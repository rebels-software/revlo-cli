"""Enrichment pipeline for the datasheet intelligence system.

Orchestrates the full flow: normalize part numbers, resolve datasheet URLs,
download PDFs, extract text, extract structured specs via Claude, and cache
results. Returns a mapping of component reference to DatasheetSpec.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from revlo.datasheet.cache import DatasheetCache
from revlo.datasheet.extractor import extract_spec
from revlo.datasheet.models import DatasheetCacheEntry, DatasheetSpec, NormalizedPartNumber
from revlo.datasheet.normalizer import normalize_part
from revlo.datasheet.pdf import download_pdf, extract_text
from revlo.datasheet.resolver import resolve_datasheet_url
from revlo.parser.models import ParsedComponent, ParsedSchematic

logger = logging.getLogger(__name__)


async def _process_component(
    comp: ParsedComponent,
    part: NormalizedPartNumber,
    cache: DatasheetCache,
    cache_dir: Path,
) -> DatasheetSpec | None:
    """Run the resolve-download-extract pipeline for a single component.

    Returns a :class:`DatasheetSpec` on success, or ``None`` if any step
    fails. Errors are logged as warnings rather than raised.
    """
    mpn = part.mpn

    # 1. Check cache first.
    cached = cache.get(mpn)
    if cached is not None and cached.spec is not None:
        logger.info("Cache hit for %s (%s)", comp.reference, mpn)
        return cached.spec

    # 2. Resolve datasheet URL.
    url = await resolve_datasheet_url(part)
    if url is None:
        logger.warning("No datasheet URL resolved for %s (%s)", comp.reference, mpn)
        return None

    # 3. Download PDF.
    pdf_path = await download_pdf(url, cache_dir)
    if pdf_path is None:
        logger.warning("PDF download failed for %s (%s): %s", comp.reference, mpn, url)
        return None

    # 4. Extract text from PDF.
    pdf_text = extract_text(pdf_path)
    if not pdf_text:
        logger.warning("No text extracted from PDF for %s (%s)", comp.reference, mpn)
        return None

    # 5. Extract structured spec via Claude.
    spec = await extract_spec(pdf_text, mpn)
    if spec is None:
        logger.warning("Spec extraction failed for %s (%s)", comp.reference, mpn)
        return None

    # 6. Store in cache.
    entry = DatasheetCacheEntry(
        mpn=mpn,
        spec=spec,
        pdf_path=str(pdf_path),
        source_url=url,
    )
    cache.put(mpn, entry)

    return spec


async def enrich_schematic(
    parsed: ParsedSchematic,
    cache_dir: Path,
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

    # Process non-generic parts concurrently.
    async def _safe_process(
        comp: ParsedComponent, part: NormalizedPartNumber
    ) -> tuple[str, DatasheetSpec | None]:
        """Wrapper that catches all exceptions for graceful degradation."""
        try:
            spec = await _process_component(comp, part, cache, cache_dir)
            return (comp.reference, spec)
        except Exception:
            logger.warning(
                "Unexpected error processing %s (%s)",
                comp.reference,
                part.mpn,
                exc_info=True,
            )
            return (comp.reference, None)

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
