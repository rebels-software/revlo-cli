"""Textual TUI application for browsing review findings."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Label, ListItem, ListView, Static

from revlo.report.markdown import generate_markdown_report
from revlo.reviewer.models import Finding, ReviewReport, Severity

# ---------------------------------------------------------------------------
# Brand colours
# ---------------------------------------------------------------------------
DEEP_NAVY = "#0A1628"
MIDNIGHT_BLUE = "#1E3A5F"
ELECTRIC_TEAL = "#00D4AA"
SIGNAL_RED = "#FF4757"
WARM_AMBER = "#FFB347"

_SEVERITY_ORDER = [Severity.error, Severity.warning, Severity.suggestion]
_SEVERITY_LABEL: dict[Severity, str] = {
    Severity.error: "ERROR",
    Severity.warning: "WARN",
    Severity.suggestion: "INFO",
}
_SEVERITY_ICON: dict[Severity, str] = {
    Severity.error: "\u2717",
    Severity.warning: "\u25B2",
    Severity.suggestion: "\u25C6",
}


# ---------------------------------------------------------------------------
# Custom widgets
# ---------------------------------------------------------------------------


class FindingItem(ListItem):
    """A list item representing a single finding."""

    def __init__(self, finding: Finding, index: int) -> None:
        super().__init__()
        self.finding = finding
        self.finding_index = index

    def compose(self) -> ComposeResult:
        sev = self.finding.severity
        icon = _SEVERITY_ICON[sev]
        label = _SEVERITY_LABEL[sev]
        ref = self.finding.component_ref
        title = self.finding.title
        css_class = f"severity-{sev.value}"
        yield Label(
            f"{icon} [{label}] {ref}: {title}",
            classes=f"finding-label {css_class}",
        )


class FindingsSidebar(ListView):
    """Sidebar listing findings grouped by severity."""

    def __init__(
        self,
        findings: list[Finding],
        *,
        id: str | None = None,  # noqa: A002
    ) -> None:
        self._all_findings = findings
        super().__init__(id=id)

    def compose(self) -> ComposeResult:
        for idx, finding in enumerate(self._all_findings):
            yield FindingItem(finding, idx)

    def rebuild(self, findings: list[Finding]) -> None:
        """Clear and repopulate the list with *findings*."""
        self._all_findings = findings
        self.clear()
        for idx, finding in enumerate(findings):
            item = FindingItem(finding, idx)
            self.append(item)


class DetailPanel(Vertical):
    """Right-hand panel showing full details of the selected finding."""

    def compose(self) -> ComposeResult:
        yield Static("Select a finding to view details.", id="detail-content")

    def show_finding(self, finding: Finding) -> None:
        """Render *finding* details into the panel."""
        sev = finding.severity
        icon = _SEVERITY_ICON[sev]
        label = _SEVERITY_LABEL[sev]

        lines = [
            f"{icon} {label}  {finding.title}",
            "",
            f"Component:  {finding.component_ref}",
            f"Category:   {finding.category.value}",
            f"Confidence: {finding.confidence:.0%}",
            "",
            "Description",
            "-" * 40,
            finding.description,
            "",
            "Recommendation",
            "-" * 40,
            finding.recommendation,
        ]
        content = self.query_one("#detail-content", Static)
        content.update("\n".join(lines))

    def show_empty(self) -> None:
        """Show the empty-state message."""
        content = self.query_one("#detail-content", Static)
        content.update("\u2713 No issues found! Your schematic looks good.")


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------


class RevloApp(App[None]):
    """Interactive TUI findings browser for Revlo."""

    CSS_PATH = "revlo.tcss"
    TITLE = "Revlo Review"

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("escape", "quit", "Quit", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("e", "filter_errors", "Errors", show=True),
        Binding("w", "filter_warnings", "Warnings", show=True),
        Binding("s", "filter_suggestions", "Suggestions", show=True),
        Binding("a", "filter_all", "All", show=True),
        Binding("m", "export_markdown", "Export MD", show=True),
        Binding("enter", "open_datasheet", "Open URL", show=True),
    ]

    active_filter: reactive[str] = reactive("all")

    def __init__(
        self,
        report: ReviewReport,
        schematic_path: str,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.report = report
        self.schematic_path = schematic_path
        self._sorted_findings = self._sort_findings(report.findings)

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _sort_findings(findings: list[Finding]) -> list[Finding]:
        """Return findings sorted by severity (errors first)."""
        order = {Severity.error: 0, Severity.warning: 1, Severity.suggestion: 2}
        return sorted(findings, key=lambda f: order.get(f.severity, 99))

    def _filtered_findings(self) -> list[Finding]:
        """Return findings matching the active filter."""
        filt = self.active_filter
        if filt == "all":
            return list(self._sorted_findings)
        sev_map = {
            "errors": Severity.error,
            "warnings": Severity.warning,
            "suggestions": Severity.suggestion,
        }
        target = sev_map.get(filt)
        if target is None:
            return list(self._sorted_findings)
        return [f for f in self._sorted_findings if f.severity == target]

    # -- compose -------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Footer()
        if not self.report.findings:
            yield Static(
                "\u2713 No issues found! Your schematic looks good.",
                id="empty-state",
            )
        else:
            with Horizontal(id="main-container"):
                yield FindingsSidebar(
                    self._filtered_findings(),
                    id="sidebar",
                )
                yield DetailPanel(id="detail-panel")

    # -- watchers / events ---------------------------------------------------

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """When a finding is selected in the sidebar, show its details."""
        item = event.item
        if isinstance(item, FindingItem):
            panel = self.query_one("#detail-panel", DetailPanel)
            panel.show_finding(item.finding)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Update detail panel on highlight change (cursor movement)."""
        item = event.item
        if isinstance(item, FindingItem):
            try:
                panel = self.query_one("#detail-panel", DetailPanel)
                panel.show_finding(item.finding)
            except Exception:
                pass

    # -- filter actions ------------------------------------------------------

    def _apply_filter(self, filter_name: str) -> None:
        self.active_filter = filter_name
        try:
            sidebar = self.query_one("#sidebar", FindingsSidebar)
        except Exception:
            return
        sidebar.rebuild(self._filtered_findings())

    def action_filter_errors(self) -> None:
        self._apply_filter("errors")

    def action_filter_warnings(self) -> None:
        self._apply_filter("warnings")

    def action_filter_suggestions(self) -> None:
        self._apply_filter("suggestions")

    def action_filter_all(self) -> None:
        self._apply_filter("all")

    # -- navigation ----------------------------------------------------------

    def action_cursor_down(self) -> None:
        try:
            sidebar = self.query_one("#sidebar", FindingsSidebar)
            sidebar.action_cursor_down()
        except Exception:
            pass

    def action_cursor_up(self) -> None:
        try:
            sidebar = self.query_one("#sidebar", FindingsSidebar)
            sidebar.action_cursor_up()
        except Exception:
            pass

    # -- export / open -------------------------------------------------------

    def action_export_markdown(self) -> None:
        """Export the markdown report to ``{schematic_name}-review.md``."""
        stem = Path(self.schematic_path).stem
        out_path = Path(self.schematic_path).parent / f"{stem}-review.md"
        md = generate_markdown_report(self.report)
        out_path.write_text(md)
        self.notify(f"Exported to {out_path.name}")

    def action_open_datasheet(self) -> None:
        """Open the datasheet URL for the highlighted finding's component."""
        try:
            sidebar = self.query_one("#sidebar", FindingsSidebar)
        except Exception:
            return
        highlighted = sidebar.highlighted_child
        if not isinstance(highlighted, FindingItem):
            return
        # Finding model doesn't carry a datasheet_url; look for one in
        # the schematic-level parsed data if we ever add it.  For now
        # this is a no-op with a notification.
        self.notify("No datasheet URL available for this finding.")
