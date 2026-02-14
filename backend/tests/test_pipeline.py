"""Tests for revlo.datasheet.pipeline — enrichment orchestration."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from revlo.datasheet.cache import DatasheetCache
from revlo.datasheet.models import (
    DatasheetCacheEntry,
    DatasheetSpec,
    NormalizedPartNumber,
)
from revlo.datasheet.pipeline import enrich_schematic
from revlo.parser.models import ParsedComponent, ParsedSchematic


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------


def _make_component(reference: str, value: str, lib_id: str) -> ParsedComponent:
    """Helper to create a minimal ParsedComponent."""
    return ParsedComponent(
        reference=reference,
        value=value,
        lib_id=lib_id,
    )


def _make_normalized_part(
    mpn: str,
    manufacturer: str = "TestMfg",
    is_generic: bool = False,
) -> NormalizedPartNumber:
    """Helper to create a NormalizedPartNumber."""
    return NormalizedPartNumber(
        raw_value=mpn,
        mpn=mpn,
        manufacturer=manufacturer,
        is_generic=is_generic,
    )


def _make_spec(mpn: str, description: str = "Test component") -> DatasheetSpec:
    """Helper to create a DatasheetSpec."""
    return DatasheetSpec(
        mpn=mpn,
        manufacturer="TestMfg",
        description=description,
        supply_voltage_min=3.0,
        supply_voltage_max=5.5,
    )


# -------------------------------------------------------------------------
# Empty and Generic-Only Schematics
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_schematic_returns_empty_dict(tmp_path: Path):
    """Empty schematic returns empty dict without errors."""
    parsed = ParsedSchematic(components=[])
    result = await enrich_schematic(parsed, tmp_path)
    assert result == {}


@pytest.mark.asyncio
@patch("revlo.datasheet.pipeline.normalize_part")
async def test_all_generic_parts_returns_empty_dict(
    mock_normalize: MagicMock, tmp_path: Path
):
    """Schematic with only generic parts returns empty dict."""
    # Set up schematic with passives.
    parsed = ParsedSchematic(
        components=[
            _make_component("R1", "10k", "Device:R"),
            _make_component("C1", "100nF", "Device:C"),
            _make_component("L1", "10uH", "Device:L"),
        ]
    )

    # Mock normalizer to return generic parts.
    mock_normalize.side_effect = [
        _make_normalized_part("R", is_generic=True),
        _make_normalized_part("C", is_generic=True),
        _make_normalized_part("L", is_generic=True),
    ]

    result = await enrich_schematic(parsed, tmp_path)

    assert result == {}
    assert mock_normalize.call_count == 3


# -------------------------------------------------------------------------
# Cache Hit Scenarios
# -------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("revlo.datasheet.pipeline.normalize_part")
@patch("revlo.datasheet.pipeline.DatasheetCache")
async def test_cache_hit_returns_cached_spec_without_pipeline(
    mock_cache_class: MagicMock,
    mock_normalize: MagicMock,
    tmp_path: Path,
):
    """Cache hit returns cached spec without calling resolve/download/extract."""
    # Set up component.
    comp = _make_component("U1", "STM32F103", "MCU:STM32F103CBT6")
    parsed = ParsedSchematic(components=[comp])

    # Mock normalizer.
    normalized = _make_normalized_part("STM32F103CBT6")
    mock_normalize.return_value = normalized

    # Mock cache with a hit.
    cached_spec = _make_spec("STM32F103CBT6", "STM32 MCU")
    cached_entry = DatasheetCacheEntry(
        mpn="STM32F103CBT6",
        spec=cached_spec,
        source_url="https://example.com/stm32.pdf",
    )

    mock_cache_instance = MagicMock()
    mock_cache_instance.get.return_value = cached_entry
    mock_cache_class.return_value = mock_cache_instance

    # Call pipeline.
    with patch("revlo.datasheet.pipeline.resolve_datasheet_url") as mock_resolve, \
         patch("revlo.datasheet.pipeline.download_pdf") as mock_download, \
         patch("revlo.datasheet.pipeline.extract_text") as mock_extract_text, \
         patch("revlo.datasheet.pipeline.extract_spec") as mock_extract_spec:

        result = await enrich_schematic(parsed, tmp_path)

    # Assertions.
    assert result == {"U1": cached_spec}
    # Cache.get() is called twice: once in _process_component, once when counting hits.
    assert mock_cache_instance.get.call_count == 2
    mock_cache_instance.save.assert_called_once()

    # Verify pipeline steps were NOT called.
    mock_resolve.assert_not_called()
    mock_download.assert_not_called()
    mock_extract_text.assert_not_called()
    mock_extract_spec.assert_not_called()


# -------------------------------------------------------------------------
# Full Pipeline Success
# -------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("revlo.datasheet.pipeline.normalize_part")
@patch("revlo.datasheet.pipeline.resolve_datasheet_url")
@patch("revlo.datasheet.pipeline.download_pdf")
@patch("revlo.datasheet.pipeline.extract_text")
@patch("revlo.datasheet.pipeline.extract_spec")
@patch("revlo.datasheet.pipeline.DatasheetCache")
async def test_full_pipeline_success(
    mock_cache_class: MagicMock,
    mock_extract_spec: AsyncMock,
    mock_extract_text: MagicMock,
    mock_download: AsyncMock,
    mock_resolve: AsyncMock,
    mock_normalize: MagicMock,
    tmp_path: Path,
):
    """Full pipeline: resolve -> download -> extract -> returns spec and caches."""
    # Set up component.
    comp = _make_component("U2", "LM7805", "Regulator:LM7805")
    parsed = ParsedSchematic(components=[comp])

    # Mock normalizer.
    normalized = _make_normalized_part("LM7805CT")
    mock_normalize.return_value = normalized

    # Mock cache (miss on first get).
    mock_cache_instance = MagicMock()
    mock_cache_instance.get.return_value = None
    mock_cache_class.return_value = mock_cache_instance

    # Mock pipeline steps.
    pdf_path = tmp_path / "datasheets" / "test.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_text("fake pdf")

    mock_resolve.return_value = "https://example.com/lm7805.pdf"
    mock_download.return_value = pdf_path
    mock_extract_text.return_value = "LM7805 datasheet text..."
    spec = _make_spec("LM7805CT", "5V Regulator")
    mock_extract_spec.return_value = spec

    # Call pipeline.
    result = await enrich_schematic(parsed, tmp_path)

    # Assertions.
    assert result == {"U2": spec}
    mock_cache_instance.get.assert_called_with("LM7805CT")
    mock_resolve.assert_called_once_with(normalized, cache_dir=str(tmp_path))
    mock_download.assert_called_once_with("https://example.com/lm7805.pdf", tmp_path)
    mock_extract_text.assert_called_once_with(pdf_path)
    mock_extract_spec.assert_called_once_with("LM7805 datasheet text...", "LM7805CT")
    mock_cache_instance.put.assert_called_once()
    mock_cache_instance.save.assert_called_once()


# -------------------------------------------------------------------------
# Pipeline Step Failures
# -------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("revlo.datasheet.pipeline.normalize_part")
@patch("revlo.datasheet.pipeline.resolve_datasheet_url")
@patch("revlo.datasheet.pipeline.DatasheetCache")
async def test_resolve_returns_none_skips_component(
    mock_cache_class: MagicMock,
    mock_resolve: AsyncMock,
    mock_normalize: MagicMock,
    tmp_path: Path,
):
    """Component with failed resolution (no URL) is skipped."""
    comp = _make_component("U3", "UnknownPart", "Unknown:Part")
    parsed = ParsedSchematic(components=[comp])

    normalized = _make_normalized_part("UnknownPart")
    mock_normalize.return_value = normalized

    mock_cache_instance = MagicMock()
    mock_cache_instance.get.return_value = None
    mock_cache_class.return_value = mock_cache_instance

    # Resolver returns None.
    mock_resolve.return_value = None

    result = await enrich_schematic(parsed, tmp_path)

    assert result == {}
    mock_resolve.assert_called_once_with(normalized, cache_dir=str(tmp_path))
    mock_cache_instance.save.assert_called_once()


@pytest.mark.asyncio
@patch("revlo.datasheet.pipeline.normalize_part")
@patch("revlo.datasheet.pipeline.resolve_datasheet_url")
@patch("revlo.datasheet.pipeline.download_pdf")
@patch("revlo.datasheet.pipeline.DatasheetCache")
async def test_download_returns_none_skips_component(
    mock_cache_class: MagicMock,
    mock_download: AsyncMock,
    mock_resolve: AsyncMock,
    mock_normalize: MagicMock,
    tmp_path: Path,
):
    """Component with failed download is skipped."""
    comp = _make_component("U4", "BadDownload", "IC:BadDownload")
    parsed = ParsedSchematic(components=[comp])

    normalized = _make_normalized_part("BadDownload")
    mock_normalize.return_value = normalized

    mock_cache_instance = MagicMock()
    mock_cache_instance.get.return_value = None
    mock_cache_class.return_value = mock_cache_instance

    mock_resolve.return_value = "https://example.com/bad.pdf"
    # Download fails.
    mock_download.return_value = None

    result = await enrich_schematic(parsed, tmp_path)

    assert result == {}
    mock_download.assert_called_once()
    mock_cache_instance.save.assert_called_once()


@pytest.mark.asyncio
@patch("revlo.datasheet.pipeline.normalize_part")
@patch("revlo.datasheet.pipeline.resolve_datasheet_url")
@patch("revlo.datasheet.pipeline.download_pdf")
@patch("revlo.datasheet.pipeline.extract_text")
@patch("revlo.datasheet.pipeline.DatasheetCache")
async def test_extract_text_returns_empty_skips_component(
    mock_cache_class: MagicMock,
    mock_extract_text: MagicMock,
    mock_download: AsyncMock,
    mock_resolve: AsyncMock,
    mock_normalize: MagicMock,
    tmp_path: Path,
):
    """Component with failed text extraction (empty string) is skipped."""
    comp = _make_component("U5", "NoText", "IC:NoText")
    parsed = ParsedSchematic(components=[comp])

    normalized = _make_normalized_part("NoText")
    mock_normalize.return_value = normalized

    mock_cache_instance = MagicMock()
    mock_cache_instance.get.return_value = None
    mock_cache_class.return_value = mock_cache_instance

    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_text("fake")

    mock_resolve.return_value = "https://example.com/notext.pdf"
    mock_download.return_value = pdf_path
    # Text extraction returns empty string.
    mock_extract_text.return_value = ""

    result = await enrich_schematic(parsed, tmp_path)

    assert result == {}
    mock_extract_text.assert_called_once()
    mock_cache_instance.save.assert_called_once()


@pytest.mark.asyncio
@patch("revlo.datasheet.pipeline.normalize_part")
@patch("revlo.datasheet.pipeline.resolve_datasheet_url")
@patch("revlo.datasheet.pipeline.download_pdf")
@patch("revlo.datasheet.pipeline.extract_text")
@patch("revlo.datasheet.pipeline.extract_spec")
@patch("revlo.datasheet.pipeline.DatasheetCache")
async def test_extract_spec_returns_none_skips_component(
    mock_cache_class: MagicMock,
    mock_extract_spec: AsyncMock,
    mock_extract_text: MagicMock,
    mock_download: AsyncMock,
    mock_resolve: AsyncMock,
    mock_normalize: MagicMock,
    tmp_path: Path,
):
    """Component with failed spec extraction returns None is skipped."""
    comp = _make_component("U6", "NoSpec", "IC:NoSpec")
    parsed = ParsedSchematic(components=[comp])

    normalized = _make_normalized_part("NoSpec")
    mock_normalize.return_value = normalized

    mock_cache_instance = MagicMock()
    mock_cache_instance.get.return_value = None
    mock_cache_class.return_value = mock_cache_instance

    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_text("fake")

    mock_resolve.return_value = "https://example.com/nospec.pdf"
    mock_download.return_value = pdf_path
    mock_extract_text.return_value = "Some text but extraction fails"
    # Spec extraction returns None.
    mock_extract_spec.return_value = None

    result = await enrich_schematic(parsed, tmp_path)

    assert result == {}
    mock_extract_spec.assert_called_once()
    mock_cache_instance.save.assert_called_once()


# -------------------------------------------------------------------------
# Mixed Scenarios
# -------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("revlo.datasheet.pipeline.normalize_part")
@patch("revlo.datasheet.pipeline.resolve_datasheet_url")
@patch("revlo.datasheet.pipeline.download_pdf")
@patch("revlo.datasheet.pipeline.extract_text")
@patch("revlo.datasheet.pipeline.extract_spec")
@patch("revlo.datasheet.pipeline.DatasheetCache")
async def test_mixed_generic_cached_resolved(
    mock_cache_class: MagicMock,
    mock_extract_spec: AsyncMock,
    mock_extract_text: MagicMock,
    mock_download: AsyncMock,
    mock_resolve: AsyncMock,
    mock_normalize: MagicMock,
    tmp_path: Path,
):
    """Mixed: one generic (skipped), one cached, one resolved -> correct dict."""
    # Three components: R1 (generic), U1 (cached), U2 (resolved).
    parsed = ParsedSchematic(
        components=[
            _make_component("R1", "10k", "Device:R"),
            _make_component("U1", "STM32", "MCU:STM32F103"),
            _make_component("U2", "LM358", "Amplifier:LM358"),
        ]
    )

    # Mock normalizer.
    generic_part = _make_normalized_part("R", is_generic=True)
    cached_part = _make_normalized_part("STM32F103CBT6")
    resolved_part = _make_normalized_part("LM358P")
    mock_normalize.side_effect = [generic_part, cached_part, resolved_part]

    # Mock cache: hit for U1, miss for U2.
    cached_spec = _make_spec("STM32F103CBT6", "STM32 MCU")
    cached_entry = DatasheetCacheEntry(
        mpn="STM32F103CBT6",
        spec=cached_spec,
        source_url="https://example.com/stm32.pdf",
    )

    def cache_get_side_effect(mpn: str):
        if mpn == "STM32F103CBT6":
            return cached_entry
        return None

    mock_cache_instance = MagicMock()
    mock_cache_instance.get.side_effect = cache_get_side_effect
    mock_cache_class.return_value = mock_cache_instance

    # Mock pipeline for U2.  Place the PDF in a subdirectory so that
    # _find_manual_pdf does not pick it up via reverse-substring matching
    # (the stem "lm358" would match MPN "LM358P").
    dl_dir = tmp_path / "_downloads"
    dl_dir.mkdir()
    pdf_path = dl_dir / "d41d8cd9.pdf"
    pdf_path.write_text("fake")

    mock_resolve.return_value = "https://example.com/lm358.pdf"
    mock_download.return_value = pdf_path
    mock_extract_text.return_value = "LM358 text"
    resolved_spec = _make_spec("LM358P", "Op-Amp")
    mock_extract_spec.return_value = resolved_spec

    # Call pipeline.
    result = await enrich_schematic(parsed, tmp_path)

    # Assertions.
    assert len(result) == 2
    assert result["U1"] == cached_spec
    assert result["U2"] == resolved_spec

    # Verify generic was skipped.
    assert "R1" not in result

    # Verify resolve/download/extract called only once (for U2).
    mock_resolve.assert_called_once_with(resolved_part, cache_dir=str(tmp_path))
    mock_download.assert_called_once()
    mock_extract_text.assert_called_once()
    mock_extract_spec.assert_called_once()

    mock_cache_instance.save.assert_called_once()


@pytest.mark.asyncio
@patch("revlo.datasheet.pipeline.normalize_part")
@patch("revlo.datasheet.pipeline.resolve_datasheet_url")
@patch("revlo.datasheet.pipeline.download_pdf")
@patch("revlo.datasheet.pipeline.extract_text")
@patch("revlo.datasheet.pipeline.extract_spec")
@patch("revlo.datasheet.pipeline.DatasheetCache")
async def test_partial_success_multiple_components(
    mock_cache_class: MagicMock,
    mock_extract_spec: AsyncMock,
    mock_extract_text: MagicMock,
    mock_download: AsyncMock,
    mock_resolve: AsyncMock,
    mock_normalize: MagicMock,
    tmp_path: Path,
):
    """Multiple components: some succeed, some fail at various stages."""
    parsed = ParsedSchematic(
        components=[
            _make_component("U1", "Success1", "IC:Success1"),
            _make_component("U2", "FailResolve", "IC:FailResolve"),
            _make_component("U3", "Success2", "IC:Success2"),
        ]
    )

    # Mock normalizer.
    norm1 = _make_normalized_part("Success1")
    norm2 = _make_normalized_part("FailResolve")
    norm3 = _make_normalized_part("Success2")
    mock_normalize.side_effect = [norm1, norm2, norm3]

    # Mock cache (all misses).
    mock_cache_instance = MagicMock()
    mock_cache_instance.get.return_value = None
    mock_cache_class.return_value = mock_cache_instance

    # Mock resolver: U1 and U3 succeed, U2 fails.
    async def resolve_side_effect(part, cache_dir=None):
        if part.mpn in ["Success1", "Success2"]:
            return f"https://example.com/{part.mpn}.pdf"
        return None

    mock_resolve.side_effect = resolve_side_effect

    # Mock download/extract for successes.
    pdf1 = tmp_path / "success1.pdf"
    pdf2 = tmp_path / "success2.pdf"
    pdf1.write_text("fake1")
    pdf2.write_text("fake2")

    async def download_side_effect(url, cache_dir):
        if "Success1" in url:
            return pdf1
        if "Success2" in url:
            return pdf2
        return None

    mock_download.side_effect = download_side_effect
    mock_extract_text.side_effect = ["Text1", "Text2"]

    spec1 = _make_spec("Success1")
    spec2 = _make_spec("Success2")
    mock_extract_spec.side_effect = [spec1, spec2]

    # Call pipeline.
    result = await enrich_schematic(parsed, tmp_path)

    # Assertions.
    assert len(result) == 2
    assert result["U1"] == spec1
    assert result["U3"] == spec2
    assert "U2" not in result

    mock_cache_instance.save.assert_called_once()


# -------------------------------------------------------------------------
# Concurrent Processing
# -------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("revlo.datasheet.pipeline.normalize_part")
@patch("revlo.datasheet.pipeline.resolve_datasheet_url")
@patch("revlo.datasheet.pipeline.download_pdf")
@patch("revlo.datasheet.pipeline.extract_text")
@patch("revlo.datasheet.pipeline.extract_spec")
@patch("revlo.datasheet.pipeline.DatasheetCache")
@patch("revlo.datasheet.pipeline._find_manual_pdf", return_value=None)
async def test_concurrent_processing_multiple_components(
    mock_find_manual: MagicMock,
    mock_cache_class: MagicMock,
    mock_extract_spec: AsyncMock,
    mock_extract_text: MagicMock,
    mock_download: AsyncMock,
    mock_resolve: AsyncMock,
    mock_normalize: MagicMock,
    tmp_path: Path,
):
    """Multiple components are processed concurrently."""
    # Create multiple components.
    parsed = ParsedSchematic(
        components=[
            _make_component(f"U{i}", f"Part{i}", f"IC:Part{i}")
            for i in range(1, 4)
        ]
    )

    # Mock normalizer.
    mock_normalize.side_effect = [
        _make_normalized_part(f"Part{i}") for i in range(1, 4)
    ]

    # Mock cache (all misses).
    mock_cache_instance = MagicMock()
    mock_cache_instance.get.return_value = None
    mock_cache_class.return_value = mock_cache_instance

    # Mock all pipeline steps to succeed.
    mock_resolve.side_effect = [
        f"https://example.com/part{i}.pdf" for i in range(1, 4)
    ]

    pdfs = []
    for i in range(1, 4):
        pdf = tmp_path / f"part{i}.pdf"
        pdf.write_text(f"fake{i}")
        pdfs.append(pdf)

    mock_download.side_effect = pdfs
    mock_extract_text.side_effect = [f"Text{i}" for i in range(1, 4)]
    mock_extract_spec.side_effect = [
        _make_spec(f"Part{i}") for i in range(1, 4)
    ]

    # Call pipeline.
    result = await enrich_schematic(parsed, tmp_path)

    # Verify all components processed.
    assert len(result) == 3
    assert all(f"U{i}" in result for i in range(1, 4))

    # Verify all steps called (concurrent processing means asyncio.gather was used).
    assert mock_resolve.call_count == 3
    assert mock_download.call_count == 3
    assert mock_extract_text.call_count == 3
    assert mock_extract_spec.call_count == 3


# -------------------------------------------------------------------------
# Exception Handling
# -------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("revlo.datasheet.pipeline.normalize_part")
@patch("revlo.datasheet.pipeline.resolve_datasheet_url")
@patch("revlo.datasheet.pipeline.DatasheetCache")
async def test_unexpected_exception_caught_and_logged(
    mock_cache_class: MagicMock,
    mock_resolve: AsyncMock,
    mock_normalize: MagicMock,
    tmp_path: Path,
):
    """Unexpected exception in component processing is caught, logged, and component skipped."""
    comp = _make_component("U7", "Exception", "IC:Exception")
    parsed = ParsedSchematic(components=[comp])

    normalized = _make_normalized_part("Exception")
    mock_normalize.return_value = normalized

    mock_cache_instance = MagicMock()
    mock_cache_instance.get.return_value = None
    mock_cache_class.return_value = mock_cache_instance

    # Resolver raises unexpected exception.
    mock_resolve.side_effect = RuntimeError("Unexpected error")

    # Call pipeline (should not raise).
    result = await enrich_schematic(parsed, tmp_path)

    assert result == {}
    mock_cache_instance.save.assert_called_once()
