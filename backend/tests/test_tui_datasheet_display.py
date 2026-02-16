"""Test suite for TUI datasheet reference display functionality.

Tests the integration of datasheet information into the TUI detail panel,
including PDF path display, page number formatting, and the Enter key action
to open datasheets.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from revlo.datasheet.models import DatasheetSpec
from revlo.reviewer.models import (
    Finding,
    FindingCategory,
    ReviewReport,
    Severity,
)
from revlo.tui.app import DetailPanel, FindingItem, FindingsSidebar, RevloApp


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
def datasheet_spec_with_pdf(tmp_path: Path) -> DatasheetSpec:
    """DatasheetSpec with a PDF path and relevant pages."""
    pdf = tmp_path / "datasheets" / "ti.com" / "TPS54340.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4\nfake pdf")

    return DatasheetSpec(
        mpn="TPS54340DDAR",
        manufacturer="Texas Instruments",
        datasheet_url="https://www.ti.com/lit/ds/symlink/tps54340.pdf",
        pdf_path=str(pdf),
        relevant_pages=[3, 12, 15, 16, 17, 18],
    )


@pytest.fixture
def report_with_datasheet_specs(
    datasheet_spec_with_pdf: DatasheetSpec,
) -> ReviewReport:
    """ReviewReport with datasheet_specs populated."""
    return ReviewReport(
        findings=[
            _make_finding(Severity.error, FindingCategory.power, "U3", "Missing capacitor"),
        ],
        summary="1 finding",
        schematic_title="Test Schematic",
        review_date="2026-02-16",
        datasheet_specs={"U3": datasheet_spec_with_pdf},
    )


@pytest.fixture
def schematic_path(tmp_path: Path) -> str:
    """Return a temporary path simulating a schematic file."""
    p = tmp_path / "test_board.kicad_sch"
    p.write_text("")
    return str(p)


# ---------------------------------------------------------------------------
# Tests for _format_pages() helper
# ---------------------------------------------------------------------------


class TestFormatPages:
    """Test the _format_pages static method on DetailPanel."""

    def test_empty_list_returns_empty_string(self):
        result = DetailPanel._format_pages([])
        assert result == ""

    def test_single_page(self):
        result = DetailPanel._format_pages([5])
        assert result == "p.5"

    def test_consecutive_pages_collapsed_to_range(self):
        result = DetailPanel._format_pages([3, 4, 5, 6])
        assert result == "p.3-6"

    def test_mixed_individual_and_ranges(self):
        result = DetailPanel._format_pages([3, 12, 15, 16, 17, 18])
        assert result == "p.3, 12, 15-18"

    def test_unsorted_input_gets_sorted(self):
        result = DetailPanel._format_pages([18, 3, 16, 15, 12, 17])
        assert result == "p.3, 12, 15-18"

    def test_single_gap_produces_two_ranges(self):
        result = DetailPanel._format_pages([1, 2, 5, 6])
        assert result == "p.1-2, 5-6"

    def test_all_consecutive_produces_single_range(self):
        result = DetailPanel._format_pages([10, 11, 12, 13, 14])
        assert result == "p.10-14"


# ---------------------------------------------------------------------------
# Tests for DetailPanel showing datasheet information
# ---------------------------------------------------------------------------


class TestDetailPanelDatasheetDisplay:
    """Test that DetailPanel displays datasheet info when available."""

    @pytest.mark.asyncio
    async def test_show_finding_with_datasheet_spec_displays_pdf_name(
        self, datasheet_spec_with_pdf: DatasheetSpec
    ):
        """DetailPanel should show the PDF filename when spec has pdf_path."""
        report = ReviewReport(
            findings=[_make_finding(ref="U3", title="Power issue")],
            summary="1 finding",
            schematic_title="Test",
            review_date="2026-02-16",
            datasheet_specs={"U3": datasheet_spec_with_pdf},
        )
        app = RevloApp(report, "/tmp/test.kicad_sch")

        async with app.run_test() as pilot:
            await pilot.pause()
            panel = app.query_one("#detail-panel", DetailPanel)
            content = panel.query_one("#detail-content")
            text = content.render().plain
            assert "TPS54340.pdf" in text

    @pytest.mark.asyncio
    async def test_show_finding_with_datasheet_spec_displays_pages(
        self, datasheet_spec_with_pdf: DatasheetSpec
    ):
        """DetailPanel should show formatted page numbers when spec has relevant_pages."""
        report = ReviewReport(
            findings=[_make_finding(ref="U3", title="Power issue")],
            summary="1 finding",
            schematic_title="Test",
            review_date="2026-02-16",
            datasheet_specs={"U3": datasheet_spec_with_pdf},
        )
        app = RevloApp(report, "/tmp/test.kicad_sch")

        async with app.run_test() as pilot:
            await pilot.pause()
            panel = app.query_one("#detail-panel", DetailPanel)
            content = panel.query_one("#detail-content")
            text = content.render().plain
            assert "p.3, 12, 15-18" in text

    @pytest.mark.asyncio
    async def test_show_finding_without_datasheet_spec_no_pdf_shown(self):
        """DetailPanel should not show datasheet section when spec is missing."""
        report = ReviewReport(
            findings=[_make_finding(ref="U3", title="Power issue")],
            summary="1 finding",
            schematic_title="Test",
            review_date="2026-02-16",
            datasheet_specs={},
        )
        app = RevloApp(report, "/tmp/test.kicad_sch")

        async with app.run_test() as pilot:
            await pilot.pause()
            panel = app.query_one("#detail-panel", DetailPanel)
            content = panel.query_one("#detail-content")
            text = content.render().plain
            assert "Datasheet:" not in text
            assert "Pages:" not in text

    @pytest.mark.asyncio
    async def test_show_finding_with_spec_but_no_pdf_path(self):
        """DetailPanel should not show datasheet when spec.pdf_path is None."""
        spec = DatasheetSpec(
            mpn="TPS54340DDAR",
            manufacturer="Texas Instruments",
            datasheet_url="https://www.ti.com/lit/ds/symlink/tps54340.pdf",
        )
        report = ReviewReport(
            findings=[_make_finding(ref="U3", title="Power issue")],
            summary="1 finding",
            schematic_title="Test",
            review_date="2026-02-16",
            datasheet_specs={"U3": spec},
        )
        app = RevloApp(report, "/tmp/test.kicad_sch")

        async with app.run_test() as pilot:
            await pilot.pause()
            panel = app.query_one("#detail-panel", DetailPanel)
            content = panel.query_one("#detail-content")
            text = content.render().plain
            assert "Datasheet:" not in text


# ---------------------------------------------------------------------------
# Tests for action_open_datasheet
# ---------------------------------------------------------------------------


class TestOpenDatasheetAction:
    """Test the Enter key action to open datasheets."""

    def test_action_open_datasheet_with_available_pdf(
        self, report_with_datasheet_specs: ReviewReport, schematic_path: str
    ):
        """action_open_datasheet should call _open_file when PDF exists."""
        # Create a mock sidebar with a highlighted FindingItem
        app = RevloApp(report_with_datasheet_specs, schematic_path)
        finding = report_with_datasheet_specs.findings[0]
        finding_item = FindingItem(finding, 0)

        with patch("revlo.tui.app._open_file") as mock_open:
            # Mock query_one to return our mock sidebar with highlighted item
            with patch.object(app, "query_one") as mock_query:
                mock_sidebar = MagicMock()
                mock_sidebar.highlighted_child = finding_item
                mock_query.return_value = mock_sidebar

                # Call the action
                app.action_open_datasheet()

                # Should have opened the PDF file path directly
                mock_open.assert_called_once()
                call_args = mock_open.call_args[0][0]
                assert "TPS54340.pdf" in call_args

    def test_action_open_datasheet_without_spec_does_nothing(
        self, schematic_path: str
    ):
        """action_open_datasheet should not call _open_file when no spec."""
        report = ReviewReport(
            findings=[_make_finding(ref="U1", title="Issue")],
            summary="1 finding",
            schematic_title="Test",
            review_date="2026-02-16",
            datasheet_specs={},  # No specs
        )
        app = RevloApp(report, schematic_path)
        finding_item = FindingItem(report.findings[0], 0)

        with patch("revlo.tui.app._open_file") as mock_open:
            with patch.object(app, "query_one") as mock_query:
                mock_sidebar = MagicMock()
                mock_sidebar.highlighted_child = finding_item
                mock_query.return_value = mock_sidebar

                # Call the action
                app.action_open_datasheet()

                # Should not have opened anything
                mock_open.assert_not_called()

    def test_action_open_datasheet_with_nonexistent_pdf_does_nothing(
        self, schematic_path: str
    ):
        """action_open_datasheet should not call _open_file when PDF doesn't exist."""
        spec = DatasheetSpec(
            mpn="TEST123",
            manufacturer="Test",
            datasheet_url="https://example.com/test.pdf",
            pdf_path="/nonexistent/path/test.pdf",  # File doesn't exist
        )
        report = ReviewReport(
            findings=[_make_finding(ref="U1", title="Issue")],
            summary="1 finding",
            schematic_title="Test",
            review_date="2026-02-16",
            datasheet_specs={"U1": spec},
        )
        app = RevloApp(report, schematic_path)
        finding_item = FindingItem(report.findings[0], 0)

        with patch("revlo.tui.app._open_file") as mock_open:
            with patch.object(app, "query_one") as mock_query:
                mock_sidebar = MagicMock()
                mock_sidebar.highlighted_child = finding_item
                mock_query.return_value = mock_sidebar

                # Call the action
                app.action_open_datasheet()

                # Should not have opened anything
                mock_open.assert_not_called()


