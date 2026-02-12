"""PDF download and text extraction for the datasheet intelligence pipeline."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pymupdf  # PyMuPDF

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_MAX_PDF_SIZE = 200 * 1024 * 1024  # 200 MB
_CONNECT_TIMEOUT = 10.0  # seconds
_READ_TIMEOUT = 60.0  # seconds
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
_PDF_TEXT_LIMIT = 100_000  # Max characters of extracted text

# Target section patterns for smart page selection (case-insensitive)
_BOOKMARK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"absolute maximum", re.IGNORECASE),
    re.compile(r"electrical characteristics", re.IGNORECASE),
    re.compile(r"pin\s+(description|function|definition)", re.IGNORECASE),
    re.compile(r"recommended operating", re.IGNORECASE),
]

# Keywords for fallback full-page scan (case-insensitive substrings)
_SCAN_KEYWORDS: list[str] = [
    "absolute maximum",
    "electrical characteristics",
    "pin function",
    "recommended operating",
]

# Number of leading pages always included (features / overview)
_ALWAYS_INCLUDE_PAGES = 3


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
        headers = {"User-Agent": _USER_AGENT}
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
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
# Smart page selection helpers
# ---------------------------------------------------------------------------


def _select_pages_from_bookmarks(
    toc: list[list], total_pages: int
) -> list[int] | None:
    """Return page indices for target sections found via PDF bookmarks.

    *toc* is the list returned by ``doc.get_toc()`` — each entry is
    ``[level, title, page_number]`` where *page_number* is 1-based.

    Returns a sorted, deduplicated list of 0-based page indices, or
    ``None`` if no matching bookmarks were found.
    """
    if not toc:
        return None

    matched_pages: set[int] = set()

    for idx, entry in enumerate(toc):
        _level, title, page_num = entry[:3]
        if not any(pat.search(title) for pat in _BOOKMARK_PATTERNS):
            continue

        start = page_num - 1  # convert to 0-based

        # Section extends to the next bookmark at the same or higher level,
        # or to end of document.
        end = total_pages
        for future in toc[idx + 1 :]:
            if future[0] <= _level:
                end = future[2] - 1  # 0-based exclusive
                break

        matched_pages.update(range(start, end))

    if not matched_pages:
        return None

    return sorted(matched_pages)


def _select_pages_by_keyword_scan(doc: pymupdf.Document) -> list[int]:
    """Scan every page for target keywords and return matching 0-based indices."""
    matched: set[int] = set()
    for i in range(len(doc)):
        try:
            text = doc[i].get_text().lower()
        except Exception:
            continue
        if any(kw in text for kw in _SCAN_KEYWORDS):
            matched.add(i)
    return sorted(matched)


# ---------------------------------------------------------------------------
# extract_text
# ---------------------------------------------------------------------------


def extract_text(pdf_path: Path, max_pages: int = 30) -> str:
    """Extract text from a PDF using PyMuPDF.

    For **small PDFs** (<= *max_pages* pages) the behaviour is unchanged:
    reads every page sequentially.

    For **large PDFs** (> *max_pages* pages) smart page selection kicks in:

    1. Try bookmarks first — look for target section titles
       (absolute maximum ratings, electrical characteristics, etc.) and
       extract the full section (bookmark page to next bookmark).
    2. Fallback — scan all pages for target keywords and extract matching
       pages.
    3. The first ``_ALWAYS_INCLUDE_PAGES`` pages are always included.

    Total output is capped at ``_PDF_TEXT_LIMIT`` characters.
    Returns an empty string on any error.
    """
    try:
        doc = pymupdf.open(str(pdf_path))
    except Exception as exc:
        logger.warning("Failed to open PDF %s: %s", pdf_path, exc)
        return ""

    total_pages = len(doc)

    try:
        # --- Small PDF: preserve original behaviour -------------------------
        if total_pages <= max_pages:
            parts: list[str] = []
            for i in range(total_pages):
                try:
                    text = doc[i].get_text()
                    if text:
                        parts.append(text)
                except Exception as exc:
                    logger.warning(
                        "Failed to extract page %d from %s: %s", i, pdf_path, exc
                    )
            return "\n".join(parts)

        # --- Large PDF: smart page selection --------------------------------
        # Always include the first N pages.
        selected: set[int] = set(
            range(min(_ALWAYS_INCLUDE_PAGES, total_pages))
        )

        # Try bookmark-based selection first.
        toc = doc.get_toc()
        bookmark_pages = _select_pages_from_bookmarks(toc, total_pages)

        if bookmark_pages is not None:
            selected.update(bookmark_pages)
            logger.info(
                "Bookmark selection for %s: %d target pages (+ %d overview)",
                pdf_path.name,
                len(bookmark_pages),
                _ALWAYS_INCLUDE_PAGES,
            )
        else:
            # Fallback: keyword scan.
            keyword_pages = _select_pages_by_keyword_scan(doc)
            selected.update(keyword_pages)
            logger.info(
                "Keyword scan for %s: %d matching pages (+ %d overview)",
                pdf_path.name,
                len(keyword_pages),
                _ALWAYS_INCLUDE_PAGES,
            )

        # Extract text from selected pages (sorted, deduplicated).
        parts = []
        char_count = 0
        for i in sorted(selected):
            if i >= total_pages:
                continue
            try:
                text = doc[i].get_text()
                if text:
                    if char_count + len(text) > _PDF_TEXT_LIMIT:
                        # Take as much of this page as fits.
                        remaining = _PDF_TEXT_LIMIT - char_count
                        if remaining > 0:
                            parts.append(text[:remaining])
                        break
                    parts.append(text)
                    char_count += len(text)
            except Exception as exc:
                logger.warning(
                    "Failed to extract page %d from %s: %s", i, pdf_path, exc
                )

        return "\n".join(parts)
    finally:
        doc.close()
