"""PDF download and text extraction for the datasheet intelligence pipeline."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pymupdf  # PyMuPDF

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_MAX_PDF_SIZE = 200 * 1024 * 1024  # 200 MB
_CONNECT_TIMEOUT = 30.0  # seconds
_READ_TIMEOUT = 60.0  # seconds


def _sha256(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# download_pdf
# ---------------------------------------------------------------------------


async def download_pdf(url: str, cache_dir: Path) -> Path | None:
    """Download a PDF from *url* into a vendor-specific subdirectory of *cache_dir*.

    Returns the local ``Path`` on success, or ``None`` on any failure
    (network error, timeout, size exceeded, etc.).

    De-duplication: if a file with the same SHA-256 already exists in the
    vendor directory the duplicate is removed and the existing path is
    returned instead.
    """
    # --- Parse URL --------------------------------------------------------
    try:
        parsed = urlparse(url)
        vendor_domain = parsed.hostname or "unknown"
        filename = Path(parsed.path).name or "download.pdf"
    except Exception:
        logger.warning("Failed to parse URL: %s", url)
        return None

    vendor_dir = cache_dir / vendor_domain
    dest = vendor_dir / filename

    # If the exact file already exists, return it immediately.
    if dest.exists():
        logger.info("Cache hit: %s", dest)
        return dest

    # --- Download ---------------------------------------------------------
    timeout = httpx.Timeout(connect=_CONNECT_TIMEOUT, read=_READ_TIMEOUT, write=_READ_TIMEOUT, pool=_CONNECT_TIMEOUT)

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            # Use streaming to inspect Content-Length before downloading body.
            async with client.stream("GET", url) as response:
                response.raise_for_status()

                # Check Content-Length header (if provided).
                content_length = response.headers.get("content-length")
                if content_length is not None:
                    try:
                        if int(content_length) > _MAX_PDF_SIZE:
                            logger.warning(
                                "PDF too large (%s bytes), skipping: %s",
                                content_length,
                                url,
                            )
                            return None
                    except ValueError:
                        pass  # Non-integer Content-Length; continue downloading.

                # Stream to a temporary file in the vendor dir.
                vendor_dir.mkdir(parents=True, exist_ok=True)
                tmp_path = dest.with_suffix(".tmp")

                downloaded = 0
                try:
                    with open(tmp_path, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=8192):
                            downloaded += len(chunk)
                            if downloaded > _MAX_PDF_SIZE:
                                logger.warning(
                                    "PDF exceeded %d bytes during download, aborting: %s",
                                    _MAX_PDF_SIZE,
                                    url,
                                )
                                f.close()
                                tmp_path.unlink(missing_ok=True)
                                return None
                            f.write(chunk)
                except Exception:
                    tmp_path.unlink(missing_ok=True)
                    raise

                # Rename tmp -> final destination.
                tmp_path.rename(dest)

    except httpx.HTTPStatusError as exc:
        logger.warning("HTTP %s for %s", exc.response.status_code, url)
        return None
    except (httpx.RequestError, OSError) as exc:
        logger.warning("Download failed for %s: %s", url, exc)
        return None

    logger.info("Downloaded %s -> %s (%d bytes)", url, dest, dest.stat().st_size)

    # --- SHA-256 de-duplication -------------------------------------------
    new_hash = _sha256(dest)

    for existing in vendor_dir.iterdir():
        if existing == dest or not existing.is_file() or existing.suffix == ".tmp":
            continue
        if _sha256(existing) == new_hash:
            logger.info(
                "Duplicate detected: %s matches %s (sha256=%s). Removing duplicate.",
                dest.name,
                existing.name,
                new_hash,
            )
            dest.unlink()
            return existing

    return dest


# ---------------------------------------------------------------------------
# extract_text
# ---------------------------------------------------------------------------


def extract_text(pdf_path: Path, max_pages: int = 30) -> str:
    """Extract text from a PDF using PyMuPDF.

    Reads at most *max_pages* pages and returns the concatenated text.
    Returns an empty string on any error.
    """
    try:
        doc = pymupdf.open(str(pdf_path))
    except Exception as exc:
        logger.warning("Failed to open PDF %s: %s", pdf_path, exc)
        return ""

    pages_to_read = min(len(doc), max_pages)
    parts: list[str] = []

    try:
        for i in range(pages_to_read):
            try:
                page = doc[i]
                text = page.get_text()
                if text:
                    parts.append(text)
            except Exception as exc:
                logger.warning("Failed to extract page %d from %s: %s", i, pdf_path, exc)
    finally:
        doc.close()

    return "\n".join(parts)
