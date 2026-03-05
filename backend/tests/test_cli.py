"""Test suite for the CLI entry point (US-012).

All external calls (parse_schematic, review_schematic, API) are fully mocked.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from revlo.cli import _build_parser, _run_check, _run_history, _run_open, _run_review, main
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
        Path(__file__).parent / "fixtures" / "simello.kicad_sch"
    )


@pytest.fixture
def mock_save_path() -> Path:
    """Return a fake save path relative to the fixtures directory."""
    return (
        Path(__file__).parent
        / "fixtures"
        / ".revlo"
        / "simello-review-20260212T000000.json"
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
    assert args.no_tui is False
    assert args.profile is None


def test_build_parser_creates_check_subcommand():
    """Test that _build_parser creates a check subcommand."""
    parser = _build_parser()
    args = parser.parse_args(["check", "test.kicad_sch"])
    assert args.command == "check"
    assert args.path == "test.kicad_sch"
    assert args.json_output is False
    assert args.min_confidence == 0.5
    assert args.profile is None


def test_build_parser_with_profile_flag():
    parser = _build_parser()
    args = parser.parse_args(["review", "test.kicad_sch", "--profile", "generic"])
    assert args.profile == "generic"


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


def test_build_parser_with_no_tui_flag():
    """Test --no-tui flag."""
    parser = _build_parser()
    args = parser.parse_args(["review", "test.kicad_sch", "--no-tui"])
    assert args.no_tui is True


def test_build_parser_creates_open_subcommand():
    """Test that _build_parser creates an open subcommand."""
    parser = _build_parser()
    args = parser.parse_args(["open", "test.kicad_sch"])
    assert args.command == "open"
    assert args.path == "test.kicad_sch"
    assert args.json_output is False
    assert args.no_tui is False


def test_build_parser_open_with_flags():
    """Test open subcommand with --json and --no-tui flags."""
    parser = _build_parser()
    args = parser.parse_args(["open", "test.kicad_sch", "--json", "--no-tui"])
    assert args.json_output is True
    assert args.no_tui is True


def test_run_check_forces_non_interactive_review(fixture_path: str):
    """The check command should route through _run_review with no_tui enabled."""
    args = _build_parser().parse_args(["check", fixture_path, "--skip-datasheet"])

    with patch("revlo.cli._run_review") as mock_run_review:
        _run_check(args)

    assert args.no_tui is True
    mock_run_review.assert_called_once_with(args)


# ---------------------------------------------------------------------------
# Test _run_review success path
# ---------------------------------------------------------------------------
@patch("revlo.parser.netlist.try_export_netlist", return_value=None)
@patch("revlo.storage.save_review", return_value=Path("/tmp/fake/.revlo/test.json"))
@patch("revlo.cli.parse_schematic")
@patch("revlo.cli.review_schematic")
@patch("revlo.cli.generate_markdown_report")
@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
def test_run_review_success_markdown(
    mock_markdown: MagicMock,
    mock_review: AsyncMock,
    mock_parse: MagicMock,
    mock_save: MagicMock,
    mock_netlist: MagicMock,
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

        args = _build_parser().parse_args(["review", fixture_path, "--skip-datasheet", "--no-tui"])
        _run_review(args)

    mock_parse.assert_called_once_with(fixture_path, netlist=None)
    mock_asyncio_run.assert_called_once()

    captured = capsys.readouterr()
    # --no-tui prints finding cards to stderr, no markdown to stdout
    assert "ERROR" in captured.err or "U1" in captured.err


@patch("revlo.parser.netlist.try_export_netlist", return_value=None)
@patch("revlo.storage.save_review", return_value=Path("/tmp/fake/.revlo/test.json"))
@patch("revlo.cli.parse_schematic")
@patch("revlo.cli.review_schematic")
@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
def test_run_review_success_json(
    mock_review: AsyncMock,
    mock_parse: MagicMock,
    mock_save: MagicMock,
    mock_netlist: MagicMock,
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

    mock_parse.assert_called_once_with(fixture_path, netlist=None)
    mock_asyncio_run.assert_called_once()

    captured = capsys.readouterr()
    # JSON output should contain the report data
    assert "findings" in captured.out
    assert "summary" in captured.out


@patch("revlo.parser.netlist.try_export_netlist", return_value=None)
@patch("revlo.storage.save_review", return_value=Path("/tmp/fake/.revlo/test.json"))
@patch("revlo.cli.parse_schematic")
@patch("revlo.cli.review_schematic")
@patch("revlo.cli.generate_markdown_report")
@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
def test_run_review_success_output_file(
    mock_markdown: MagicMock,
    mock_review: AsyncMock,
    mock_parse: MagicMock,
    mock_save: MagicMock,
    mock_netlist: MagicMock,
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

    mock_parse.assert_called_once_with(fixture_path, netlist=None)
    mock_asyncio_run.assert_called_once()
    mock_markdown.assert_called_once_with(mock_review_report)

    # Verify file was written
    assert output_file.exists()
    assert output_file.read_text() == "# Test Report\n"

    # Verify nothing was printed to stdout
    captured = capsys.readouterr()
    assert captured.out == ""


@patch("revlo.parser.netlist.try_export_netlist", return_value=None)
@patch("revlo.storage.save_review", return_value=Path("/tmp/fake/.revlo/test.json"))
@patch("revlo.cli.parse_schematic")
@patch("revlo.cli.review_schematic")
@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
def test_run_review_success_json_to_file(
    mock_review: AsyncMock,
    mock_parse: MagicMock,
    mock_save: MagicMock,
    mock_netlist: MagicMock,
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

    mock_parse.assert_called_once_with(fixture_path, netlist=None)
    mock_asyncio_run.assert_called_once()

    # Verify file was written with JSON content
    assert output_file.exists()
    content = output_file.read_text()
    assert "findings" in content
    assert "summary" in content


# ---------------------------------------------------------------------------
# Test Rich progress output (US-026)
# ---------------------------------------------------------------------------
@patch("revlo.storage.save_review", return_value=Path("/tmp/fake/.revlo/test.json"))
@patch("revlo.cli.parse_schematic")
@patch("revlo.cli.review_schematic")
@patch("revlo.cli.generate_markdown_report")
@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
def test_run_review_rich_progress_on_stderr(
    mock_markdown: MagicMock,
    mock_review: AsyncMock,
    mock_parse: MagicMock,
    mock_save: MagicMock,
    mock_parsed_schematic: ParsedSchematic,
    mock_review_report: ReviewReport,
    fixture_path: str,
    capsys,
):
    """Test that Rich branded progress appears on stderr."""
    mock_parse.return_value = mock_parsed_schematic
    mock_review.return_value = mock_review_report
    mock_markdown.return_value = "# Test Report\n"

    with patch("revlo.cli.asyncio.run") as mock_asyncio_run:
        mock_asyncio_run.return_value = mock_review_report

        args = _build_parser().parse_args(["review", fixture_path, "--skip-datasheet", "--no-tui"])
        _run_review(args)

    captured = capsys.readouterr()
    # Rich progress goes to stderr
    assert "AI-powered design review" in captured.err
    assert "Parsing schematic" in captured.err


@patch("revlo.storage.save_review", return_value=Path("/tmp/fake/.revlo/test.json"))
@patch("revlo.cli.parse_schematic")
@patch("revlo.cli.review_schematic")
@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
def test_run_review_json_suppresses_rich(
    mock_review: AsyncMock,
    mock_parse: MagicMock,
    mock_save: MagicMock,
    mock_parsed_schematic: ParsedSchematic,
    mock_review_report: ReviewReport,
    fixture_path: str,
    capsys,
):
    """Test that --json flag (to stdout) suppresses all Rich output."""
    mock_parse.return_value = mock_parsed_schematic
    mock_review.return_value = mock_review_report

    with patch("revlo.cli.asyncio.run") as mock_asyncio_run:
        mock_asyncio_run.return_value = mock_review_report

        args = _build_parser().parse_args(
            ["review", fixture_path, "--json", "--skip-datasheet"]
        )
        _run_review(args)

    captured = capsys.readouterr()
    # JSON goes to stdout
    assert "findings" in captured.out
    # NO rich output on stderr
    assert "AI-powered design review" not in captured.err
    assert "Parsing schematic" not in captured.err


@patch("revlo.storage.save_review", return_value=Path("/tmp/fake/.revlo/test.json"))
@patch("revlo.cli.parse_schematic")
@patch("revlo.cli.review_schematic")
@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
def test_run_review_no_tui_prints_cards(
    mock_review: AsyncMock,
    mock_parse: MagicMock,
    mock_save: MagicMock,
    mock_parsed_schematic: ParsedSchematic,
    mock_review_report: ReviewReport,
    fixture_path: str,
    capsys,
):
    """Test --no-tui prints finding cards on stderr and no markdown to stdout."""
    mock_parse.return_value = mock_parsed_schematic
    mock_review.return_value = mock_review_report

    with patch("revlo.cli.asyncio.run") as mock_asyncio_run:
        mock_asyncio_run.return_value = mock_review_report

        args = _build_parser().parse_args(
            ["review", fixture_path, "--no-tui", "--skip-datasheet"]
        )
        _run_review(args)

    captured = capsys.readouterr()
    # No markdown/json on stdout
    assert captured.out == ""
    # Finding cards on stderr
    assert "ERROR" in captured.err
    assert "U1" in captured.err
    assert "Missing decoupling capacitor" in captured.err
    # Summary on stderr
    assert "1 errors" in captured.err


@patch("revlo.storage.save_review", return_value=Path("/tmp/fake/.revlo/test.json"))
@patch("revlo.cli.parse_schematic")
@patch("revlo.cli.review_schematic")
@patch("revlo.cli.generate_markdown_report")
@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
def test_run_review_output_file_with_rich_progress(
    mock_markdown: MagicMock,
    mock_review: AsyncMock,
    mock_parse: MagicMock,
    mock_save: MagicMock,
    mock_parsed_schematic: ParsedSchematic,
    mock_review_report: ReviewReport,
    fixture_path: str,
    tmp_path: Path,
    capsys,
):
    """Test --output writes file and still shows Rich progress on stderr."""
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

    # File written
    assert output_file.exists()
    assert output_file.read_text() == "# Test Report\n"

    captured = capsys.readouterr()
    # Nothing on stdout
    assert captured.out == ""
    # Rich progress on stderr
    assert "AI-powered design review" in captured.err
    assert "Parsing schematic" in captured.err


@patch("revlo.storage.save_review", return_value=Path("/tmp/fake/.revlo/test.json"))
@patch("revlo.cli.parse_schematic")
@patch("revlo.cli.review_schematic")
@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
def test_run_review_summary_line_severity_counts(
    mock_review: AsyncMock,
    mock_parse: MagicMock,
    mock_save: MagicMock,
    fixture_path: str,
    capsys,
):
    """Test that summary line shows correct severity counts with colors."""
    report = ReviewReport(
        findings=[
            Finding(
                severity=Severity.error,
                category=FindingCategory.decoupling,
                component_ref="U1",
                title="Error 1",
                description="desc",
                recommendation="rec",
                confidence=0.9,
            ),
            Finding(
                severity=Severity.warning,
                category=FindingCategory.power,
                component_ref="R7",
                title="Warning 1",
                description="desc",
                recommendation="rec",
                confidence=0.8,
            ),
            Finding(
                severity=Severity.suggestion,
                category=FindingCategory.unused_pin,
                component_ref="U2",
                title="Suggestion 1",
                description="desc",
                recommendation="rec",
                confidence=0.7,
            ),
        ],
        summary="test",
        schematic_title="Test",
        review_date="2026-02-12",
    )
    mock_parse.return_value = ParsedSchematic(
        components=[],
        nets=[],
        title_block=TitleBlockInfo(
            title="Test", date="2026-02-12", revision="1.0", company="Test"
        ),
    )

    with patch("revlo.cli.asyncio.run") as mock_asyncio_run:
        mock_asyncio_run.return_value = report
        with patch("revlo.cli.generate_markdown_report", return_value="# Report\n"):
            args = _build_parser().parse_args(
                ["review", fixture_path, "--skip-datasheet", "--no-tui"]
            )
            _run_review(args)

    captured = capsys.readouterr()
    assert "1 errors" in captured.err
    assert "1 warnings" in captured.err
    assert "1 suggestions" in captured.err


# ---------------------------------------------------------------------------
# Test --json --no-tui priority fix
# ---------------------------------------------------------------------------
@patch("revlo.storage.save_review", return_value=Path("/tmp/fake/.revlo/test.json"))
@patch("revlo.cli.parse_schematic")
@patch("revlo.cli.review_schematic")
@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
def test_run_review_json_no_tui_produces_json(
    mock_review: AsyncMock,
    mock_parse: MagicMock,
    mock_save: MagicMock,
    mock_parsed_schematic: ParsedSchematic,
    mock_review_report: ReviewReport,
    fixture_path: str,
    capsys,
):
    """Test --json --no-tui produces JSON output (--json takes priority)."""
    mock_parse.return_value = mock_parsed_schematic
    mock_review.return_value = mock_review_report

    with patch("revlo.cli.asyncio.run") as mock_asyncio_run:
        mock_asyncio_run.return_value = mock_review_report

        args = _build_parser().parse_args(
            ["review", fixture_path, "--json", "--no-tui", "--skip-datasheet"]
        )
        _run_review(args)

    captured = capsys.readouterr()
    # JSON output on stdout
    data = json.loads(captured.out)
    assert "findings" in data
    assert "summary" in data


@patch("revlo.storage.save_review", return_value=Path("/tmp/fake/.revlo/test.json"))
@patch("revlo.cli.parse_schematic")
@patch("revlo.cli.review_schematic")
@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
def test_run_review_json_output_file_shows_rich(
    mock_review: AsyncMock,
    mock_parse: MagicMock,
    mock_save: MagicMock,
    mock_parsed_schematic: ParsedSchematic,
    mock_review_report: ReviewReport,
    fixture_path: str,
    tmp_path: Path,
    capsys,
):
    """Test --json --output writes JSON to file AND shows rich on stderr."""
    mock_parse.return_value = mock_parsed_schematic
    mock_review.return_value = mock_review_report

    output_file = tmp_path / "report.json"

    with patch("revlo.cli.asyncio.run") as mock_asyncio_run:
        mock_asyncio_run.return_value = mock_review_report

        args = _build_parser().parse_args(
            [
                "review", fixture_path,
                "--json", "--output", str(output_file),
                "--skip-datasheet",
            ]
        )
        _run_review(args)

    # JSON file written
    assert output_file.exists()
    data = json.loads(output_file.read_text())
    assert "findings" in data

    captured = capsys.readouterr()
    # Nothing on stdout (JSON went to file)
    assert captured.out == ""
    # Rich progress on stderr since JSON goes to file, not stdout
    assert "AI-powered design review" in captured.err
    assert "Parsing schematic" in captured.err


# ---------------------------------------------------------------------------
# Test auto-save
# ---------------------------------------------------------------------------
@patch("revlo.storage.save_review")
@patch("revlo.cli.parse_schematic")
@patch("revlo.cli.review_schematic")
@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
def test_run_review_auto_saves(
    mock_review: AsyncMock,
    mock_parse: MagicMock,
    mock_save: MagicMock,
    mock_parsed_schematic: ParsedSchematic,
    mock_review_report: ReviewReport,
    fixture_path: str,
):
    """Test that _run_review auto-saves the review to storage."""
    mock_parse.return_value = mock_parsed_schematic
    mock_save.return_value = Path("/tmp/fake/.revlo/test-review-20260212T000000.json")

    with patch("revlo.cli.asyncio.run") as mock_asyncio_run:
        mock_asyncio_run.return_value = mock_review_report

        args = _build_parser().parse_args(
            ["review", fixture_path, "--no-tui", "--skip-datasheet"]
        )
        _run_review(args)

    mock_save.assert_called_once_with(mock_review_report, fixture_path)
    assert mock_review_report.review_profile == "generic"


def test_run_review_invalid_profile_exits(fixture_path: str):
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        args = _build_parser().parse_args(
            ["review", fixture_path, "--profile", "sensor-node"]
        )
        with pytest.raises(SystemExit) as exc:
            _run_review(args)
        assert exc.value.code == 1


# ---------------------------------------------------------------------------
# Test ui.py helpers directly (US-026)
# ---------------------------------------------------------------------------
def test_ui_print_header(capsys):
    """Test print_header outputs the branded header."""
    from rich.console import Console

    from revlo.ui import print_header

    console = Console(stderr=True)
    print_header(console)

    captured = capsys.readouterr()
    assert "AI-powered design review" in captured.err


def test_ui_print_step(capsys):
    """Test print_step outputs a step line."""
    from rich.console import Console

    from revlo.ui import print_step

    console = Console(stderr=True)
    print_step(console, "Parsing schematic...")

    captured = capsys.readouterr()
    assert "Parsing schematic" in captured.err


def test_ui_print_summary(capsys):
    """Test print_summary outputs severity counts."""
    from rich.console import Console

    from revlo.ui import print_summary

    report = ReviewReport(
        findings=[
            Finding(
                severity=Severity.error,
                category=FindingCategory.decoupling,
                component_ref="U1",
                title="Error",
                description="d",
                recommendation="r",
                confidence=0.9,
            ),
        ],
        summary="test",
        schematic_title="Test",
        review_date="2026-02-12",
    )
    console = Console(stderr=True)
    print_summary(console, report)

    captured = capsys.readouterr()
    assert "1 errors" in captured.err
    assert "0 warnings" in captured.err
    assert "0 suggestions" in captured.err


def test_ui_print_finding_cards(capsys):
    """Test print_finding_cards outputs styled cards for each severity."""
    from rich.console import Console

    from revlo.ui import print_finding_cards

    report = ReviewReport(
        findings=[
            Finding(
                severity=Severity.error,
                category=FindingCategory.decoupling,
                component_ref="U1",
                title="Missing cap",
                description="No cap near U1.",
                recommendation="Add 100nF.",
                confidence=0.9,
            ),
            Finding(
                severity=Severity.warning,
                category=FindingCategory.power,
                component_ref="R7",
                title="High current",
                description="R7 rated too low.",
                recommendation="Use higher rated part.",
                confidence=0.8,
            ),
            Finding(
                severity=Severity.suggestion,
                category=FindingCategory.unused_pin,
                component_ref="U2",
                title="Unused pin",
                description="Pin 5 unconnected.",
                recommendation="Connect or mark NC.",
                confidence=0.7,
            ),
        ],
        summary="test",
        schematic_title="Test",
        review_date="2026-02-12",
    )
    console = Console(stderr=True)
    print_finding_cards(console, report)

    captured = capsys.readouterr()
    # Error card
    assert "ERROR" in captured.err
    assert "U1" in captured.err
    assert "Missing cap" in captured.err
    assert "No cap near U1" in captured.err
    assert "Add 100nF" in captured.err
    # Warning card
    assert "WARN" in captured.err
    assert "R7" in captured.err
    assert "High current" in captured.err
    # Suggestion card
    assert "INFO" in captured.err
    assert "U2" in captured.err
    assert "Unused pin" in captured.err


def test_ui_print_finding_cards_empty(capsys):
    """Test print_finding_cards with no findings produces no output."""
    from rich.console import Console

    from revlo.ui import print_finding_cards

    report = ReviewReport(
        findings=[],
        summary="No issues",
        schematic_title="Test",
        review_date="2026-02-12",
    )
    console = Console(stderr=True)
    print_finding_cards(console, report)

    captured = capsys.readouterr()
    assert captured.err.strip() == ""


# ---------------------------------------------------------------------------
# Test _run_review error paths
# ---------------------------------------------------------------------------
def test_run_review_file_not_found():
    """Test error when input file does not exist."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        args = _build_parser().parse_args(["review", "nonexistent.kicad_sch"])
        with pytest.raises(SystemExit) as exc:
            _run_review(args)
        assert exc.value.code == 1


