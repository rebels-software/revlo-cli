"""Textual TUI application for browsing review findings."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.color import Color
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Label, ListItem, ListView, Static

from revlo.report.markdown import generate_markdown_report
from revlo.reviewer.models import Finding, ReviewReport, Severity

if TYPE_CHECKING:
    from revlo.datasheet.models import DatasheetSpec

# ---------------------------------------------------------------------------
# Brand colours
# ---------------------------------------------------------------------------
DEEP_NAVY = "#0A1628"
PANEL_BG = "#0F1929"
MIDNIGHT_BLUE = "#5F471E"
BORDER_DIM = "#2A3A50"
ELECTRIC_TEAL = "#00D4AA"
SIGNAL_RED = "#FF4757"
WARM_AMBER = "#FFB347"
SOFT_WHITE = "#E8ECF1"
LIGHT_GRAY = "#B8C5D6"
MUTED_GRAY = "#6B7B8D"

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
_SEVERITY_COLOR: dict[Severity, str] = {
    Severity.error: SIGNAL_RED,
    Severity.warning: WARM_AMBER,
    Severity.suggestion: ELECTRIC_TEAL,
}

_FILTER_NAMES: dict[str, str] = {
    "all": "Filters",
    "errors": "Errors",
    "warnings": "Warnings",
    "suggestions": "Suggestions",
}


def _open_file(path: str) -> None:
    """Open a file with the OS default application (cross-platform)."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
    elif sys.platform == "win32":
        import os
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", path])


def _build_filter_left(filter_name: str) -> str:
    label = _FILTER_NAMES.get(filter_name, "All Findings")
    return f"[bold {ELECTRIC_TEAL}]\u25c6[/] [{SOFT_WHITE}]{label}[/]"


def _build_filter_center() -> str:
    return (
        f"  [{MUTED_GRAY}]\u2502[/]"
        f"  [{SIGNAL_RED}]e[/][{MUTED_GRAY}]rrors[/]"
        f"  [{WARM_AMBER}]w[/][{MUTED_GRAY}]arnings[/]"
        f"  [{ELECTRIC_TEAL}]s[/][{MUTED_GRAY}]uggestions[/]"
        f"  [{SOFT_WHITE}]a[/][{MUTED_GRAY}]ll[/]"
    )


def _build_filter_right() -> str:
    return (
        f"[{MUTED_GRAY}]\\[[/][{SOFT_WHITE}]m[/][{MUTED_GRAY}]] export  "
        f"\\[[/][{SOFT_WHITE}]q[/][{MUTED_GRAY}]] quit[/]"
    )


# ---------------------------------------------------------------------------
# Custom widgets
# ---------------------------------------------------------------------------