# ---------------------------------------------------------------------------
# Tests for ReviewReport serialization with datasheet_specs
# ---------------------------------------------------------------------------


class TestReviewReportSerialization:
    """Test that ReviewReport correctly serializes datasheet_specs."""

    def test_model_dump_includes_datasheet_specs(
        self, datasheet_spec_with_pdf: DatasheetSpec
    ):
        """ReviewReport.model_dump() should include datasheet_specs."""
        report = ReviewReport(
            findings=[],
            summary="",
            schematic_title="Test",
            review_date="2026-02-16",
            datasheet_specs={"U3": datasheet_spec_with_pdf},
        )

        dumped = report.model_dump()

        assert "datasheet_specs" in dumped
        assert "U3" in dumped["datasheet_specs"]
        assert dumped["datasheet_specs"]["U3"]["mpn"] == "TPS54340DDAR"

    def test_model_dump_json_round_trip(
        self, datasheet_spec_with_pdf: DatasheetSpec
    ):
        """ReviewReport should round-trip through JSON with datasheet_specs."""
        original = ReviewReport(
            findings=[],
            summary="Test",
            schematic_title="Board",
            review_date="2026-02-16",
            datasheet_specs={"U3": datasheet_spec_with_pdf},
        )

        json_str = original.model_dump_json()
        restored = ReviewReport.model_validate_json(json_str)

        assert restored.datasheet_specs == original.datasheet_specs
        assert restored.datasheet_specs["U3"].mpn == "TPS54340DDAR"
        assert restored.datasheet_specs["U3"].pdf_path == datasheet_spec_with_pdf.pdf_path

    def test_default_datasheet_specs_is_empty_dict(self):
        """ReviewReport should default to empty dict for backward compatibility."""
        report = ReviewReport(
            findings=[],
            summary="",
            schematic_title="Test",
            review_date="2026-02-16",
        )

        assert report.datasheet_specs == {}
        assert isinstance(report.datasheet_specs, dict)
