"""Textual TUI application for browsing review findings."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.color import Color
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Input, Label, ListItem, ListView, Static

from revlo.config import DEFAULT_MODEL
from revlo.report.markdown import generate_markdown_report
from revlo.reviewer.models import Finding, ReviewReport, Severity

if TYPE_CHECKING:
    from revlo.datasheet.models import DatasheetSpec

logger = logging.getLogger(__name__)

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



def _build_filter_left(filter_name: str) -> str:
    label = _FILTER_NAMES.get(filter_name, "All Findings")
    return f"[bold {ELECTRIC_TEAL}]\u25c6[/] [{SOFT_WHITE}]{label}[/]"


def _build_filter_center() -> str:
    return (
        f"  [{MUTED_GRAY}]\u2502[/]"
        f"  [{SIGNAL_RED}]e[/][{MUTED_GRAY}]rrors[/]"
        f"  [{WARM_AMBER}]w[/][{MUTED_GRAY}]arnings[/]"
        f"  [{ELECTRIC_TEAL}]s[/][{MUTED_GRAY}]uggestions[/]"
        f"  [{SOFT_WHITE}]f[/][{MUTED_GRAY}]ilter all[/]"
    )


def _build_filter_right() -> str:
    return (
        f"[{MUTED_GRAY}]\\[[/][{ELECTRIC_TEAL}]a[/][{MUTED_GRAY}]] ask  "
        f"\\[[/][{SOFT_WHITE}]o[/][{MUTED_GRAY}]] open pdf  "
        f"\\[[/][{SOFT_WHITE}]m[/][{MUTED_GRAY}]] export  "
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
                f"  [{MUTED_GRAY}]press O to open PDF[/]"
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
        Binding("escape", "escape_key", "Escape", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("e", "filter_errors", "Errors", show=False),
        Binding("w", "filter_warnings", "Warnings", show=False),
        Binding("s", "filter_suggestions", "Suggestions", show=False),
        Binding("f", "filter_all", "All", show=False),
        Binding("a", "ask", "Ask", show=False),
        Binding("m", "export_markdown", "Export MD", show=False),
        Binding("o", "open_datasheet", "Open PDF", show=False),
    ]

    active_filter: reactive[str] = reactive("all")
    _chat_mode: reactive[bool] = reactive(False)

    def __init__(
        self,
        report: ReviewReport,
        schematic_path: str,
        review_path: Path | None = None,
        parsed_schematic: object | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.report = report
        self.schematic_path = schematic_path
        self._review_path = review_path  # Path to the .revlo review JSON
        self._parsed_schematic = parsed_schematic
        self._sorted_findings = self._sort_findings(report.findings)
        self._chat_panel = None
        self._conversation: list[dict] = []  # API-format messages

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

    def _get_parsed_schematic(self):
        """Get or lazily parse the schematic for tool use."""
        if self._parsed_schematic is not None:
            return self._parsed_schematic
        try:
            from revlo.parser import parse_schematic
            self._parsed_schematic = parse_schematic(self.schematic_path)
            return self._parsed_schematic
        except Exception:
            logger.warning("Could not parse schematic for tool use", exc_info=True)
            return None

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
        if self._chat_mode:
            return
        item = event.item
        if isinstance(item, FindingItem):
            panel = self.query_one("#detail-panel", DetailPanel)
            panel.show_finding(item.finding)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if self._chat_mode:
            return
        item = event.item
        if isinstance(item, FindingItem):
            try:
                panel = self.query_one("#detail-panel", DetailPanel)
                panel.show_finding(item.finding)
            except Exception:
                pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter in the chat input."""
        if not self._chat_mode or self._chat_panel is None:
            return
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        self._send_chat_message(text)

    # -- escape handling --

    def action_escape_key(self) -> None:
        """Handle Escape: exit chat mode or quit the app."""
        if self._chat_mode:
            self._exit_chat_mode()
        else:
            self.exit()

    # -- filter actions --

    def _apply_filter(self, filter_name: str) -> None:
        if self._chat_mode:
            return
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
        if self._chat_mode:
            return
        try:
            sidebar = self.query_one("#sidebar", FindingsSidebar)
            sidebar.action_cursor_down()
        except Exception:
            pass

    def action_cursor_up(self) -> None:
        if self._chat_mode:
            return
        try:
            sidebar = self.query_one("#sidebar", FindingsSidebar)
            sidebar.action_cursor_up()
        except Exception:
            pass

    # -- ask mode --

    def action_ask(self) -> None:
        """Enter chat / ask mode."""
        if self._chat_mode:
            return
        self._enter_chat_mode()

    def _get_highlighted_finding(self) -> Finding | None:
        """Return the currently highlighted finding, if any."""
        try:
            sidebar = self.query_one("#sidebar", FindingsSidebar)
            highlighted = sidebar.highlighted_child
            if isinstance(highlighted, FindingItem):
                return highlighted.finding
        except Exception:
            pass
        return None

    def _enter_chat_mode(self) -> None:
        """Show the chat panel, hiding the detail panel."""
        from revlo.tui.chat import ChatPanel

        self._chat_mode = True

        # Hide detail panel
        try:
            detail = self.query_one("#detail-panel", DetailPanel)
            detail.styles.display = "none"
        except Exception:
            pass

        # Build initial context from highlighted finding
        initial_context = ""
        finding = self._get_highlighted_finding()
        if finding is not None:
            initial_context = (
                f"[{finding.severity.value.upper()}] {finding.component_ref}: "
                f"{finding.title} -- {finding.description}"
            )

        # Create and mount chat panel into main-container
        try:
            container = self.query_one("#main-container", Horizontal)
        except Exception:
            # No main container (empty report) -- mount at app level before filter bar
            container = None

        chat = ChatPanel(initial_context=initial_context, id="chat-panel")
        self._chat_panel = chat

        if container is not None:
            container.mount(chat)
        else:
            # Mount before filter bar
            try:
                fbar = self.query_one("#filter-bar", FilterBar)
                self.mount(chat, before=fbar)
            except Exception:
                self.mount(chat)

    def _exit_chat_mode(self) -> None:
        """Return to findings detail view, saving the conversation."""
        self._chat_mode = False

        # Save conversation if there are messages
        if self._chat_panel is not None and self._chat_panel.messages:
            self._save_conversation()

        # Remove chat panel
        if self._chat_panel is not None:
            self._chat_panel.remove()
            self._chat_panel = None

        # Show detail panel
        try:
            detail = self.query_one("#detail-panel", DetailPanel)
            detail.styles.display = "block"
        except Exception:
            pass

        # Clear conversation history for next session
        self._conversation = []

    def _save_conversation(self) -> None:
        """Save the current chat conversation to disk."""
        if self._chat_panel is None:
            return
        messages = [m.to_dict() for m in self._chat_panel.messages]
        if not messages:
            return
        try:
            from revlo.storage import save_chat
            path = save_chat(
                messages,
                self.schematic_path,
                review_path=self._review_path,
            )
            self.notify(f"Chat saved to {path.name}")
        except Exception:
            logger.warning("Failed to save chat conversation", exc_info=True)

    def _send_chat_message(self, text: str) -> None:
        """Send a user message to Claude and stream the response."""
        if self._chat_panel is None:
            return

        # Add user message to UI
        self._chat_panel.add_user_message(text)
        self._chat_panel.set_input_enabled(False)

        # Add to API conversation history
        self._conversation.append({"role": "user", "content": text})

        # Start streaming assistant response
        self._chat_panel.start_assistant_message()
        self._stream_response()

    @property
    def _system_prompt(self) -> str:
        """Build the system prompt for the ask-mode chat."""
        from revlo.tui.chat import build_ask_system_prompt
        return build_ask_system_prompt(
            report=self.report,
            datasheet_specs=self.report.datasheet_specs,
        )

    def _stream_response(self) -> None:
        """Start the threaded streaming worker."""
        self.run_worker(
            self._do_stream,  # pass the method, not a coroutine
            thread=True,      # run in a separate thread
            name="chat_stream",
            exclusive=True,
        )

    def _do_stream(self) -> None:
        """Threaded worker: non-streaming with tool use loop, streams text to UI."""
        import anthropic

        from revlo.tui.tools import SCHEMATIC_TOOLS, execute_tool

        client = anthropic.Anthropic()
        messages = list(self._conversation)
        full_text = ""

        # Only include tools if we have a parsed schematic
        parsed = self._get_parsed_schematic()
        tools = SCHEMATIC_TOOLS if parsed is not None else []
        specs = self.report.datasheet_specs or {}

        max_rounds = 10
        for _ in range(max_rounds):
            try:
                response = client.messages.create(
                    model=DEFAULT_MODEL,
                    max_tokens=4096,
                    system=self._system_prompt,
                    messages=messages,
                    tools=tools if tools else anthropic.NOT_GIVEN,
                )
            except Exception as exc:
                logger.warning("Chat API call failed: %s", exc, exc_info=True)
                full_text = full_text or f"Error: could not reach Claude. ({exc})"
                break

            # Separate text and tool_use blocks
            text_parts: list[str] = []
            tool_uses: list = []
            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_uses.append(block)

            # Accumulate text and update UI
            if text_parts:
                full_text += "".join(text_parts)
                if self._chat_panel is not None:
                    self.call_from_thread(
                        self._chat_panel.update_assistant_stream, full_text
                    )

            # If no tool calls, we're done
            if not tool_uses:
                break

            # Show tool use status in the chat
            for tu in tool_uses:
                status = _tool_status_text(tu.name, tu.input)
                if self._chat_panel is not None:
                    self.call_from_thread(
                        self._chat_panel.show_tool_status, status
                    )

            # Build assistant message with all content blocks for the API
            messages.append({
                "role": "assistant",
                "content": [_block_to_dict(b) for b in response.content],
            })

            # Execute tools and build tool_result message
            tool_results: list[dict] = []
            for tu in tool_uses:
                result = execute_tool(tu.name, tu.input, parsed, specs)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": result,
                })
            messages.append({"role": "user", "content": tool_results})

        # Finalize the message
        if self._chat_panel is not None:
            self.call_from_thread(self._chat_panel.finish_assistant_message, full_text)
            self.call_from_thread(self._chat_panel.set_input_enabled, True)

        self._conversation.append({"role": "assistant", "content": full_text})

    # -- export / open --

    def action_export_markdown(self) -> None:
        if self._chat_mode:
            return
        stem = Path(self.schematic_path).stem
        out_path = Path(self.schematic_path).parent / f"{stem}-review.md"
        md = generate_markdown_report(self.report)
        out_path.write_text(md)
        self.notify(f"Exported to {out_path.name}")

    def action_open_datasheet(self) -> None:
        if self._chat_mode:
            return
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
            pdf_path = spec.pdf_path
            import subprocess
            import sys
            if sys.platform == "darwin":
                subprocess.Popen(["open", pdf_path])
            elif sys.platform == "win32":
                import os
                os.startfile(pdf_path)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", pdf_path])
            self.notify(f"Opening datasheet for {ref} (p.{spec.relevant_pages[0]})" if spec.relevant_pages else f"Opening datasheet for {ref}")
        else:
            self.notify("No datasheet available for this finding.")

    def action_quit(self) -> None:
        """Override quit to save chat before exiting."""
        if self._chat_mode and self._chat_panel is not None:
            if self._chat_panel.messages:
                self._save_conversation()
        self.exit()


# ---------------------------------------------------------------------------
# Module-level helpers for tool-use loop
# ---------------------------------------------------------------------------


def _block_to_dict(block) -> dict:
    """Convert an API content block to a dict for message history."""
    if block.type == "text":
        return {"type": "text", "text": block.text}
    elif block.type == "tool_use":
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
    return {"type": block.type}


def _tool_status_text(name: str, args: dict) -> str:
    """Build a user-friendly status string for a tool call."""
    if name == "lookup_component":
        return f"Looking up {args.get('ref', '?')}..."
    elif name == "trace_net":
        return f"Tracing net {args.get('net_name', '?')}..."
    elif name == "find_unconnected_pins":
        ref = args.get("ref")
        return f"Finding unconnected pins{' on ' + ref if ref else ''}..."
    elif name == "list_power_rails":
        return "Listing power rails..."
    return f"Using {name}..."
