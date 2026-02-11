"""Test suite for the CLI entry point (US-012).

All external calls (parse_schematic, review_schematic, API) are fully mocked.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from revlo.cli import _build_parser, _run_review, main
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
def fixture_path() -> str:
    """Return the path to the test fixture .kicad_sch file."""
    return str(
        Path(__file__).parent / "fixtures" / "STM32F103CBT8_Devel.kicad_sch"
    )


# ---------------------------------------------------------------------------
# Test _build_parser
# ---------------------------------------------------------------------------
def test_build_parser_creates_review_subcommand():
    """Test that _build_parser creates a review subcommand."""
    parser = _build_parser()
    args = parser.parse_args(["review", "test.kicad_sch"])
    assert args.command == "review"
    assert args.path == "test.kicad_sch"
    assert args.output is None
    assert args.json_output is False


def test_build_parser_with_output_flag():
    """Test --output flag."""
    parser = _build_parser()
    args = parser.parse_args(["review", "test.kicad_sch", "--output", "report.md"])
    assert args.output == "report.md"


def test_build_parser_with_json_flag():
    """Test --json flag."""
    parser = _build_parser()
    args = parser.parse_args(["review", "test.kicad_sch", "--json"])
    assert args.json_output is True


def test_build_parser_with_both_flags():
    """Test --output and --json together."""
    parser = _build_parser()
    args = parser.parse_args(
        ["review", "test.kicad_sch", "--output", "report.json", "--json"]
    )
    assert args.output == "report.json"
    assert args.json_output is True


# ---------------------------------------------------------------------------
# Test _run_review success path
# ---------------------------------------------------------------------------
@patch("revlo.cli.parse_schematic")
@patch("revlo.cli.review_schematic")
@patch("revlo.cli.generate_markdown_report")
@patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
def test_run_review_success_markdown(
    mock_markdown: MagicMock,
    mock_review: AsyncMock,
    mock_parse: MagicMock,
    mock_parsed_schematic: ParsedSchematic,
    mock_review_report: ReviewReport,
    fixture_path: str,
    capsys,
):
    """Test successful review with markdown output to stdout."""
    mock_parse.return_value = mock_parsed_schematic
    mock_review.return_value = mock_review_report
    mock_markdown.return_value = "# Test Report\n"

    # Mock asyncio.run since review_schematic is async
    with patch("revlo.cli.asyncio.run") as mock_asyncio_run:
        mock_asyncio_run.return_value = mock_review_report

        args = _build_parser().parse_args(["review", fixture_path, "--skip-datasheet"])
        _run_review(args)

    mock_parse.assert_called_once_with(fixture_path)
    mock_asyncio_run.assert_called_once()
    mock_markdown.assert_called_once_with(mock_review_report)

    captured = capsys.readouterr()
    assert "# Test Report\n" in captured.out


@patch("revlo.cli.parse_schematic")
@patch("revlo.cli.review_schematic")
@patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
def test_run_review_success_json(
    mock_review: AsyncMock,
    mock_parse: MagicMock,
    mock_parsed_schematic: ParsedSchematic,
    mock_review_report: ReviewReport,
    fixture_path: str,
    capsys,
):
    """Test successful review with JSON output to stdout."""
    mock_parse.return_value = mock_parsed_schematic
    mock_review.return_value = mock_review_report

    with patch("revlo.cli.asyncio.run") as mock_asyncio_run:
        mock_asyncio_run.return_value = mock_review_report

        args = _build_parser().parse_args(["review", fixture_path, "--json", "--skip-datasheet"])
        _run_review(args)

    mock_parse.assert_called_once_with(fixture_path)
    mock_asyncio_run.assert_called_once()

    captured = capsys.readouterr()
    # JSON output should contain the report data
    assert "findings" in captured.out
    assert "summary" in captured.out


@patch("revlo.cli.parse_schematic")
@patch("revlo.cli.review_schematic")
@patch("revlo.cli.generate_markdown_report")
@patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
def test_run_review_success_output_file(
    mock_markdown: MagicMock,
    mock_review: AsyncMock,
    mock_parse: MagicMock,
    mock_parsed_schematic: ParsedSchematic,
    mock_review_report: ReviewReport,
    fixture_path: str,
    tmp_path: Path,
    capsys,
):
    """Test successful review writing markdown to file."""
    mock_parse.return_value = mock_parsed_schematic
    mock_review.return_value = mock_review_report
    mock_markdown.return_value = "# Test Report\n"

    output_file = tmp_path / "report.md"

    with patch("revlo.cli.asyncio.run") as mock_asyncio_run:
        mock_asyncio_run.return_value = mock_review_report

        args = _build_parser().parse_args(
            ["review", fixture_path, "--output", str(output_file), "--skip-datasheet"]
        )
        _run_review(args)

    mock_parse.assert_called_once_with(fixture_path)
    mock_asyncio_run.assert_called_once()
    mock_markdown.assert_called_once_with(mock_review_report)

    # Verify file was written
    assert output_file.exists()
    assert output_file.read_text() == "# Test Report\n"

    # Verify nothing was printed to stdout
    captured = capsys.readouterr()
    assert captured.out == ""


@patch("revlo.cli.parse_schematic")
@patch("revlo.cli.review_schematic")
@patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
def test_run_review_success_json_to_file(
    mock_review: AsyncMock,
    mock_parse: MagicMock,
    mock_parsed_schematic: ParsedSchematic,
    mock_review_report: ReviewReport,
    fixture_path: str,
    tmp_path: Path,
):
    """Test successful review writing JSON to file."""
    mock_parse.return_value = mock_parsed_schematic
    mock_review.return_value = mock_review_report

    output_file = tmp_path / "report.json"

    with patch("revlo.cli.asyncio.run") as mock_asyncio_run:
        mock_asyncio_run.return_value = mock_review_report

        args = _build_parser().parse_args(
            ["review", fixture_path, "--output", str(output_file), "--json", "--skip-datasheet"]
        )
        _run_review(args)

    mock_parse.assert_called_once_with(fixture_path)
    mock_asyncio_run.assert_called_once()

    # Verify file was written with JSON content
    assert output_file.exists()
    content = output_file.read_text()
    assert "findings" in content
    assert "summary" in content


# ---------------------------------------------------------------------------
# Test _run_review error paths
# ---------------------------------------------------------------------------
def test_run_review_file_not_found():
    """Test error when input file does not exist."""
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
        args = _build_parser().parse_args(["review", "nonexistent.kicad_sch"])
        with pytest.raises(SystemExit) as exc:
            _run_review(args)
        assert exc.value.code == 1


def test_run_review_missing_api_key(fixture_path: str):
    """Test error when ANTHROPIC_API_KEY is not set."""
    with patch.dict(os.environ, {}, clear=True):
        args = _build_parser().parse_args(["review", fixture_path])
        with pytest.raises(SystemExit) as exc:
            _run_review(args)
        assert exc.value.code == 1


@patch("revlo.cli.parse_schematic")
@patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
def test_run_review_parse_error(mock_parse: MagicMock, fixture_path: str):
    """Test error when parse_schematic raises an exception."""
    mock_parse.side_effect = ValueError("Invalid schematic format")

    args = _build_parser().parse_args(["review", fixture_path])
    with pytest.raises(SystemExit) as exc:
        _run_review(args)
    assert exc.value.code == 1

    mock_parse.assert_called_once_with(fixture_path)


@patch("revlo.cli.parse_schematic")
@patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
def test_run_review_review_error(
    mock_parse: MagicMock,
    mock_parsed_schematic: ParsedSchematic,
    fixture_path: str,
):
    """Test error when review_schematic raises an exception."""
    mock_parse.return_value = mock_parsed_schematic

    with patch("revlo.cli.asyncio.run") as mock_asyncio_run:
        mock_asyncio_run.side_effect = RuntimeError("API call failed")

        args = _build_parser().parse_args(["review", fixture_path])
        with pytest.raises(SystemExit) as exc:
            _run_review(args)
        assert exc.value.code == 1

    mock_parse.assert_called_once_with(fixture_path)


@patch("revlo.cli.parse_schematic")
@patch("revlo.cli.review_schematic")
@patch("revlo.cli.generate_markdown_report")
@patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
def test_run_review_output_write_error(
    mock_markdown: MagicMock,
    mock_review: AsyncMock,
    mock_parse: MagicMock,
    mock_parsed_schematic: ParsedSchematic,
    mock_review_report: ReviewReport,
    fixture_path: str,
):
    """Test error when writing to output file fails."""
    mock_parse.return_value = mock_parsed_schematic
    mock_review.return_value = mock_review_report
    mock_markdown.return_value = "# Test Report\n"

    # Use a read-only directory path
    readonly_path = "/nonexistent/readonly/report.md"

    with patch("revlo.cli.asyncio.run") as mock_asyncio_run:
        mock_asyncio_run.return_value = mock_review_report

        args = _build_parser().parse_args(
            ["review", fixture_path, "--output", readonly_path]
        )
        with pytest.raises(SystemExit) as exc:
            _run_review(args)
        assert exc.value.code == 1


# ---------------------------------------------------------------------------
# Test main() entry point
# ---------------------------------------------------------------------------
@patch("revlo.cli._run_review")
@patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
def test_main_with_review_subcommand(mock_run_review: MagicMock, fixture_path: str):
    """Test main() calls _run_review when review subcommand is provided."""
    with patch("sys.argv", ["revlo", "review", fixture_path]):
        main()
    mock_run_review.assert_called_once()


def test_main_no_subcommand():
    """Test main() prints help and exits when no subcommand is provided."""
    with patch("sys.argv", ["revlo"]):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1


def test_main_help_flag(capsys):
    """Test main() prints help when --help is provided."""
    with patch("sys.argv", ["revlo", "review", "--help"]):
        with pytest.raises(SystemExit) as exc:
            main()
        # argparse exits with 0 for --help
        assert exc.value.code == 0

    captured = capsys.readouterr()
    assert "usage:" in captured.out.lower()
    assert "review" in captured.out.lower()


@patch("revlo.cli._run_review")
@patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
def test_main_logging_configured(mock_run_review: MagicMock, fixture_path: str):
    """Test that main() calls logging.basicConfig()."""
    with patch("revlo.cli.logging.basicConfig") as mock_logging:
        with patch("sys.argv", ["revlo", "review", fixture_path]):
            main()
        mock_logging.assert_called_once()


# ---------------------------------------------------------------------------
# Test __main__ module
# ---------------------------------------------------------------------------
def test_main_module_imports():
    """Test that __main__.py can be imported and calls main()."""
    # This verifies the __main__.py module structure without actually running it
    import importlib.util

    main_path = Path(__file__).parent.parent / "revlo" / "__main__.py"
    spec = importlib.util.spec_from_file_location("__main__", main_path)
    assert spec is not None
    assert spec.loader is not None

    # Read the file to verify it imports and calls main
    main_content = main_path.read_text()
    assert "from revlo.cli import main" in main_content
    assert "main()" in main_content