def test_run_review_missing_api_key(fixture_path: str):
    """Test error when the configured provider key is not set."""
    with patch.dict(os.environ, {}, clear=True):
        args = _build_parser().parse_args(["review", fixture_path])
        with pytest.raises(SystemExit) as exc:
            _run_review(args)
        assert exc.value.code == 1


@patch("revlo.parser.netlist.try_export_netlist", return_value=None)
@patch("revlo.storage.save_review", return_value=Path("/tmp/fake/.revlo/test.json"))
@patch("revlo.cli.parse_schematic")
@patch("revlo.cli.review_schematic")
@patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=True)
def test_run_review_uses_provider_from_revlo_toml(
    mock_review: AsyncMock,
    mock_parse: MagicMock,
    mock_save: MagicMock,
    mock_netlist: MagicMock,
    mock_parsed_schematic: ParsedSchematic,
    mock_review_report: ReviewReport,
    fixture_path: str,
    tmp_path: Path,
    monkeypatch,
):
    """Test provider resolution through revlo.toml without a CLI provider flag."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "revlo.toml").write_text(
        "[llm]\nprovider = \"anthropic\"\nreview_model = \"claude-opus-4-6\"\n"
    )
    mock_parse.return_value = mock_parsed_schematic
    mock_review.return_value = mock_review_report

    with patch("revlo.cli.asyncio.run") as mock_asyncio_run:
        mock_asyncio_run.return_value = mock_review_report
        args = _build_parser().parse_args(["review", fixture_path, "--skip-datasheet", "--no-tui"])
        _run_review(args)

    assert mock_review.call_args.kwargs["provider"] == "anthropic"
    assert mock_review.call_args.kwargs["model"] == "claude-opus-4-6"


@patch("revlo.parser.netlist.try_export_netlist", return_value=None)
@patch("revlo.cli.parse_schematic")
@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
def test_run_review_parse_error(
    mock_parse: MagicMock,
    mock_netlist: MagicMock,
    fixture_path: str,
):
    """Test error when parse_schematic raises an exception."""
    mock_parse.side_effect = ValueError("Invalid schematic format")

    args = _build_parser().parse_args(["review", fixture_path])
    with pytest.raises(SystemExit) as exc:
        _run_review(args)
    assert exc.value.code == 1

    mock_parse.assert_called_once_with(fixture_path, netlist=None)


@patch("revlo.parser.netlist.try_export_netlist", return_value=None)
@patch("revlo.cli.parse_schematic")
@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
def test_run_review_review_error(
    mock_parse: MagicMock,
    mock_netlist: MagicMock,
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

    mock_parse.assert_called_once_with(fixture_path, netlist=None)


@patch("revlo.storage.save_review", return_value=Path("/tmp/fake/.revlo/test.json"))
@patch("revlo.cli.parse_schematic")
@patch("revlo.cli.review_schematic")
@patch("revlo.cli.generate_markdown_report")
@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
def test_run_review_output_write_error(
    mock_markdown: MagicMock,
    mock_review: AsyncMock,
    mock_parse: MagicMock,
    mock_save: MagicMock,
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
# Test _run_open
# ---------------------------------------------------------------------------
def test_run_open_file_not_found():
    """Test _run_open exits when schematic file does not exist."""
    args = _build_parser().parse_args(["open", "nonexistent.kicad_sch"])
    with pytest.raises(SystemExit) as exc:
        _run_open(args)
    assert exc.value.code == 1


@patch("revlo.storage.load_latest_review", return_value=None)
def test_run_open_no_review_found(
    mock_load: MagicMock,
    fixture_path: str,
    capsys,
):
    """Test _run_open exits when no review exists for the schematic."""
    args = _build_parser().parse_args(["open", fixture_path])
    with pytest.raises(SystemExit) as exc:
        _run_open(args)
    assert exc.value.code == 1

    captured = capsys.readouterr()
    assert "No review found" in captured.err


@patch("revlo.storage.load_latest_review")
def test_run_open_no_tui(
    mock_load: MagicMock,
    mock_review_report: ReviewReport,
    fixture_path: str,
    capsys,
):
    """Test _run_open with --no-tui prints finding cards."""
    mock_load.return_value = (
        mock_review_report,
        {"schematic": "test.kicad_sch", "saved_at": "2026-02-12T00:00:00+00:00"},
        Path(fixture_path).parent / ".revlo" / "test-review-20260212T000000.json",
    )

    args = _build_parser().parse_args(["open", fixture_path, "--no-tui"])
    _run_open(args)

    captured = capsys.readouterr()
    # Header and summary on stderr
    assert "AI-powered design review" in captured.err
    assert "Loaded review" in captured.err
    # Finding cards on stderr
    assert "ERROR" in captured.err
    assert "U1" in captured.err


@patch("revlo.storage.load_latest_review")
def test_run_open_json(
    mock_load: MagicMock,
    mock_review_report: ReviewReport,
    fixture_path: str,
    capsys,
):
    """Test _run_open with --json outputs JSON to stdout."""
    mock_load.return_value = (
        mock_review_report,
        {"schematic": "test.kicad_sch", "saved_at": "2026-02-12T00:00:00+00:00"},
        Path(fixture_path).parent / ".revlo" / "test-review-20260212T000000.json",
    )

    args = _build_parser().parse_args(["open", fixture_path, "--json"])
    _run_open(args)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "findings" in data
    assert "summary" in data


# ---------------------------------------------------------------------------
# Test main() entry point
# ---------------------------------------------------------------------------
@patch("revlo.cli._run_review")
@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
def test_main_with_review_subcommand(mock_run_review: MagicMock, fixture_path: str):
    """Test main() calls _run_review when review subcommand is provided."""
    with patch("sys.argv", ["revlo", "review", fixture_path]):
        main()
    mock_run_review.assert_called_once()


@patch("revlo.cli._run_open")
def test_main_with_open_subcommand(mock_run_open: MagicMock, fixture_path: str):
    """Test main() calls _run_open when open subcommand is provided."""
    with patch("sys.argv", ["revlo", "open", fixture_path]):
        main()
    mock_run_open.assert_called_once()


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
@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
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


# ---------------------------------------------------------------------------
# Test _build_parser: history subcommand
# ---------------------------------------------------------------------------
def test_build_parser_creates_history_subcommand():
    """Test that _build_parser creates a history subcommand."""
    parser = _build_parser()
    args = parser.parse_args(["history", "test.kicad_sch"])
    assert args.command == "history"
    assert args.path == "test.kicad_sch"
    assert args.load is None
    assert args.json_output is False
    assert args.no_tui is False


def test_build_parser_history_with_load_flag():
    """Test history --load N flag."""
    parser = _build_parser()
    args = parser.parse_args(["history", "test.kicad_sch", "--load", "3"])
    assert args.load == 3


def test_build_parser_history_with_all_flags():
    """Test history with --load, --json, --no-tui flags."""
    parser = _build_parser()
    args = parser.parse_args(
        ["history", "test.kicad_sch", "--load", "1", "--json", "--no-tui"]
    )
    assert args.load == 1
    assert args.json_output is True
    assert args.no_tui is True


# ---------------------------------------------------------------------------
# Test _run_history
# ---------------------------------------------------------------------------
def test_run_history_file_not_found():
    """Test _run_history exits when schematic file does not exist."""
    args = _build_parser().parse_args(["history", "nonexistent.kicad_sch"])
    with pytest.raises(SystemExit) as exc:
        _run_history(args)
    assert exc.value.code == 1


def test_run_history_no_entries(fixture_path: str, capsys):
    """Test _run_history shows 'No history found' when .revlo/ is empty."""
    with patch("revlo.storage.list_entries", return_value=[]):
        args = _build_parser().parse_args(["history", fixture_path])
        _run_history(args)

    captured = capsys.readouterr()
    assert "No history found" in captured.err


def test_run_history_lists_entries(fixture_path: str, capsys):
    """Test _run_history displays a table of entries."""
    from revlo.storage import HistoryEntry

    entries = [
        HistoryEntry(
            path=Path("/tmp/.revlo/board-review-20260212T120000.json"),
            entry_type="review",
            meta={"saved_at": "2026-02-12T12:00:00+00:00"},
            summary="2 errors, 1 warning",
        ),
        HistoryEntry(
            path=Path("/tmp/.revlo/board-chat-20260201T140000.json"),
            entry_type="chat",
            meta={"saved_at": "2026-02-01T14:00:00+00:00"},
            summary="5 messages",
        ),
    ]

    with patch("revlo.storage.list_entries", return_value=entries):
        args = _build_parser().parse_args(["history", fixture_path])
        _run_history(args)

    captured = capsys.readouterr()
    # Should show both entries with indices, types, dates, summaries
    assert "review" in captured.err
    assert "chat" in captured.err
    assert "2 errors, 1 warning" in captured.err
    assert "5 messages" in captured.err
    assert "2026-02-12" in captured.err
    assert "2026-02-01" in captured.err


def test_run_history_load_out_of_range(fixture_path: str, capsys):
    """Test --load N with N out of range shows error."""
    from revlo.storage import HistoryEntry

    entries = [
        HistoryEntry(
            path=Path("/tmp/.revlo/board-review-20260212T120000.json"),
            entry_type="review",
            meta={"saved_at": "2026-02-12T12:00:00+00:00"},
            summary="1 error",
        ),
    ]

    with patch("revlo.storage.list_entries", return_value=entries):
        args = _build_parser().parse_args(["history", fixture_path, "--load", "5"])
        with pytest.raises(SystemExit) as exc:
            _run_history(args)
        assert exc.value.code == 1

    captured = capsys.readouterr()
    assert "out of range" in captured.err


def test_run_history_load_zero(fixture_path: str, capsys):
    """Test --load 0 shows error (indices start at 1)."""
    from revlo.storage import HistoryEntry

    entries = [
        HistoryEntry(
            path=Path("/tmp/.revlo/board-review-20260212T120000.json"),
            entry_type="review",
            meta={"saved_at": "2026-02-12T12:00:00+00:00"},
            summary="1 error",
        ),
    ]

    with patch("revlo.storage.list_entries", return_value=entries):
        args = _build_parser().parse_args(["history", fixture_path, "--load", "0"])
        with pytest.raises(SystemExit) as exc:
            _run_history(args)
        assert exc.value.code == 1


def test_run_history_load_json(
    fixture_path: str, mock_review_report: ReviewReport, capsys
):
    """Test --load N --json outputs the entry as JSON."""
    from revlo.storage import HistoryEntry

    entry = HistoryEntry(
        path=Path("/tmp/.revlo/board-review-20260212T120000.json"),
        entry_type="review",
        meta={"saved_at": "2026-02-12T12:00:00+00:00"},
        summary="1 error",
    )

    with patch("revlo.storage.list_entries", return_value=[entry]):
        with patch(
            "revlo.storage.load_entry",
            return_value=(
                mock_review_report,
                {"saved_at": "2026-02-12T12:00:00+00:00", "schematic": "board.kicad_sch"},
                "review",
            ),
        ):
            args = _build_parser().parse_args(
                ["history", fixture_path, "--load", "1", "--json"]
            )
            _run_history(args)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "findings" in data
    assert "summary" in data


def test_run_history_load_no_tui_review(
    fixture_path: str, mock_review_report: ReviewReport, capsys
):
    """Test --load N --no-tui prints finding cards for a review entry."""
    from revlo.storage import HistoryEntry

    entry = HistoryEntry(
        path=Path("/tmp/.revlo/board-review-20260212T120000.json"),
        entry_type="review",
        meta={"saved_at": "2026-02-12T12:00:00+00:00"},
        summary="1 error",
    )

    with patch("revlo.storage.list_entries", return_value=[entry]):
        with patch(
            "revlo.storage.load_entry",
            return_value=(
                mock_review_report,
                {"saved_at": "2026-02-12T12:00:00+00:00", "schematic": "board.kicad_sch"},
                "review",
            ),
        ):
            args = _build_parser().parse_args(
                ["history", fixture_path, "--load", "1", "--no-tui"]
            )
            _run_history(args)

    captured = capsys.readouterr()
    assert "ERROR" in captured.err
    assert "U1" in captured.err
    assert "Missing decoupling capacitor" in captured.err


def test_run_history_load_no_tui_chat(fixture_path: str, capsys):
    """Test --load N --no-tui prints conversation for a chat entry."""
    from revlo.storage import HistoryEntry

    entry = HistoryEntry(
        path=Path("/tmp/.revlo/board-chat-20260201T140000.json"),
        entry_type="chat",
        meta={"saved_at": "2026-02-01T14:00:00+00:00"},
        summary="2 messages",
    )

    chat_data = {
        "messages": [
            {"role": "user", "content": "What about C1?"},
            {"role": "assistant", "content": "C1 looks fine."},
        ],
    }

    with patch("revlo.storage.list_entries", return_value=[entry]):
        with patch(
            "revlo.storage.load_entry",
            return_value=(
                chat_data,
                {"saved_at": "2026-02-01T14:00:00+00:00", "schematic": "board.kicad_sch"},
                "chat",
            ),
        ):
            args = _build_parser().parse_args(
                ["history", fixture_path, "--load", "1", "--no-tui"]
            )
            _run_history(args)

    captured = capsys.readouterr()
    assert "user" in captured.err
    assert "What about C1?" in captured.err
    assert "assistant" in captured.err
    assert "C1 looks fine." in captured.err


def test_run_history_load_chat_json(fixture_path: str, capsys):
    """Test --load N --json for a chat entry outputs raw JSON."""
    from revlo.storage import HistoryEntry

    entry = HistoryEntry(
        path=Path("/tmp/.revlo/board-chat-20260201T140000.json"),
        entry_type="chat",
        meta={"saved_at": "2026-02-01T14:00:00+00:00"},
        summary="2 messages",
    )

    chat_data = {
        "messages": [
            {"role": "user", "content": "Hello"},
        ],
    }

    with patch("revlo.storage.list_entries", return_value=[entry]):
        with patch(
            "revlo.storage.load_entry",
            return_value=(
                chat_data,
                {"saved_at": "2026-02-01T14:00:00+00:00", "schematic": "board.kicad_sch"},
                "chat",
            ),
        ):
            args = _build_parser().parse_args(
                ["history", fixture_path, "--load", "1", "--json"]
            )
            _run_history(args)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "messages" in data
    assert len(data["messages"]) == 1


# ---------------------------------------------------------------------------
# Test main() with history subcommand
# ---------------------------------------------------------------------------
@patch("revlo.cli._run_history")
def test_main_with_history_subcommand(mock_run_history: MagicMock, fixture_path: str):
    """Test main() calls _run_history when history subcommand is provided."""
    with patch("sys.argv", ["revlo", "history", fixture_path]):
        main()
    mock_run_history.assert_called_once()
