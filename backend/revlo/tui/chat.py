"""Chat panel for interactive Ask mode in the TUI.

Provides a scrollable conversation area with text input for asking
Claude questions about the schematic, grounded in parsed data,
datasheets, and review findings.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from textual.containers import Vertical, VerticalScroll
from textual.widgets import Input, Static

if TYPE_CHECKING:
    from revlo.datasheet.models import DatasheetSpec
    from revlo.reviewer.models import ReviewReport

logger = logging.getLogger(__name__)

# Brand colours (duplicated for self-containment; kept in sync with app.py)
ELECTRIC_TEAL = "#00D4AA"
WARM_AMBER = "#FFB347"
SOFT_WHITE = "#E8ECF1"
LIGHT_GRAY = "#B8C5D6"
MUTED_GRAY = "#6B7B8D"


# ---------------------------------------------------------------------------
# Rich-markup post-processing
# ---------------------------------------------------------------------------

# Matches typical component refs: U1, R10, C3, D2, Q1, L1, FB1, SW1, J1, etc.
_COMP_REF_RE = re.compile(r"\b([A-Z]{1,3})(\d{1,4})\b")

# Matches page citations: "p.42", "page 42", "p. 12", "pages 3-5"
_PAGE_CITE_RE = re.compile(
    r"\b(p(?:ages?)?\s*\.?\s*\d+(?:\s*[-,]\s*\d+)*)",
    re.IGNORECASE,
)


def markup_response(text: str) -> str:
    """Apply Rich markup to assistant response text.

    - Component references (U1, R2, C10, ...) are highlighted in teal.
    - Datasheet page citations (p.42, page 12, ...) are highlighted in amber.
    """
    # First escape any Rich markup characters in the raw text.
    # We only need to handle [ ] since those are Rich markup delimiters.
    # But we must be careful not to double-escape if already escaped.
    # Actually, we'll insert our own markup, so we should escape user text first.
    safe = text.replace("[", "\\[").replace("]", "\\]")

    # Apply page citations first (longer patterns) so component refs inside
    # don't get double-wrapped.
    def _page_repl(m: re.Match) -> str:
        return f"[{WARM_AMBER}]{m.group(0)}[/]"

    safe = _PAGE_CITE_RE.sub(_page_repl, safe)

    # Apply component ref highlighting.
    def _ref_repl(m: re.Match) -> str:
        prefix = m.group(1)
        # Only highlight known EE prefixes
        if prefix in (
            "U", "R", "C", "L", "D", "Q", "F", "FB", "SW", "J", "P",
            "K", "T", "Y", "X",
        ):
            return f"[{ELECTRIC_TEAL}]{m.group(0)}[/]"
        return m.group(0)

    safe = _COMP_REF_RE.sub(_ref_repl, safe)
    return safe


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

def build_ask_system_prompt(
    report: ReviewReport,
    datasheet_specs: dict[str, DatasheetSpec] | None = None,
    schematic_summary: str = "",
) -> str:
    """Build a system prompt for the ask-mode chat.

    Includes EE base knowledge, schematic context, datasheet specs,
    and current review findings.
    """
    from revlo.skills import load_skill

    sections: list[str] = []

    # 1) EE base knowledge
    try:
        base_ee = load_skill("base_ee_knowledge")
        sections.append(base_ee)
    except Exception:
        logger.warning("Could not load base_ee_knowledge skill")

    # 2) Role instruction
    sections.append(
        "You are Revlo, an expert electronics engineering assistant. "
        "You help users understand and improve their KiCad schematic designs. "
        "Answer questions accurately and concisely, citing specific component "
        "references, pin numbers, net names, and datasheet page numbers where relevant. "
        "When referencing datasheets, cite page numbers like: 'See datasheet p.42'."
    )

    # 3) Schematic summary
    if schematic_summary:
        sections.append(f"## Current Schematic\n\n{schematic_summary}")

    # 4) Datasheet specs
    specs = datasheet_specs or report.datasheet_specs or {}
    if specs:
        ds_lines: list[str] = ["## Datasheet Specifications"]
        for ref, spec in sorted(specs.items()):
            ds_lines.append(f"\n### {ref}: {spec.mpn}")
            if spec.manufacturer:
                ds_lines.append(f"- Manufacturer: {spec.manufacturer}")
            if spec.description:
                ds_lines.append(f"- Description: {spec.description}")
            if spec.supply_voltage_min is not None or spec.supply_voltage_max is not None:
                vmin = spec.supply_voltage_min if spec.supply_voltage_min is not None else "?"
                vmax = spec.supply_voltage_max if spec.supply_voltage_max is not None else "?"
                ds_lines.append(f"- Supply Voltage: {vmin}V to {vmax}V")
            if spec.pdf_path:
                ds_lines.append(f"- PDF: file://{spec.pdf_path}")
                if spec.relevant_pages:
                    pages = ", ".join(str(p) for p in spec.relevant_pages[:20])
                    ds_lines.append(f"- Relevant pages: {pages}")
            if spec.pin_functions:
                ds_lines.append("- Pin Functions:")
                for pf in spec.pin_functions[:30]:
                    desc = f" -- {pf.function_description}" if pf.function_description else ""
                    ds_lines.append(f"  - Pin {pf.pin_number} ({pf.name}){desc}")
        sections.append("\n".join(ds_lines))

    # 5) Current findings
    if report.findings:
        f_lines: list[str] = ["## Current Review Findings"]
        for i, f in enumerate(report.findings, 1):
            f_lines.append(
                f"{i}. [{f.severity.value.upper()}] {f.component_ref}: "
                f"{f.title} -- {f.description}"
            )
        sections.append("\n".join(f_lines))

    return "\n\n---\n\n".join(sections)


# ---------------------------------------------------------------------------
# Chat message model
# ---------------------------------------------------------------------------

class ChatMessage:
    """A single message in the conversation."""

    __slots__ = ("role", "content", "timestamp")

    def __init__(self, role: str, content: str, timestamp: str = "") -> None:
        self.role = role
        self.content = content
        self.timestamp = timestamp

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content, "timestamp": self.timestamp}

    def to_api_dict(self) -> dict:
        """Return the dict format expected by the Anthropic messages API."""
        return {"role": self.role, "content": self.content}


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------


class MessageBubble(Static):
    """A single chat message displayed in the conversation area."""

    DEFAULT_CSS = """
    MessageBubble {
        width: 1fr;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    """

    def __init__(self, role: str, content: str, **kwargs) -> None:
        self._role = role
        self._content = content
        super().__init__(**kwargs)

    def on_mount(self) -> None:
        self._render_content()

    def _render_content(self) -> None:
        if self._role == "user":
            formatted = f"[bold {SOFT_WHITE}]You:[/] [{LIGHT_GRAY}]{self._content}[/]"
        else:
            marked = markup_response(self._content)
            formatted = f"[bold {ELECTRIC_TEAL}]Revlo:[/] {marked}"
        self.update(formatted)

    def update_content(self, content: str) -> None:
        """Update the message content (used during streaming)."""
        self._content = content
        self._render_content()


class ChatPanel(Vertical):
    """Chat panel with scrollable conversation area and text input.

    Replaces the DetailPanel when the user enters Ask mode.
    """

    DEFAULT_CSS = """
    ChatPanel {
        width: 1fr;
        height: 100%;
        background: #0A1628;
        padding: 1 2;
    }
    """

    def __init__(self, initial_context: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.messages: list[ChatMessage] = []
        self._streaming_bubble: MessageBubble | None = None
        self._initial_context: str = initial_context

    def compose(self):
        yield Static(
            f"[bold {ELECTRIC_TEAL}]Ask Revlo[/]  [{MUTED_GRAY}]Ask questions about your schematic. Press Escape to return.[/]",
            id="chat-header",
        )
        yield VerticalScroll(id="chat-scroll")
        yield Input(
            placeholder="Ask about your schematic...",
            id="chat-input",
        )

    def on_mount(self) -> None:
        if self._initial_context:
            self.add_initial_context(self._initial_context)
        self.query_one("#chat-input", Input).focus()

    def add_user_message(self, text: str) -> None:
        """Add a user message to the conversation."""
        from datetime import datetime, timezone

        msg = ChatMessage("user", text, datetime.now(timezone.utc).isoformat())
        self.messages.append(msg)
        scroll = self.query_one("#chat-scroll", VerticalScroll)
        scroll.mount(MessageBubble("user", text))
        scroll.scroll_end(animate=False)

    def start_assistant_message(self) -> None:
        """Add a placeholder for the assistant response (for streaming)."""
        scroll = self.query_one("#chat-scroll", VerticalScroll)
        bubble = MessageBubble("assistant", f"[{MUTED_GRAY}]Thinking...[/]")
        self._streaming_bubble = bubble
        scroll.mount(bubble)
        scroll.scroll_end(animate=False)

    def update_assistant_stream(self, text: str) -> None:
        """Update the streaming assistant message with new text."""
        if self._streaming_bubble is not None:
            self._streaming_bubble.update_content(text)
            try:
                scroll = self.query_one("#chat-scroll", VerticalScroll)
                scroll.scroll_end(animate=False)
            except Exception:
                pass

    def finish_assistant_message(self, full_text: str) -> None:
        """Finalize the assistant message after streaming completes."""
        from datetime import datetime, timezone

        if self._streaming_bubble is not None:
            self._streaming_bubble.update_content(full_text)
            self._streaming_bubble = None
        msg = ChatMessage("assistant", full_text, datetime.now(timezone.utc).isoformat())
        self.messages.append(msg)
        try:
            scroll = self.query_one("#chat-scroll", VerticalScroll)
            scroll.scroll_end(animate=False)
        except Exception:
            pass

    def add_initial_context(self, finding_text: str) -> None:
        """Add an initial context banner showing the highlighted finding."""
        scroll = self.query_one("#chat-scroll", VerticalScroll)
        banner = Static(
            f"[{MUTED_GRAY}]Context: {finding_text}[/]",
            classes="chat-context-banner",
        )
        scroll.mount(banner)

    def set_input_enabled(self, enabled: bool) -> None:
        """Enable or disable the chat input."""
        inp = self.query_one("#chat-input", Input)
        inp.disabled = not enabled
