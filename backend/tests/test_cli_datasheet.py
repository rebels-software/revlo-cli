"""Test suite for CLI datasheet enrichment integration (US-021).

Tests the --skip-datasheet flag and enrichment pipeline integration in the CLI.
All external calls (parse_schematic, review_schematic, enrich_schematic, API) are fully mocked.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from revlo.cli import _build_parser, _run_review
from revlo.datasheet.models import DatasheetSpec
from revlo.parser.models import (
    ParsedComponent,
    ParsedSchematic,
    TitleBlockInfo,
)
from revlo.reviewer.models import (
    Finding,
    FindingCategory,
    ReviewReport,
    Severity,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_parsed_schematic() -> ParsedSchematic:
    """Return a minimal valid ParsedSchematic for testing."""
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
            )
        ],
        nets=[],
        title_block=TitleBlockInfo(
            title="Test Schematic",
            date="2026-02-11",
            revision="1.0",
            company="Test Company",
        ),
    )


@pytest.fixture
def mock_review_report() -> ReviewReport:
    """Return a minimal valid ReviewReport for testing."""
    return ReviewReport(
        findings=[
            Finding(
                severity=Severity.error,
                category=FindingCategory.decoupling,
                component_ref="U1",
                title="Missing decoupling capacitor",
                description="No decoupling capacitor found near U1.",
                recommendation="Add a 100nF capacitor close to the power pins.",
                confidence=0.95,
            )
        ],
        summary="Found 1 issues (1 errors, 0 warnings, 0 suggestions)",
        schematic_title="Test Schematic",
        review_date="2026-02-11",
    )


@pytest.fixture
def mock_datasheet_specs() -> dict[str, DatasheetSpec]:
    """Return sample datasheet specs for testing."""
    return {
        "U1": DatasheetSpec(
            mpn="STM32F103C8T6",
            manufacturer="STMicroelectronics",
            description="ARM Cortex-M3 MCU",
            supply_voltage_min=2.0,
            supply_voltage_max=3.6,
        )
    }


@pytest.fixture
def fixture_path() -> str:
    """Return the path to the test fixture .kicad_sch file."""
    return str(
        Path(__file__).parent / "fixtures" / "STM32F103CBT8_Devel.kicad_sch"
    )


# ---------------------------------------------------------------------------
# Test --skip-datasheet flag parsing
# ---------------------------------------------------------------------------
def test_skip_datasheet_flag_recognized():
    """Test that --skip-datasheet flag is recognized by argparse."""
    parser = _build_parser()
    args = parser.parse_args(["review", "test.kicad_sch", "--skip-datasheet"])
    assert args.command == "review"
    assert args.skip_datasheet is True


def test_skip_datasheet_flag_defaults_to_false():
    """Test that skip_datasheet defaults to False (enrichment enabled)."""
    parser = _build_parser()
    args = parser.parse_args(["review", "test.kicad_sch"])
    assert args.skip_datasheet is False


# ---------------------------------------------------------------------------
# Test enrichment pipeline integration
# ---------------------------------------------------------------------------
@patch("revlo.storage.save_review", return_value=Path("/tmp/fake/.revlo/test.json"))
@patch("revlo.cli.parse_schematic")
@patch("revlo.cli.review_schematic")
@patch("revlo.cli.generate_markdown_report")
@patch("revlo.cli.asyncio.run")
@patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
def test_enrichment_pipeline_called_by_default(
    mock_asyncio_run: MagicMock,
    mock_markdown: MagicMock,
    mock_review: AsyncMock,
    mock_parse: MagicMock,
    mock_save: MagicMock,
    mock_parsed_schematic: ParsedSchematic,
    mock_review_report: ReviewReport,
    mock_datasheet_specs: dict[str, DatasheetSpec],
    fixture_path: str,
    capsys,
):
    """Test that enrichment pipeline is called when --skip-datasheet is NOT set."""
    mock_parse.return_value = mock_parsed_schematic
    mock_markdown.return_value = "# Test Report\n"

    # Mock the enrichment pipeline at the import location
    with patch("revlo.datasheet.pipeline.enrich_schematic") as mock_enrich:
        # Mock asyncio.run to return the specs and then the report
        mock_asyncio_run.side_effect = [mock_datasheet_specs, mock_review_report]

        args = _build_parser().parse_args(["review", fixture_path, "--no-tui"])
        _run_review(args)

    # Verify enrichment was called with parsed schematic and cache_dir
    mock_enrich.assert_called_once()
    call_args = mock_enrich.call_args
    assert call_args[0][0] == mock_parsed_schematic
    # Cache dir should be Path(fixture_path).parent / "datasheets"
    cache_dir = call_args[0][1]
    assert isinstance(cache_dir, Path)
    assert cache_dir.name == "datasheets"
    # Verify status_callback is passed
    assert "status_callback" in call_args.kwargs
    assert callable(call_args.kwargs["status_callback"])

    # Verify review_schematic was called with datasheet_specs
    assert mock_asyncio_run.call_count == 2


@patch("revlo.storage.save_review", return_value=Path("/tmp/fake/.revlo/test.json"))
@patch("revlo.cli.parse_schematic")
@patch("revlo.cli.review_schematic")
@patch("revlo.cli.generate_markdown_report")
@patch("revlo.cli.asyncio.run")
@patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
def test_skip_datasheet_flag_skips_enrichment(
    mock_asyncio_run: MagicMock,
    mock_markdown: MagicMock,
    mock_review: AsyncMock,
    mock_parse: MagicMock,
    mock_save: MagicMock,
    mock_parsed_schematic: ParsedSchematic,
    mock_review_report: ReviewReport,
    fixture_path: str,
):
    """Test that --skip-datasheet flag prevents enrichment pipeline call."""
    mock_parse.return_value = mock_parsed_schematic
    mock_markdown.return_value = "# Test Report\n"
    mock_asyncio_run.return_value = mock_review_report

    with patch("revlo.datasheet.pipeline.enrich_schematic") as mock_enrich:
        args = _build_parser().parse_args(["review", fixture_path, "--skip-datasheet", "--no-tui"])
        _run_review(args)

    # Verify enrichment was NOT called
    mock_enrich.assert_not_called()

    # Verify review_schematic was still called (once via asyncio.run)
    mock_asyncio_run.assert_called_once()


@patch("revlo.storage.save_review", return_value=Path("/tmp/fake/.revlo/test.json"))
@patch("revlo.cli.parse_schematic")
@patch("revlo.cli.review_schematic")
@patch("revlo.cli.generate_markdown_report")
@patch("revlo.cli.asyncio.run")
@patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
def test_enrichment_failure_degrades_gracefully(
    mock_asyncio_run: MagicMock,
    mock_markdown: MagicMock,
    mock_review: AsyncMock,
    mock_parse: MagicMock,
    mock_save: MagicMock,
    mock_parsed_schematic: ParsedSchematic,
    mock_review_report: ReviewReport,
    fixture_path: str,
    caplog,
):
    """Test that enrichment failures are logged and review continues without specs."""
    mock_parse.return_value = mock_parsed_schematic
    mock_markdown.return_value = "# Test Report\n"

    with patch("revlo.datasheet.pipeline.enrich_schematic"):
        # Simulate enrichment failure via asyncio.run
        mock_asyncio_run.side_effect = [
            RuntimeError("API key invalid"),
            mock_review_report,
        ]

        args = _build_parser().parse_args(["review", fixture_path, "--no-tui"])
        _run_review(args)

    # Verify warning was logged
    assert "Datasheet enrichment failed" in caplog.text
    assert "continuing without specs" in caplog.text

    # Verify review_schematic was still called (second asyncio.run call)
    assert mock_asyncio_run.call_count == 2


@patch("revlo.storage.save_review", return_value=Path("/tmp/fake/.revlo/test.json"))
@patch("revlo.cli.parse_schematic")
@patch("revlo.cli.review_schematic")
@patch("revlo.cli.generate_markdown_report")
@patch("revlo.cli.asyncio.run")
@patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
def test_cache_dir_defaults_to_parent_datasheets(
    mock_asyncio_run: MagicMock,
    mock_markdown: MagicMock,
    mock_review: AsyncMock,
    mock_parse: MagicMock,
    mock_save: MagicMock,
    mock_parsed_schematic: ParsedSchematic,
    mock_review_report: ReviewReport,
    mock_datasheet_specs: dict[str, DatasheetSpec],
    tmp_path: Path,
):
    """Test that cache_dir defaults to Path(path).parent / 'datasheets'."""
    # Create a test file in tmp_path
    test_file = tmp_path / "test_schematic.kicad_sch"
    test_file.write_text("")

    mock_parse.return_value = mock_parsed_schematic
    mock_markdown.return_value = "# Test Report\n"

    with patch("revlo.datasheet.pipeline.enrich_schematic") as mock_enrich:
        mock_asyncio_run.side_effect = [mock_datasheet_specs, mock_review_report]

        args = _build_parser().parse_args(["review", str(test_file), "--no-tui"])
        _run_review(args)

    # Verify cache_dir is correct
    mock_enrich.assert_called_once()
    cache_dir = mock_enrich.call_args[0][1]
    assert cache_dir == tmp_path / "datasheets"


@patch("revlo.storage.save_review", return_value=Path("/tmp/fake/.revlo/test.json"))
@patch("revlo.cli.parse_schematic")
@patch("revlo.cli.generate_markdown_report")
@patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
def test_specs_passed_to_review_schematic_via_asyncio_run(
    mock_markdown: MagicMock,
    mock_parse: MagicMock,
    mock_save: MagicMock,
    mock_parsed_schematic: ParsedSchematic,
    mock_review_report: ReviewReport,
    mock_datasheet_specs: dict[str, DatasheetSpec],
    fixture_path: str,
):
    """Test that datasheet_specs are passed to review_schematic when enrichment succeeds."""
    mock_parse.return_value = mock_parsed_schematic
    mock_markdown.return_value = "# Test Report\n"

    review_schematic_kwargs = {}

    # Mock review_schematic to capture its arguments
    async def mock_review_schematic_impl(schematic, model=None, datasheet_specs=None, min_confidence=0.5):
        review_schematic_kwargs["schematic"] = schematic
        review_schematic_kwargs["model"] = model
        review_schematic_kwargs["datasheet_specs"] = datasheet_specs
        review_schematic_kwargs["min_confidence"] = min_confidence
        return mock_review_report

    with (
        patch("revlo.datasheet.pipeline.enrich_schematic", new_callable=AsyncMock) as mock_enrich,
        patch("revlo.cli.review_schematic", side_effect=mock_review_schematic_impl),
        patch("revlo.cli.asyncio.run") as mock_asyncio_run,
    ):
        # Configure mock_enrich to return the specs
        mock_enrich.return_value = mock_datasheet_specs

        # Make asyncio.run actually execute the coroutine
        def run_impl(coro):
            import asyncio
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

        mock_asyncio_run.side_effect = run_impl

        args = _build_parser().parse_args(["review", fixture_path, "--no-tui"])
        _run_review(args)

    # Verify datasheet_specs were passed to review_schematic
    assert "datasheet_specs" in review_schematic_kwargs
    assert review_schematic_kwargs["datasheet_specs"] == mock_datasheet_specs