class BrandHeader(Horizontal):
    """Top header bar showing the Revlo brand, schematic name, stats, and date."""

    def __init__(
        self,
        schematic_name: str,
        review_date: str,
        report: ReviewReport | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._schematic_name = schematic_name
        self._review_date = review_date or ""
        self._report = report

    def compose(self) -> ComposeResult:
        yield Label(
            f"[bold {ELECTRIC_TEAL}]\u25c6 Revlo[/] [{MUTED_GRAY}]- AI-powered hardware review[/]",
            id="header-left",
        )
        yield Label(
            f"[bold {SOFT_WHITE}]{self._schematic_name}[/]",
            id="header-center",
        )
        stats_text = ""
        if self._report and self._report.findings:
            s = self._report.stats
            stats_text = (
                f"[{SIGNAL_RED}]{s.error}\u2717[/]  "
                f"[{WARM_AMBER}]{s.warning}\u25B2[/]  "
                f"[{ELECTRIC_TEAL}]{s.suggestion}\u25C6[/]"
                f"  [{MUTED_GRAY}]\u2502[/]  "
            )
        yield Label(
            f"{stats_text}[{LIGHT_GRAY}]{self._review_date}[/]",
            id="header-right",
        )


class StatsBar(Horizontal):
    """Horizontal bar showing severity count badges."""

    def __init__(self, report: ReviewReport, **kwargs) -> None:
        super().__init__(**kwargs)
        self._report = report

    def compose(self) -> ComposeResult:
        stats = self._report.stats
        yield Label(
            f"[bold {SIGNAL_RED}]\u2717[/] {stats.error} errors",
            classes="stat-badge stat-error",
        )
        yield Label(
            f"[bold {WARM_AMBER}]\u25B2[/] {stats.warning} warnings",
            classes="stat-badge stat-warning",
        )
        yield Label(
            f"[bold {ELECTRIC_TEAL}]\u25C6[/] {stats.suggestion} suggestions",
            classes="stat-badge stat-suggestion",
        )
        yield Label(
            f"[bold {SOFT_WHITE}]\u2211[/] {stats.total} total",
            classes="stat-badge stat-total",
        )


class SeverityGroupHeader(ListItem):
    """Visual group header showing severity name and count."""

    def __init__(self, severity: Severity, count: int) -> None:
        super().__init__(disabled=True)
        self._severity = severity
        self._count = count

    def compose(self) -> ComposeResult:
        icon = _SEVERITY_ICON[self._severity]
        label = _SEVERITY_LABEL[self._severity]
        color = _SEVERITY_COLOR[self._severity]
        yield Label(
            f"[bold {color}]{icon} {label}S ({self._count})[/]",
            classes="group-header-label",
        )


class FindingItem(ListItem):
    """A list item representing a single finding."""

    def __init__(self, finding: Finding, index: int) -> None:
        super().__init__()
        self.finding = finding
        self.finding_index = index

    def compose(self) -> ComposeResult:
        sev = self.finding.severity
        icon = _SEVERITY_ICON[sev]
        color = _SEVERITY_COLOR[sev]
        ref = self.finding.component_ref
        title = self.finding.title
        yield Label(
            f"[{color}]{icon}[/]  [{SOFT_WHITE}]{ref}:[/] [{LIGHT_GRAY}]{title}[/]",
            classes="finding-label",
        )


class FindingsSidebar(ListView):
    """Sidebar listing findings grouped by severity."""

    DEFAULT_CSS = """
    FindingsSidebar {
        background: #0A1628;
    }
    """

    def on_mount(self) -> None:
        self.styles.background = Color.parse("#0A1628")

    def __init__(
        self,
        findings: list[Finding],
        *,
        id: str | None = None,  # noqa: A002
    ) -> None:
        self._all_findings = findings
        super().__init__(id=id)

    def _build_items(self) -> list[ListItem]:
        items: list[ListItem] = []
        for sev in _SEVERITY_ORDER:
            group = [f for f in self._all_findings if f.severity == sev]
            if group:
                items.append(SeverityGroupHeader(sev, len(group)))
                for idx, finding in enumerate(self._all_findings):
                    if finding.severity == sev:
                        items.append(FindingItem(finding, idx))
        return items

    def compose(self) -> ComposeResult:
        yield from self._build_items()

    def rebuild(self, findings: list[Finding]) -> None:
        self._all_findings = findings
        self.clear()
        for item in self._build_items():
            self.append(item)


class DetailPanel(Vertical):
    """Right-hand panel showing full details of the selected finding."""

    def __init__(
        self,
        datasheet_specs: dict[str, DatasheetSpec] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._datasheet_specs: dict[str, DatasheetSpec] = datasheet_specs or {}

    def compose(self) -> ComposeResult:
        yield Static(
            f"[{LIGHT_GRAY}]Select a finding to view details.[/]",
            id="detail-placeholder",
        )
        yield Static("", id="detail-content")
        yield Static("", id="detail-description")
        yield Static("", id="detail-recommendation")

    def on_mount(self) -> None:
        self.query_one("#detail-description", Static).border_title = "Description"
        self.query_one("#detail-recommendation", Static).border_title = "Recommendation"

    @staticmethod
    def _format_pages(pages: list[int]) -> str:
        """Format a list of page numbers into a compact display string.

        Consecutive pages are collapsed into ranges (e.g. [3, 12, 15, 16, 17, 18]
        becomes "p.3, 12, 15-18").
        """
        if not pages:
            return ""
        sorted_pages = sorted(pages)
        parts: list[str] = []
        start = prev = sorted_pages[0]
        for p in sorted_pages[1:]:
            if p == prev + 1:
                prev = p
            else:
                parts.append(f"{start}" if start == prev else f"{start}-{prev}")
                start = prev = p
        parts.append(f"{start}" if start == prev else f"{start}-{prev}")
        return "p." + ", ".join(parts)

    def show_finding(self, finding: Finding) -> None:
        sev = finding.severity
        icon = _SEVERITY_ICON[sev]
        label = _SEVERITY_LABEL[sev]
        color = _SEVERITY_COLOR[sev]

        filled = int(finding.confidence * 10)
        bar = "\u2588" * filled + "\u2591" * (10 - filled)
        pct = f"{finding.confidence:.0%}"

        header_lines = [
            f"[bold {color}]{icon} {label}[/]  [bold {SOFT_WHITE}]{finding.title}[/]",
            "",
            f"[{SOFT_WHITE}]Component:[/]  [{ELECTRIC_TEAL}]{finding.component_ref}[/]",
            f"[{SOFT_WHITE}]Category:[/]   [{LIGHT_GRAY}]{finding.category.value}[/]",
            f"[{SOFT_WHITE}]Confidence:[/] [{ELECTRIC_TEAL}]{bar}[/] {pct}",
        ]

        # Show datasheet info if available for this component.
        spec = self._datasheet_specs.get(finding.component_ref)
        if spec and spec.pdf_path:
            pdf_name = Path(spec.pdf_path).name
            header_lines.append(
                f"[{SOFT_WHITE}]Datasheet:[/]  [{WARM_AMBER}]{pdf_name}[/]"
            )
            if spec.relevant_pages:
                pages_str = self._format_pages(spec.relevant_pages)
                header_lines.append(
                    f"[{SOFT_WHITE}]Pages:[/]      [{WARM_AMBER}]{pages_str}[/]"
                )
            header_lines.append(
                f"  [{MUTED_GRAY}]press Enter to open PDF[/]"
            )

        self.query_one("#detail-placeholder", Static).styles.display = "none"
        content = self.query_one("#detail-content", Static)
        content.styles.display = "block"
        content.update("\n".join(header_lines))

        desc = self.query_one("#detail-description", Static)
        desc.styles.display = "block"
        desc.update(finding.description)

        rec = self.query_one("#detail-recommendation", Static)
        rec.styles.display = "block"
        rec.update(finding.recommendation)

    def show_empty(self) -> None:
        self.query_one("#detail-placeholder", Static).styles.display = "block"
        self.query_one("#detail-placeholder", Static).update(
            f"[{ELECTRIC_TEAL}]\u2713 No issues found! Your schematic looks good.[/]"
        )
        self.query_one("#detail-content", Static).styles.display = "none"
        self.query_one("#detail-description", Static).styles.display = "none"
        self.query_one("#detail-recommendation", Static).styles.display = "none"


class FilterBar(Horizontal):
    """Bottom bar showing active filter name and keybinding hints."""

    _active_filter: str = "all"

    def compose(self) -> ComposeResult:
        yield Label(
            _build_filter_left(self._active_filter),
            id="filter-left",
        )
        yield Label(
            _build_filter_center(),
            id="filter-center",
        )
        yield Label(
            _build_filter_right(),
            id="filter-right",
        )

    def set_filter(self, filter_name: str) -> None:
        self._active_filter = filter_name
        self.query_one("#filter-left", Label).update(
            _build_filter_left(filter_name)
        )


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------


class RevloApp(App[None]):
    """Interactive TUI findings browser for Revlo."""

    CSS_PATH = "revlo.tcss"
    TITLE = "Revlo Review"

    BINDINGS = [
        Binding("q", "quit", "Quit", show=False),
        Binding("escape", "quit", "Quit", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("e", "filter_errors", "Errors", show=False),
        Binding("w", "filter_warnings", "Warnings", show=False),
        Binding("s", "filter_suggestions", "Suggestions", show=False),
        Binding("a", "filter_all", "All", show=False),
        Binding("m", "export_markdown", "Export MD", show=False),
        Binding("enter", "open_datasheet", "Open URL", show=False),
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

    @staticmethod
    def _sort_findings(findings: list[Finding]) -> list[Finding]:
        order = {Severity.error: 0, Severity.warning: 1, Severity.suggestion: 2}
        return sorted(findings, key=lambda f: order.get(f.severity, 99))

    def _filtered_findings(self) -> list[Finding]:
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

    def compose(self) -> ComposeResult:
        sch_name = Path(self.schematic_path).name
        review_date = self.report.review_date
        yield BrandHeader(sch_name, review_date, report=self.report, id="brand-header")
        if not self.report.findings:
            yield Static(
                f"[{ELECTRIC_TEAL}]\u2713 No issues found! "
                f"Your schematic looks good.[/]",
                id="empty-state",
            )
        else:
            with Horizontal(id="main-container"):
                yield FindingsSidebar(
                    self._filtered_findings(),
                    id="sidebar",
                )
                yield DetailPanel(
                    datasheet_specs=self.report.datasheet_specs,
                    id="detail-panel",
                )
        yield FilterBar(id="filter-bar")

    # -- events --

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, FindingItem):
            panel = self.query_one("#detail-panel", DetailPanel)
            panel.show_finding(item.finding)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        item = event.item
        if isinstance(item, FindingItem):
            try:
                panel = self.query_one("#detail-panel", DetailPanel)
                panel.show_finding(item.finding)
            except Exception:
                pass

    # -- filter actions --

    def _apply_filter(self, filter_name: str) -> None:
        self.active_filter = filter_name
        try:
            sidebar = self.query_one("#sidebar", FindingsSidebar)
        except Exception:
            return
        sidebar.rebuild(self._filtered_findings())
        try:
            self.query_one("#filter-bar", FilterBar).set_filter(filter_name)
        except Exception:
            pass

    def action_filter_errors(self) -> None:
        self._apply_filter("errors")

    def action_filter_warnings(self) -> None:
        self._apply_filter("warnings")

    def action_filter_suggestions(self) -> None:
        self._apply_filter("suggestions")

    def action_filter_all(self) -> None:
        self._apply_filter("all")

    # -- navigation --

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

    # -- export / open --

    def action_export_markdown(self) -> None:
        stem = Path(self.schematic_path).stem
        out_path = Path(self.schematic_path).parent / f"{stem}-review.md"
        md = generate_markdown_report(self.report)
        out_path.write_text(md)
        self.notify(f"Exported to {out_path.name}")

    def action_open_datasheet(self) -> None:
        try:
            sidebar = self.query_one("#sidebar", FindingsSidebar)
        except Exception:
            return
        highlighted = sidebar.highlighted_child
        if not isinstance(highlighted, FindingItem):
            return

        ref = highlighted.finding.component_ref
        spec = self.report.datasheet_specs.get(ref)
        if spec and spec.pdf_path and Path(spec.pdf_path).exists():
            _open_file(spec.pdf_path)
            self.notify(f"Opening datasheet for {ref}")
        else:
            self.notify("No datasheet available for this finding.")
