"""Test suite for the Textual TUI findings browser (US-027).

Uses Textual's ``run_test`` / ``Pilot`` helper for headless async testing.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from revlo.reviewer.models import (
    Finding,
    FindingCategory,
    ReviewReport,
    Severity,
)
from revlo.tui.app import (
    DEEP_NAVY,
    DetailPanel,
    FindingItem,
    FindingsSidebar,
    RevloApp,
    _SEVERITY_LABEL,
    _SEVERITY_ORDER,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_finding(
    severity: Severity = Severity.error,
    category: FindingCategory = FindingCategory.decoupling,
    ref: str = "U1",
    title: str = "Missing decoupling capacitor",
    description: str = "No decoupling capacitor found near U1.",
    recommendation: str = "Add a 100nF capacitor close to the power pins.",
    confidence: float = 0.95,
) -> Finding:
    return Finding(
        severity=severity,
        category=category,
        component_ref=ref,
        title=title,
        description=description,
        recommendation=recommendation,
        confidence=confidence,
    )


@pytest.fixture
def sample_report() -> ReviewReport:
    """Report with one finding per severity."""
    return ReviewReport(
        findings=[
            _make_finding(Severity.error, FindingCategory.decoupling, "U1", "Missing cap"),
            _make_finding(Severity.warning, FindingCategory.power, "R7", "High current path"),
            _make_finding(Severity.suggestion, FindingCategory.unused_pin, "U2", "Unused pin"),
        ],
        summary="3 findings",
        schematic_title="Test Schematic",
        review_date="2026-02-12",
    )


@pytest.fixture
def empty_report() -> ReviewReport:
    """Report with no findings."""
    return ReviewReport(
        findings=[],
        summary="No issues",
        schematic_title="Test Schematic",
        review_date="2026-02-12",
    )


@pytest.fixture
def errors_only_report() -> ReviewReport:
    """Report with only error findings."""
    return ReviewReport(
        findings=[
            _make_finding(Severity.error, FindingCategory.decoupling, "U1", "Error 1"),
            _make_finding(Severity.error, FindingCategory.power, "U2", "Error 2"),
        ],
        summary="2 errors",
        schematic_title="Test",
        review_date="2026-02-12",
    )


@pytest.fixture
def schematic_path(tmp_path: Path) -> str:
    """Return a temporary path simulating a schematic file."""
    p = tmp_path / "test_board.kicad_sch"
    p.write_text("")
    return str(p)


# ---------------------------------------------------------------------------
# Unit tests -- sorting / filtering helpers
# ---------------------------------------------------------------------------

class TestSortFindings:
    def test_sorts_by_severity(self, sample_report: ReviewReport):
        sorted_f = RevloApp._sort_findings(sample_report.findings)
        severities = [f.severity for f in sorted_f]
        assert severities == [Severity.error, Severity.warning, Severity.suggestion]

    def test_empty_list(self):
        assert RevloApp._sort_findings([]) == []

    def test_same_severity_preserves_order(self):
        f1 = _make_finding(Severity.error, ref="U1", title="First")
        f2 = _make_finding(Severity.error, ref="U2", title="Second")
        result = RevloApp._sort_findings([f2, f1])
        # Both are errors; order preserved
        assert result[0].component_ref == "U2"
        assert result[1].component_ref == "U1"


class TestFilteredFindings:
    def test_filter_all(self, sample_report: ReviewReport, schematic_path: str):
        app = RevloApp(sample_report, schematic_path)
        app.active_filter = "all"
        assert len(app._filtered_findings()) == 3

    def test_filter_errors(self, sample_report: ReviewReport, schematic_path: str):
        app = RevloApp(sample_report, schematic_path)
        app.active_filter = "errors"
        findings = app._filtered_findings()
        assert len(findings) == 1
        assert all(f.severity == Severity.error for f in findings)

    def test_filter_warnings(self, sample_report: ReviewReport, schematic_path: str):
        app = RevloApp(sample_report, schematic_path)
        app.active_filter = "warnings"
        findings = app._filtered_findings()
        assert len(findings) == 1
        assert all(f.severity == Severity.warning for f in findings)

    def test_filter_suggestions(self, sample_report: ReviewReport, schematic_path: str):
        app = RevloApp(sample_report, schematic_path)
        app.active_filter = "suggestions"
        findings = app._filtered_findings()
        assert len(findings) == 1
        assert all(f.severity == Severity.suggestion for f in findings)

    def test_filter_returns_empty_when_no_match(
        self, errors_only_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(errors_only_report, schematic_path)
        app.active_filter = "warnings"
        assert app._filtered_findings() == []


# ---------------------------------------------------------------------------
# Async TUI tests using Textual Pilot
# ---------------------------------------------------------------------------

class TestRevloAppCompose:
    """Test that the app composes the correct widget tree."""

    @pytest.mark.asyncio
    async def test_app_mounts_sidebar_and_detail(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test() as _pilot:
            sidebar = app.query_one("#sidebar", FindingsSidebar)
            assert sidebar is not None
            detail = app.query_one("#detail-panel", DetailPanel)
            assert detail is not None

    @pytest.mark.asyncio
    async def test_sidebar_has_correct_item_count(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test() as _pilot:
            sidebar = app.query_one("#sidebar", FindingsSidebar)
            items = sidebar.query(FindingItem)
            assert len(items) == 3

    @pytest.mark.asyncio
    async def test_empty_report_shows_empty_state(
        self, empty_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(empty_report, schematic_path)
        async with app.run_test() as _pilot:
            empty = app.query_one("#empty-state")
            text = empty.render().plain
            assert "No issues found" in text

    @pytest.mark.asyncio
    async def test_title_is_revlo_review(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test() as _pilot:
            assert app.title == "Revlo Review"


class TestKeyboardNavigation:
    """Test key bindings via the Pilot."""

    @pytest.mark.asyncio
    async def test_q_quits(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test() as pilot:
            await pilot.press("q")
            # After pressing q the app should have exited (run_test handles this)

    @pytest.mark.asyncio
    async def test_escape_quits(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test() as pilot:
            await pilot.press("escape")


class TestFilterKeys:
    """Test that filter key bindings update the sidebar."""

    @pytest.mark.asyncio
    async def test_e_filters_errors(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test() as pilot:
            await pilot.press("e")
            await pilot.pause()
            sidebar = app.query_one("#sidebar", FindingsSidebar)
            items = sidebar.query(FindingItem)
            assert len(items) == 1
            assert items[0].finding.severity == Severity.error

    @pytest.mark.asyncio
    async def test_w_filters_warnings(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test() as pilot:
            await pilot.press("w")
            await pilot.pause()
            sidebar = app.query_one("#sidebar", FindingsSidebar)
            items = sidebar.query(FindingItem)
            assert len(items) == 1
            assert items[0].finding.severity == Severity.warning

    @pytest.mark.asyncio
    async def test_s_filters_suggestions(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test() as pilot:
            await pilot.press("s")
            await pilot.pause()
            sidebar = app.query_one("#sidebar", FindingsSidebar)
            items = sidebar.query(FindingItem)
            assert len(items) == 1
            assert items[0].finding.severity == Severity.suggestion

    @pytest.mark.asyncio
    async def test_a_shows_all(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test() as pilot:
            # First filter down, then press 'a' to show all
            await pilot.press("e")
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            sidebar = app.query_one("#sidebar", FindingsSidebar)
            items = sidebar.query(FindingItem)
            assert len(items) == 3


class TestMarkdownExport:
    """Test the 'm' key exports a markdown report file."""

    @pytest.mark.asyncio
    async def test_m_exports_markdown(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test(notifications=True) as pilot:
            await pilot.press("m")
            await pilot.pause()

        # Check the file was written
        sch = Path(schematic_path)
        expected = sch.parent / f"{sch.stem}-review.md"
        assert expected.exists()
        content = expected.read_text()
        assert "Test Schematic" in content


class TestDetailPanel:
    """Test that selecting a finding populates the detail panel."""

    @pytest.mark.asyncio
    async def test_highlight_updates_detail(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test() as pilot:
            # The first item should be highlighted by default
            await pilot.pause()
            detail = app.query_one("#detail-content")
            text = detail.render().plain
            # First finding (error) should be shown since it auto-highlights
            assert "U1" in text or "Missing cap" in text or "ERROR" in text

    @pytest.mark.asyncio
    async def test_j_moves_cursor_down(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test() as pilot:
            await pilot.press("j")
            await pilot.pause()
            # After moving down, the detail panel should update
            detail = app.query_one("#detail-content")
            text = detail.render().plain
            # Should show one of the findings
            assert len(text) > 10  # Not the placeholder text

    @pytest.mark.asyncio
    async def test_k_moves_cursor_up(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test() as pilot:
            # Move down first, then back up
            await pilot.press("j")
            await pilot.pause()
            await pilot.press("k")
            await pilot.pause()
            detail = app.query_one("#detail-content")
            text = detail.render().plain
            assert len(text) > 10


class TestEnterKey:
    """Test the Enter key (datasheet URL open)."""

    @pytest.mark.asyncio
    async def test_enter_notifies_no_url(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test(notifications=True) as pilot:
            await pilot.press("enter")
            await pilot.pause()
            # The app should still be alive (no crash)


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------

class TestCLITuiIntegration:
    """Test that the CLI launches (or skips) the TUI correctly."""

    @patch("revlo.cli.parse_schematic")
    @patch("revlo.cli.review_schematic")
    @patch("revlo.cli.generate_markdown_report")
    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    def test_json_flag_skips_tui(
        self,
        mock_markdown: MagicMock,
        mock_review: AsyncMock,
        mock_parse: MagicMock,
        sample_report: ReviewReport,
        capsys,
    ):
        """--json should produce JSON output, not launch TUI."""
        from revlo.cli import _build_parser, _run_review
        from revlo.parser.models import ParsedSchematic, TitleBlockInfo

        fixture_path = str(
            Path(__file__).parent / "fixtures" / "STM32F103CBT8_Devel.kicad_sch"
        )
        mock_parse.return_value = ParsedSchematic(
            components=[], nets=[],
            title_block=TitleBlockInfo(title="T", date="", revision="", company=""),
        )

        with patch("revlo.cli.asyncio.run") as mock_asyncio_run:
            mock_asyncio_run.return_value = sample_report
            args = _build_parser().parse_args(
                ["review", fixture_path, "--json", "--skip-datasheet"]
            )
            _run_review(args)

        captured = capsys.readouterr()
        assert "findings" in captured.out

    @patch("revlo.cli.parse_schematic")
    @patch("revlo.cli.review_schematic")
    @patch("revlo.cli.generate_markdown_report")
    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    def test_output_flag_skips_tui(
        self,
        mock_markdown: MagicMock,
        mock_review: AsyncMock,
        mock_parse: MagicMock,
        sample_report: ReviewReport,
        tmp_path: Path,
    ):
        """--output should write file, not launch TUI."""
        from revlo.cli import _build_parser, _run_review
        from revlo.parser.models import ParsedSchematic, TitleBlockInfo

        fixture_path = str(
            Path(__file__).parent / "fixtures" / "STM32F103CBT8_Devel.kicad_sch"
        )
        mock_parse.return_value = ParsedSchematic(
            components=[], nets=[],
            title_block=TitleBlockInfo(title="T", date="", revision="", company=""),
        )
        mock_markdown.return_value = "# Report\n"

        out = tmp_path / "out.md"
        with patch("revlo.cli.asyncio.run") as mock_asyncio_run:
            mock_asyncio_run.return_value = sample_report
            args = _build_parser().parse_args(
                ["review", fixture_path, "--output", str(out), "--skip-datasheet"]
            )
            _run_review(args)

        assert out.exists()

    @patch("revlo.cli.parse_schematic")
    @patch("revlo.cli.review_schematic")
    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    def test_no_tui_flag_skips_tui(
        self,
        mock_review: AsyncMock,
        mock_parse: MagicMock,
        sample_report: ReviewReport,
        capsys,
    ):
        """--no-tui should show cards, not launch TUI."""
        from revlo.cli import _build_parser, _run_review
        from revlo.parser.models import ParsedSchematic, TitleBlockInfo

        fixture_path = str(
            Path(__file__).parent / "fixtures" / "STM32F103CBT8_Devel.kicad_sch"
        )
        mock_parse.return_value = ParsedSchematic(
            components=[], nets=[],
            title_block=TitleBlockInfo(title="T", date="", revision="", company=""),
        )

        with patch("revlo.cli.asyncio.run") as mock_asyncio_run:
            mock_asyncio_run.return_value = sample_report
            args = _build_parser().parse_args(
                ["review", fixture_path, "--no-tui", "--skip-datasheet"]
            )
            _run_review(args)

        captured = capsys.readouterr()
        # Finding cards on stderr, nothing on stdout
        assert captured.out == ""
        assert "ERROR" in captured.err or "U1" in captured.err

    @patch("revlo.cli.parse_schematic")
    @patch("revlo.cli.review_schematic")
    @patch("revlo.tui.RevloApp.run")
    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    def test_default_launches_tui(
        self,
        mock_tui_run: MagicMock,
        mock_review: AsyncMock,
        mock_parse: MagicMock,
        sample_report: ReviewReport,
    ):
        """Default mode (no flags) should launch the TUI."""
        from revlo.cli import _build_parser, _run_review
        from revlo.parser.models import ParsedSchematic, TitleBlockInfo

        fixture_path = str(
            Path(__file__).parent / "fixtures" / "STM32F103CBT8_Devel.kicad_sch"
        )
        mock_parse.return_value = ParsedSchematic(
            components=[], nets=[],
            title_block=TitleBlockInfo(title="T", date="", revision="", company=""),
        )

        with patch("revlo.cli.asyncio.run") as mock_asyncio_run:
            mock_asyncio_run.return_value = sample_report
            args = _build_parser().parse_args(
                ["review", fixture_path, "--skip-datasheet"]
            )
            _run_review(args)

        mock_tui_run.assert_called_once()


# ---------------------------------------------------------------------------
# Constants / configuration tests
# ---------------------------------------------------------------------------

class TestConstants:
    def test_severity_order(self):
        assert _SEVERITY_ORDER == [
            Severity.error, Severity.warning, Severity.suggestion
        ]

    def test_severity_labels(self):
        assert _SEVERITY_LABEL[Severity.error] == "ERROR"
        assert _SEVERITY_LABEL[Severity.warning] == "WARN"
        assert _SEVERITY_LABEL[Severity.suggestion] == "INFO"

    def test_brand_colors(self):
        assert DEEP_NAVY == "#0A1628"


class TestPackageExport:
    def test_revlo_tui_exports_revlo_app(self):
        from revlo.tui import RevloApp as RA
        assert RA is RevloApp
