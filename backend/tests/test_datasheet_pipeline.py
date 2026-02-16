"""Test suite for the datasheet enrichment pipeline (pipeline.py).

Covers the progress_callback feature and manual PDF detection fallback.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from revlo.datasheet.models import DatasheetCacheEntry, DatasheetSpec, NormalizedPartNumber
from revlo.datasheet.pipeline import _find_manual_pdf, enrich_schematic
from revlo.parser.models import ParsedComponent, ParsedSchematic, TitleBlockInfo


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def non_generic_part() -> NormalizedPartNumber:
    return NormalizedPartNumber(
        raw_value="STM32F103C8T6",
        mpn="STM32F103C8T6",
        manufacturer="STMicroelectronics",
        is_generic=False,
    )


@pytest.fixture
def generic_part() -> NormalizedPartNumber:
    return NormalizedPartNumber(
        raw_value="100nF",
        mpn="100nF",
        is_generic=True,
    )


@pytest.fixture
def mock_spec() -> DatasheetSpec:
    return DatasheetSpec(
        mpn="STM32F103C8T6",
        manufacturer="STMicroelectronics",
        description="ARM Cortex-M3 MCU",
        supply_voltage_min=2.0,
        supply_voltage_max=3.6,
    )


@pytest.fixture
def simple_schematic() -> ParsedSchematic:
    return ParsedSchematic(
        components=[
            ParsedComponent(
                reference="U1",
                value="STM32F103C8T6",
                lib_id="MCU_ST_STM32F1:STM32F103C8T6",
                footprint="LQFP-48",
                position=(50.0, 50.0),
                properties={},
                pins=[],
            ),
        ],
        nets=[],
        title_block=TitleBlockInfo(
            title="Test", date="2026-02-14", revision="1.0", company="Test",
        ),
    )


@pytest.fixture
def two_comp_schematic() -> ParsedSchematic:
    """Schematic with two non-generic components."""
    return ParsedSchematic(
        components=[
            ParsedComponent(
                reference="U1",
                value="STM32F103C8T6",
                lib_id="MCU_ST:STM32F103C8T6",
                footprint="LQFP-48",
                position=(50.0, 50.0),
                properties={},
                pins=[],
            ),
            ParsedComponent(
                reference="U2",
                value="ESP32-WROOM-32",
                lib_id="RF:ESP32-WROOM-32",
                footprint="ESP32-WROOM-32",
                position=(100.0, 50.0),
                properties={},
                pins=[],
            ),
        ],
        nets=[],
        title_block=TitleBlockInfo(
            title="Test", date="2026-02-14", revision="1.0", company="Test",
        ),
    )


# ---------------------------------------------------------------------------
# _find_manual_pdf
# ---------------------------------------------------------------------------
class TestFindManualPdf:
    """Tests for the manual PDF scanner."""

    def test_finds_matching_pdf(self, tmp_path: Path) -> None:
        """A PDF whose name contains the MPN is found."""
        pdf = tmp_path / "stm32f103c8t6-datasheet.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        result = _find_manual_pdf("STM32F103C8T6", tmp_path)
        assert result == pdf

    def test_case_insensitive_match(self, tmp_path: Path) -> None:
        """Matching is case-insensitive on both MPN and filename."""
        pdf = tmp_path / "STM32F103C8T6.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        result = _find_manual_pdf("stm32f103c8t6", tmp_path)
        assert result == pdf

    def test_finds_pdf_in_subdirectory(self, tmp_path: Path) -> None:
        """PDFs in subdirectories are scanned recursively."""
        subdir = tmp_path / "vendor" / "st"
        subdir.mkdir(parents=True)
        pdf = subdir / "STM32F103C8T6_rev4.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        result = _find_manual_pdf("STM32F103C8T6", tmp_path)
        assert result == pdf

    def test_no_match_returns_none(self, tmp_path: Path) -> None:
        """Returns None when no PDF matches."""
        pdf = tmp_path / "unrelated-datasheet.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        result = _find_manual_pdf("STM32F103C8T6", tmp_path)
        assert result is None

    def test_nonexistent_directory_returns_none(self) -> None:
        """Returns None when cache_dir does not exist."""
        result = _find_manual_pdf("STM32F103C8T6", Path("/nonexistent/dir"))
        assert result is None

    def test_empty_directory_returns_none(self, tmp_path: Path) -> None:
        """Returns None when directory has no PDFs."""
        result = _find_manual_pdf("STM32F103C8T6", tmp_path)
        assert result is None

    def test_segment_match_rescue_lib_id(self, tmp_path: Path) -> None:
        """Matches when a hyphen-separated segment of MPN appears in filename."""
        pdf = tmp_path / "stm32f103tb.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        # MPN from rescue lib_id: segment 'STM32F103CBTx' doesn't match
        # but segment 'STM32F1' does appear in the filename.
        result = _find_manual_pdf("STM32F103CBTx-MCU_ST_STM32F1", tmp_path)
        assert result == pdf

    def test_reverse_substring_match(self, tmp_path: Path) -> None:
        """Matches when the PDF stem is a substring of the MPN."""
        pdf = tmp_path / "stm32f103.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        result = _find_manual_pdf("STM32F103CBTx", tmp_path)
        assert result == pdf

    def test_short_segments_skipped(self, tmp_path: Path) -> None:
        """Segments shorter than 4 chars are not matched to avoid false positives."""
        pdf = tmp_path / "random-st-data.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        # 'ST' is a 2-char segment so should NOT match via segment strategy
        result = _find_manual_pdf("LM7805-ST", tmp_path)
        assert result is None


# ---------------------------------------------------------------------------
# Progress callback in enrich_schematic
# ---------------------------------------------------------------------------
class TestProgressCallback:
    """Tests for the progress_callback parameter of enrich_schematic."""

    @patch("revlo.datasheet.pipeline.extract_spec", new_callable=AsyncMock)
    @patch("revlo.datasheet.pipeline.extract_text")
    @patch("revlo.datasheet.pipeline.download_pdf", new_callable=AsyncMock)
    @patch("revlo.datasheet.pipeline.resolve_datasheet_url", new_callable=AsyncMock)
    @patch("revlo.datasheet.pipeline.normalize_part")
    @patch("revlo.datasheet.pipeline.DatasheetCache")
    def test_callback_called_with_progress(
        self,
        MockCache: MagicMock,
        mock_normalize: MagicMock,
        mock_resolve: AsyncMock,
        mock_download: AsyncMock,
        mock_extract_text: MagicMock,
        mock_extract_spec: AsyncMock,
        simple_schematic: ParsedSchematic,
        non_generic_part: NormalizedPartNumber,
        mock_spec: DatasheetSpec,
        tmp_path: Path,
    ) -> None:
        """Callback receives (0, total) initially, then (1, total) on completion."""
        mock_normalize.return_value = non_generic_part
        cache_instance = MockCache.return_value
        cache_instance.get.return_value = None

        mock_resolve.return_value = "https://example.com/ds.pdf"
        mock_download.return_value = tmp_path / "ds.pdf"
        mock_extract_text.return_value = ("PDF text content", [1, 2, 3])
        mock_extract_spec.return_value = mock_spec

        calls: list[tuple[int, int]] = []

        def on_progress(completed: int, total: int) -> None:
            calls.append((completed, total))

        asyncio.run(
            enrich_schematic(
                simple_schematic, tmp_path, progress_callback=on_progress,
            )
        )

        # First call: (0, 1) — initial, then (1, 1) — completion
        assert calls[0] == (0, 1)
        assert calls[-1] == (1, 1)

    @patch("revlo.datasheet.pipeline.normalize_part")
    @patch("revlo.datasheet.pipeline.DatasheetCache")
    def test_callback_with_multiple_components(
        self,
        MockCache: MagicMock,
        mock_normalize: MagicMock,
        two_comp_schematic: ParsedSchematic,
        tmp_path: Path,
    ) -> None:
        """Callback reports correct total for multiple non-generic components."""
        part1 = NormalizedPartNumber(
            raw_value="STM32F103C8T6", mpn="STM32F103C8T6", is_generic=False,
        )
        part2 = NormalizedPartNumber(
            raw_value="ESP32-WROOM-32", mpn="ESP32-WROOM-32", is_generic=False,
        )
        mock_normalize.side_effect = [part1, part2]
        cache_instance = MockCache.return_value
        # Both are cache hits so pipeline finishes quickly.
        cache_instance.get.return_value = DatasheetCacheEntry(
            mpn="x", spec=DatasheetSpec(mpn="x"),
        )

        calls: list[tuple[int, int]] = []

        def on_progress(completed: int, total: int) -> None:
            calls.append((completed, total))

        asyncio.run(
            enrich_schematic(
                two_comp_schematic, tmp_path, progress_callback=on_progress,
            )
        )

        # Initial (0,2), then two completions ending at (2,2)
        assert calls[0] == (0, 2)
        assert calls[-1][0] == 2
        assert calls[-1][1] == 2

    @patch("revlo.datasheet.pipeline.normalize_part")
    @patch("revlo.datasheet.pipeline.DatasheetCache")
    def test_no_callback_does_not_error(
        self,
        MockCache: MagicMock,
        mock_normalize: MagicMock,
        simple_schematic: ParsedSchematic,
        non_generic_part: NormalizedPartNumber,
        tmp_path: Path,
    ) -> None:
        """Omitting progress_callback does not raise."""
        mock_normalize.return_value = non_generic_part
        cache_instance = MockCache.return_value
        cache_instance.get.return_value = DatasheetCacheEntry(
            mpn="STM32F103C8T6", spec=DatasheetSpec(mpn="STM32F103C8T6"),
        )

        # Should not raise even without callback
        result = asyncio.run(enrich_schematic(simple_schematic, tmp_path))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Manual PDF fallback in _process_component
# ---------------------------------------------------------------------------
class TestManualPdfFallback:
    """Tests for the manual PDF scan in _process_component."""

    @patch("revlo.datasheet.pipeline.extract_spec", new_callable=AsyncMock)
    @patch("revlo.datasheet.pipeline.extract_text")
    @patch("revlo.datasheet.pipeline.download_pdf", new_callable=AsyncMock)
    @patch("revlo.datasheet.pipeline.resolve_datasheet_url", new_callable=AsyncMock)
    @patch("revlo.datasheet.pipeline.normalize_part")
    @patch("revlo.datasheet.pipeline.DatasheetCache")
    def test_manual_pdf_bypasses_url_resolution(
        self,
        MockCache: MagicMock,
        mock_normalize: MagicMock,
        mock_resolve: AsyncMock,
        mock_download: AsyncMock,
        mock_extract_text: MagicMock,
        mock_extract_spec: AsyncMock,
        simple_schematic: ParsedSchematic,
        non_generic_part: NormalizedPartNumber,
        mock_spec: DatasheetSpec,
        tmp_path: Path,
    ) -> None:
        """When a manual PDF exists, URL resolution and download are skipped."""
        # Place a manual PDF in cache_dir
        pdf_file = tmp_path / "stm32f103c8t6-datasheet.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")

        mock_normalize.return_value = non_generic_part
        cache_instance = MockCache.return_value
        cache_instance.get.return_value = None  # No cache hit

        mock_extract_text.return_value = ("PDF text content from manual PDF", [1, 2])
        mock_extract_spec.return_value = mock_spec

        result = asyncio.run(enrich_schematic(simple_schematic, tmp_path))

        # URL resolution and download should NOT be called
        mock_resolve.assert_not_called()
        mock_download.assert_not_called()

        # But text extraction and spec extraction SHOULD be called
        mock_extract_text.assert_called_once_with(pdf_file)
        mock_extract_spec.assert_called_once()

        # Result should contain the spec
        assert "U1" in result
        assert result["U1"] == mock_spec

    @patch("revlo.datasheet.pipeline.extract_spec", new_callable=AsyncMock)
    @patch("revlo.datasheet.pipeline.extract_text")
    @patch("revlo.datasheet.pipeline.download_pdf", new_callable=AsyncMock)
    @patch("revlo.datasheet.pipeline.resolve_datasheet_url", new_callable=AsyncMock)
    @patch("revlo.datasheet.pipeline.normalize_part")
    @patch("revlo.datasheet.pipeline.DatasheetCache")
    def test_falls_back_to_url_when_no_manual_pdf(
        self,
        MockCache: MagicMock,
        mock_normalize: MagicMock,
        mock_resolve: AsyncMock,
        mock_download: AsyncMock,
        mock_extract_text: MagicMock,
        mock_extract_spec: AsyncMock,
        simple_schematic: ParsedSchematic,
        non_generic_part: NormalizedPartNumber,
        mock_spec: DatasheetSpec,
        tmp_path: Path,
    ) -> None:
        """Without a manual PDF, normal URL resolution path is used."""
        mock_normalize.return_value = non_generic_part
        cache_instance = MockCache.return_value
        cache_instance.get.return_value = None

        mock_resolve.return_value = "https://example.com/ds.pdf"
        mock_download.return_value = tmp_path / "ds.pdf"
        mock_extract_text.return_value = ("PDF text", [1])
        mock_extract_spec.return_value = mock_spec

        result = asyncio.run(enrich_schematic(simple_schematic, tmp_path))

        # URL resolution and download SHOULD be called
        mock_resolve.assert_called_once()
        mock_download.assert_called_once()
        assert "U1" in result

    @patch("revlo.datasheet.pipeline.extract_spec", new_callable=AsyncMock)
    @patch("revlo.datasheet.pipeline.extract_text")
    @patch("revlo.datasheet.pipeline.resolve_datasheet_url", new_callable=AsyncMock)
    @patch("revlo.datasheet.pipeline.normalize_part")
    @patch("revlo.datasheet.pipeline.DatasheetCache")
    def test_manual_pdf_cache_entry_has_empty_source_url(
        self,
        MockCache: MagicMock,
        mock_normalize: MagicMock,
        mock_resolve: AsyncMock,
        mock_extract_text: MagicMock,
        mock_extract_spec: AsyncMock,
        simple_schematic: ParsedSchematic,
        non_generic_part: NormalizedPartNumber,
        mock_spec: DatasheetSpec,
        tmp_path: Path,
    ) -> None:
        """Cache entry for manual PDF has empty source_url."""
        pdf_file = tmp_path / "stm32f103c8t6.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")

        mock_normalize.return_value = non_generic_part
        cache_instance = MockCache.return_value
        cache_instance.get.return_value = None

        mock_extract_text.return_value = ("PDF text", [1])
        mock_extract_spec.return_value = mock_spec

        asyncio.run(enrich_schematic(simple_schematic, tmp_path))

        # Verify cache.put was called with empty source_url
        cache_instance.put.assert_called_once()
        entry = cache_instance.put.call_args[0][1]
        assert entry.source_url == ""


# ---------------------------------------------------------------------------
# Status callback in enrich_schematic
# ---------------------------------------------------------------------------
class TestStatusCallback:
    """Tests for the status_callback parameter."""

    @patch("revlo.datasheet.pipeline.normalize_part")
    @patch("revlo.datasheet.pipeline.DatasheetCache")
    def test_status_cached_on_cache_hit(
        self,
        MockCache: MagicMock,
        mock_normalize: MagicMock,
        simple_schematic: ParsedSchematic,
        non_generic_part: NormalizedPartNumber,
        mock_spec: DatasheetSpec,
        tmp_path: Path,
    ) -> None:
        """status_callback receives 'cached' on cache hit."""
        mock_normalize.return_value = non_generic_part
        cache_instance = MockCache.return_value
        cache_instance.get.return_value = DatasheetCacheEntry(
            mpn="STM32F103C8T6", spec=mock_spec,
        )

        statuses: list[tuple[str, str, str]] = []

        def on_status(ref: str, mpn: str, source: str) -> None:
            statuses.append((ref, mpn, source))

        asyncio.run(
            enrich_schematic(
                simple_schematic, tmp_path, status_callback=on_status,
            )
        )

        assert ("U1", "STM32F103C8T6", "cached") in statuses

    @patch("revlo.datasheet.pipeline.extract_spec", new_callable=AsyncMock)
    @patch("revlo.datasheet.pipeline.extract_text")
    @patch("revlo.datasheet.pipeline.normalize_part")
    @patch("revlo.datasheet.pipeline.DatasheetCache")
    def test_status_manual_on_manual_pdf(
        self,
        MockCache: MagicMock,
        mock_normalize: MagicMock,
        mock_extract_text: MagicMock,
        mock_extract_spec: AsyncMock,
        simple_schematic: ParsedSchematic,
        non_generic_part: NormalizedPartNumber,
        mock_spec: DatasheetSpec,
        tmp_path: Path,
    ) -> None:
        """status_callback receives 'manual' when manual PDF is found."""
        pdf_file = tmp_path / "stm32f103c8t6.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")

        mock_normalize.return_value = non_generic_part
        cache_instance = MockCache.return_value
        cache_instance.get.return_value = None

        mock_extract_text.return_value = ("PDF text", [1])
        mock_extract_spec.return_value = mock_spec

        statuses: list[tuple[str, str, str]] = []

        def on_status(ref: str, mpn: str, source: str) -> None:
            statuses.append((ref, mpn, source))

        asyncio.run(
            enrich_schematic(
                simple_schematic, tmp_path, status_callback=on_status,
            )
        )

        assert ("U1", "STM32F103C8T6", "manual") in statuses

    @patch("revlo.datasheet.pipeline.extract_spec", new_callable=AsyncMock)
    @patch("revlo.datasheet.pipeline.extract_text")
    @patch("revlo.datasheet.pipeline.download_pdf", new_callable=AsyncMock)
    @patch("revlo.datasheet.pipeline.resolve_datasheet_url", new_callable=AsyncMock)
    @patch("revlo.datasheet.pipeline.normalize_part")
    @patch("revlo.datasheet.pipeline.DatasheetCache")
    def test_status_fetched_on_download(
        self,
        MockCache: MagicMock,
        mock_normalize: MagicMock,
        mock_resolve: AsyncMock,
        mock_download: AsyncMock,
        mock_extract_text: MagicMock,
        mock_extract_spec: AsyncMock,
        simple_schematic: ParsedSchematic,
        non_generic_part: NormalizedPartNumber,
        mock_spec: DatasheetSpec,
        tmp_path: Path,
    ) -> None:
        """status_callback receives 'fetched' after successful download."""
        mock_normalize.return_value = non_generic_part
        cache_instance = MockCache.return_value
        cache_instance.get.return_value = None

        mock_resolve.return_value = "https://example.com/ds.pdf"
        mock_download.return_value = tmp_path / "ds.pdf"
        mock_extract_text.return_value = ("PDF text", [1])
        mock_extract_spec.return_value = mock_spec

        statuses: list[tuple[str, str, str]] = []

        def on_status(ref: str, mpn: str, source: str) -> None:
            statuses.append((ref, mpn, source))

        asyncio.run(
            enrich_schematic(
                simple_schematic, tmp_path, status_callback=on_status,
            )
        )

        assert ("U1", "STM32F103C8T6", "fetched") in statuses

    @patch("revlo.datasheet.pipeline.resolve_datasheet_url", new_callable=AsyncMock)
    @patch("revlo.datasheet.pipeline.normalize_part")
    @patch("revlo.datasheet.pipeline.DatasheetCache")
    def test_status_failed_on_no_url(
        self,
        MockCache: MagicMock,
        mock_normalize: MagicMock,
        mock_resolve: AsyncMock,
        simple_schematic: ParsedSchematic,
        non_generic_part: NormalizedPartNumber,
        tmp_path: Path,
    ) -> None:
        """status_callback receives 'failed' when URL resolution fails."""
        mock_normalize.return_value = non_generic_part
        cache_instance = MockCache.return_value
        cache_instance.get.return_value = None

        mock_resolve.return_value = None

        statuses: list[tuple[str, str, str]] = []
        errors: list[tuple[str, str]] = []

        def on_status(ref: str, mpn: str, source: str) -> None:
            statuses.append((ref, mpn, source))

        def on_error(ref: str, msg: str) -> None:
            errors.append((ref, msg))

        asyncio.run(
            enrich_schematic(
                simple_schematic, tmp_path,
                error_callback=on_error,
                status_callback=on_status,
            )
        )

        assert ("U1", "STM32F103C8T6", "failed") in statuses
        # error_callback should still be called as well
        assert len(errors) == 1

    @patch("revlo.datasheet.pipeline.normalize_part")
    @patch("revlo.datasheet.pipeline.DatasheetCache")
    def test_no_status_callback_does_not_error(
        self,
        MockCache: MagicMock,
        mock_normalize: MagicMock,
        simple_schematic: ParsedSchematic,
        non_generic_part: NormalizedPartNumber,
        tmp_path: Path,
    ) -> None:
        """Omitting status_callback does not raise."""
        mock_normalize.return_value = non_generic_part
        cache_instance = MockCache.return_value
        cache_instance.get.return_value = DatasheetCacheEntry(
            mpn="STM32F103C8T6", spec=DatasheetSpec(mpn="STM32F103C8T6"),
        )

        # Should not raise without status_callback
        result = asyncio.run(enrich_schematic(simple_schematic, tmp_path))
        assert isinstance(result, dict)
