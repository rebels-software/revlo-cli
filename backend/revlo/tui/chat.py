"""Chat panel for interactive Ask mode in the TUI.

Provides a scrollable conversation area with text input for asking
Claude questions about the schematic, grounded in parsed data,
datasheets, and review findings.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Union

from rich.console import Group as RichGroup
from rich.markdown import Markdown as RichMarkdown
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

    # Convert markdown bold (**text**) to Rich bold markup.
    safe = re.sub(r"\*\*(.+?)\*\*", r"[bold]\1[/bold]", safe)

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
        "You help users understand and improve their KiCad schematic designs.\n\n"
        "### How to reason\n"
        "Think through problems step by step. Show your work — calculate values, "
        "derive time constants, check voltage margins. When a question involves "
        "multiple components, trace the signal path end-to-end and verify that "
        "every component in the chain is compatible.\n\n"
        "### Tool use\n"
        "ALWAYS use your tools to look up real data before answering. Never guess "
        "component values or pin connections. Chain multiple tool calls to build a "
        "complete picture — for example, look up a component, then trace its nets, "
        "then check what else is on those nets.\n\n"
        "### Datasheet citations\n"
        "Cite specific datasheet pages, tables, and figures. "
        "Format: 'See datasheet p.47, Table 13'. When you have PDF paths and "
        "relevant page numbers in context, reference them to ground your answers.\n\n"
        "### Cross-component analysis\n"
        "Trace signal paths end-to-end. Check that every component in the chain "
        "is compatible — voltage levels, current ratings, timing requirements, "
        "and impedance matching. Flag mismatches proactively."
    )

    # 2b) Tool use instructions
    sections.append(
        "## Available Tools\n\n"
        "You have tools to query the schematic in real-time:\n"
        "- **lookup_component(ref)**: Get full details of a component (pins, nets, footprint, datasheet)\n"
        "- **trace_net(net_name)**: See all components/pins connected to a net\n"
        "- **find_unconnected_pins(ref?)**: Find floating pins\n"
        "- **list_power_rails()**: List all power nets and their connections\n\n"
        "USE THESE TOOLS to look up specific data instead of guessing. "
        "When a user asks about a component or net, ALWAYS look it up first. "
        "Chain multiple tool calls to trace signal paths or verify connectivity."
    )

    # 2c) Few-shot example interactions
    sections.append(
        "## Example Interactions\n\n"
        "**Q: Is my reset circuit correct for U1?**\n"
        "A: Let me check. [uses lookup_component(U1) to get the MCU type and NRST pin]\n"
        "[uses trace_net on the NRST net to see what's connected]\n"
        "The STM32F103 datasheet (p.47, Table 13) specifies:\n"
        "- NRST pin requires a 100nF filter capacitor to ground\n"
        "- External reset pulse must be low for at least 20\u00b5s\n"
        "Your circuit has C3 (100nF) connected between NRST and GND \u2713\n"
        "R5 (10k\u03a9) pulls NRST to VCC \u2713\n"
        "RC time constant: 10k\u03a9 \u00d7 100nF = 1ms \u2014 well above the 20\u00b5s minimum \u2713\n"
        "Your reset circuit meets all datasheet requirements.\n\n"
        "**Q: Can I run U2 at 2.5V instead of 3.3V?**\n"
        "A: [uses lookup_component(U2) to check the regulator specs]\n"
        "[uses trace_net on U2's output to find what's powered by it]\n"
        "The AMS1117-3.3 is a fixed 3.3V output regulator \u2014 it cannot be configured for 2.5V.\n"
        "If you need 2.5V, you'd need to replace U2 with an adjustable LDO (e.g. AMS1117-ADJ)\n"
        "and add a resistor divider on the feedback pin.\n"
        "WARNING: Components on the 3V3 rail (U1, C11, C12) are rated for 3.3V operation.\n"
        "U1 (STM32F103) minimum VDD is 2.0V (datasheet p.52), so 2.5V would work for the MCU,\n"
        "but verify all other components on that rail support 2.5V.\n\n"
        "**Q: What's the total current draw on the 3V3 rail?**\n"
        "A: [uses list_power_rails() to find the 3V3 net]\n"
        "[uses lookup_component for each IC on the rail]\n"
        "Components on +3V3:\n"
        "- U1 (STM32F103): max 150mA (datasheet p.55, all peripherals active)\n"
        "- U3 (CH340G): max 30mA (datasheet p.3)\n"
        "- Passives: negligible\n"
        "Total worst-case: ~180mA\n"
        "U2 (AMS1117-3.3) can supply up to 1A \u2014 adequate margin.\n"
        "Power dissipation: (5V - 3.3V) \u00d7 0.18A = 0.31W \u2014 within SOT-223 thermal limits."
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

    # 6) Response guidelines
    sections.append(
        "## Response Guidelines\n\n"
        "- For complex questions, think step by step and show calculations\n"
        "- Always look up real data with tools before making claims\n"
        "- When uncertain, say so \u2014 don't fabricate specifications\n"
        "- Format component references in the response (e.g. U1, R4, C10)\n"
        "- Cite datasheet pages when referencing specifications\n"
        "- Keep responses focused and actionable"
    )

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
        self._finalized = False
        # Pass formatted content to Static.__init__ so the widget has
        # correct dimensions from the very first layout calculation.
        super().__init__(self._format_content(), **kwargs)

    def _format_content(self) -> Union[str, RichGroup]:
        """Format message content for display.

        User messages use Rich markup for simple label + text rendering.
        Assistant messages use Rich markup during streaming (for speed),
        then switch to full ``rich.markdown.Markdown`` rendering once
        the response is finalized -- giving proper headers, tables,
        lists, code blocks, bold, etc.
        """
        if self._role == "user":
            return f"[bold {SOFT_WHITE}]You:[/] [{LIGHT_GRAY}]{self._content}[/]"
        if self._finalized:
            # Full markdown rendering for completed assistant messages
            label = f"[bold {ELECTRIC_TEAL}]Revlo:[/]"
            md = RichMarkdown(self._content)
            return RichGroup(label, md)
        # Plain Rich markup during streaming
        marked = markup_response(self._content)
        return f"[bold {ELECTRIC_TEAL}]Revlo:[/] {marked}"

    def update_content(self, content: str) -> None:
        """Update the message content (used during streaming)."""
        self._content = content
        self.update(self._format_content())
        self.refresh(layout=True)  # height changes as streaming text grows

    def finalize(self) -> None:
        """Switch to full markdown rendering after streaming completes."""
        self._finalized = True
        self.update(self._format_content())
        self.refresh(layout=True)


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

    def start_assistant_message(self, placeholder: str = "Thinking...") -> None:
        """Add a placeholder for the assistant response (for streaming)."""
        scroll = self.query_one("#chat-scroll", VerticalScroll)
        bubble = MessageBubble("assistant", placeholder)
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
            self._streaming_bubble.finalize()  # switch to markdown rendering
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

    def show_tool_status(self, status: str) -> None:
        """Show a tool use status line in the conversation."""
        scroll = self.query_one("#chat-scroll", VerticalScroll)
        label = Static(
            f"[{MUTED_GRAY}]  \u21b3 {status}[/]",
            classes="chat-tool-status",
        )
        scroll.mount(label)
        scroll.scroll_end(animate=False)

    def load_history(self, messages: list[dict]) -> None:
        """Load saved chat messages into the conversation area.

        Each message dict should have keys: role, content, and optionally timestamp.
        Populates both the visual scroll area and the internal messages list.
        """
        scroll = self.query_one("#chat-scroll", VerticalScroll)
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            timestamp = m.get("timestamp", "")
            msg = ChatMessage(role, content, timestamp)
            self.messages.append(msg)
            bubble = MessageBubble(role, content)
            if role == "assistant":
                bubble._finalized = True
            scroll.mount(bubble)
        scroll.scroll_end(animate=False)

    def set_input_enabled(self, enabled: bool) -> None:
        """Enable or disable the chat input."""
        inp = self.query_one("#chat-input", Input)
        inp.disabled = not enabled
