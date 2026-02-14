"""Enrichment pipeline for the datasheet intelligence system.

Orchestrates the full flow: normalize part numbers, resolve datasheet URLs,
download PDFs, extract text, extract structured specs via Claude, and cache
results. Returns a mapping of component reference to DatasheetSpec.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from pathlib import Path

from revlo.datasheet.cache import DatasheetCache
from revlo.datasheet.extractor import extract_spec
from revlo.datasheet.models import DatasheetCacheEntry, DatasheetSpec, NormalizedPartNumber
from revlo.datasheet.normalizer import normalize_part
from revlo.datasheet.pdf import download_pdf, extract_text
from revlo.datasheet.resolver import resolve_datasheet_url
from revlo.parser.models import ParsedComponent, ParsedSchematic

logger = logging.getLogger(__name__)


def _find_manual_pdf(mpn: str, cache_dir: Path) -> Path | None:
    """Scan *cache_dir* recursively for a PDF whose filename contains *mpn*.

    Matching is case-insensitive and uses multiple strategies:

    1. **Exact substring** -- full MPN appears in the PDF filename.
    2. **Segment match** -- any hyphen-separated segment of the MPN (length > 3
       to avoid false positives) appears in the filename.
    3. **Reverse substring** -- the PDF stem (without ``.pdf``) appears inside
       the MPN string.

    Returns the first matching :class:`Path`, or ``None`` when no match is
    found.
    """
    if not cache_dir.is_dir():
        return None
    mpn_lower = mpn.lower()
    # Pre-compute segments by splitting on hyphens and underscores,
    # keeping only those longer than 3 chars to avoid false positives.
    segments = [seg.lower() for seg in re.split(r"[-_]", mpn) if len(seg) > 3]
    for pdf in cache_dir.rglob("*.pdf"):
        name_lower = pdf.name.lower()
        stem_lower = pdf.stem.lower()
        # Strategy 1: full MPN in filename
        if mpn_lower in name_lower:
            return pdf
        # Strategy 2: any segment of MPN in filename
        if any(seg in name_lower for seg in segments):
            return pdf
        # Strategy 3: PDF stem in MPN
        if stem_lower in mpn_lower:
            return pdf
    return None


async def _process_component(
    comp: ParsedComponent,
    part: NormalizedPartNumber,
    cache: DatasheetCache,
    cache_dir: Path,
    error_callback: Callable[[str, str], None] | None = None,
    status_callback: Callable[[str, str, str], None] | None = None,
) -> DatasheetSpec | None:
    """Run the resolve-download-extract pipeline for a single component.

    Returns a :class:`DatasheetSpec` on success, or ``None`` if any step
    fails. Errors are logged as warnings rather than raised.
    """
    mpn = part.mpn

    ref = comp.reference

    # 1. Check cache first.
    cached = cache.get(mpn)
    if cached is not None and cached.spec is not None:
        logger.info("[%s] Cache hit for %s", ref, mpn)
        if status_callback:
            status_callback(ref, mpn, "cached")
        return cached.spec

    # 2. Scan for manually placed PDFs before attempting URL resolution.
    manual_pdf = _find_manual_pdf(mpn, cache_dir)
    if manual_pdf is not None:
        logger.info("[%s] Found manual PDF: %s", ref, manual_pdf)
        if status_callback:
            status_callback(ref, mpn, "manual")
        pdf_path = manual_pdf
    else:
        # 3. Resolve datasheet URL.
        logger.info("[%s] Resolving datasheet URL for %s ...", ref, mpn)
        url = await resolve_datasheet_url(part, cache_dir=str(cache_dir))
        if url is None:
            logger.warning("[%s] No datasheet URL resolved for %s", ref, mpn)
            if status_callback:
                status_callback(ref, mpn, "failed")
            if error_callback:
                error_callback(ref, f"Could not fetch datasheet for {mpn}")
            return None

        # 4. Download PDF.
        logger.info("[%s] Downloading %s ...", ref, url)
        pdf_path = await download_pdf(url, cache_dir)
        if pdf_path is None:
            logger.warning("[%s] PDF download failed: %s", ref, url)
            if status_callback:
                status_callback(ref, mpn, "failed")
            if error_callback:
                error_callback(ref, f"PDF download failed for {mpn}")
            return None
        logger.info("[%s] Downloaded -> %s", ref, pdf_path)
        if status_callback:
            status_callback(ref, mpn, "fetched")

    # 5. Extract text from PDF.
    logger.info("[%s] Extracting text from PDF ...", ref)
    pdf_text = extract_text(pdf_path)
    if not pdf_text:
        logger.warning("[%s] No text extracted from PDF", ref)
        return None

    # 6. Extract structured spec via Claude.
    logger.info("[%s] Extracting spec via Claude ...", ref)
    spec = await extract_spec(pdf_text, mpn)
    if spec is None:
        logger.warning("[%s] Spec extraction failed for %s", ref, mpn)
        return None
    logger.info("[%s] Spec extracted successfully", ref)

    # 7. Store in cache.
    source_url = url if manual_pdf is None else ""
    entry = DatasheetCacheEntry(
        mpn=mpn,
        spec=spec,
        pdf_path=str(pdf_path),
        source_url=source_url,
    )
    cache.put(mpn, entry)

    return spec


async def enrich_schematic(
    parsed: ParsedSchematic,
    cache_dir: Path,
    progress_callback: Callable[[int, int], None] | None = None,
    error_callback: Callable[[str, str], None] | None = None,
    status_callback: Callable[[str, str, str], None] | None = None,
) -> dict[str, DatasheetSpec]:
    """Enrich a parsed schematic with datasheet specifications.

    For each component in *parsed*, normalizes the part number, resolves a
    datasheet URL, downloads the PDF, extracts text, and uses Claude to
    produce a structured :class:`DatasheetSpec`. Results are cached to disk
    so subsequent runs skip already-resolved parts.

    Generic/passive parts (resistors, capacitors, etc.) are skipped.

    Non-generic parts are processed concurrently using ``asyncio.gather``,
    though each part's internal pipeline (resolve -> download -> extract)
    runs sequentially.

    Args:
        parsed: A fully parsed KiCad schematic.
        cache_dir: Directory for PDF downloads and the cache JSON file.

    Returns:
        A dict mapping component reference designator (e.g. ``"U1"``) to
        its :class:`DatasheetSpec`. Components that could not be enriched
        are omitted from the dict.
    """
    total = len(parsed.components)

    # Load persistent cache.
    cache = DatasheetCache(cache_dir)
    cache.load()

    # Normalize all parts and partition into generic vs. non-generic.
    skipped_generic = 0
    to_process: list[tuple[ParsedComponent, NormalizedPartNumber]] = []

    for comp in parsed.components:
        part = normalize_part(comp)
        if part.is_generic:
            skipped_generic += 1
            continue
        to_process.append((comp, part))

    logger.info(
        "Enrichment: %d components total, %d generic skipped, %d to process",
        total,
        skipped_generic,
        len(to_process),
    )

    # Track progress across concurrent tasks.
    _completed = 0
    _total = len(to_process)

    if progress_callback is not None:
        progress_callback(0, _total)

    # Process non-generic parts concurrently.
    async def _safe_process(
        comp: ParsedComponent, part: NormalizedPartNumber
    ) -> tuple[str, DatasheetSpec | None]:
        """Wrapper that catches all exceptions for graceful degradation."""
        nonlocal _completed
        try:
            spec = await _process_component(comp, part, cache, cache_dir, error_callback, status_callback)
            return (comp.reference, spec)
        except Exception:
            logger.warning(
                "Unexpected error processing %s (%s)",
                comp.reference,
                part.mpn,
                exc_info=True,
            )
            return (comp.reference, None)
        finally:
            _completed += 1
            if progress_callback is not None:
                progress_callback(_completed, _total)

    results = await asyncio.gather(
        *[_safe_process(comp, part) for comp, part in to_process]
    )

    # Build output dict, counting stats.
    output: dict[str, DatasheetSpec] = {}
    cache_hits = 0
    resolved = 0

    for ref, spec in results:
        if spec is not None:
            output[ref] = spec
            resolved += 1

    # Count cache hits: entries that existed in cache before we started.
    # (Approximation: any result where the MPN was already in cache.)
    for comp, part in to_process:
        cached_entry = cache.get(part.mpn)
        if cached_entry is not None and cached_entry.spec is not None:
            cache_hits += 1

    # Persist cache.
    cache.save()

    logger.info(
        "Enriched %d of %d components (%d skipped generic, %d cache hits)",
        resolved,
        total,
        skipped_generic,
        cache_hits,
    )

    return output
