"""Rich-based CLI output helpers for branded Revlo progress display."""

from __future__ import annotations

from rich.console import Console
from rich.progress import ProgressColumn, Task as RichTask
from rich.text import Text

from revlo.reviewer.models import ReviewReport, Severity

# ---------------------------------------------------------------------------
# Brand colours
# ---------------------------------------------------------------------------
TEAL = "#00D4AA"   # Electric Teal  -- progress / info
RED = "#FF4757"    # Signal Red     -- errors
AMBER = "#FFB347"  # Warm Amber     -- warnings


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------
VERSION = "v0.1"
LOGO = (
    "██████╗ ███████╗██╗   ██╗██╗      ██████╗ \n"
    "██╔══██╗██╔════╝██║   ██║██║     ██╔═══██╗\n"
    "██████╔╝█████╗  ██║   ██║██║     ██║   ██║\n"
    "██╔══██╗██╔══╝  ╚██╗ ██╔╝██║     ██║   ██║\n"
    "██║  ██║███████╗ ╚████╔╝ ███████╗╚██████╔╝\n"
    f"╚═╝  ╚═╝╚══════╝  ╚═══╝  ╚══════╝ ╚═════╝ {VERSION}"
)


class BlockBarColumn(ProgressColumn):
    """A progress bar with solid teal fill and dotted teal background."""

    def __init__(self, bar_width: int = 30) -> None:
        super().__init__()
        self.bar_width = bar_width

    def render(self, task: RichTask) -> Text:
        if not task.total:
            return Text("\u2591" * self.bar_width, style=TEAL)
        filled = int(self.bar_width * task.completed / task.total)
        empty = self.bar_width - filled
        bar = Text()
        bar.append("\u2588" * filled, style=TEAL)
        bar.append("\u2591" * empty, style=TEAL)
        return bar


class BenDayDotsColumn(ProgressColumn):
    """A progress bar with solid teal fill and halftone Ben-Day dots remainder.

    Filled portion uses solid blocks (``\u2588``), remaining uses
    alternating braille characters (``\u2895\u286a``) whose dot positions
    interleave to form a fine-grained checkerboard / halftone pattern.
    """

    _FILL = "\u2588"               # █  — solid block
    _DOTS = "\u2895"               # ⢕ — diagonal dot checkerboard

    def __init__(self, bar_width: int = 30) -> None:
        super().__init__()
        self.bar_width = bar_width

    def render(self, task: RichTask) -> Text:
        if not task.total:
            return Text(self._DOTS * self.bar_width, style=TEAL)
        filled = int(self.bar_width * task.completed / task.total)
        empty = self.bar_width - filled
        bar = Text()
        bar.append(self._FILL * filled, style=TEAL)
        bar.append(self._DOTS * empty, style=TEAL)
        return bar


def print_error(console: Console, text: str) -> None:
    """Print a red error line: ``{cross} {text}``."""
    txt = Text(f"\u2717 {text}", style=RED)
    console.print(txt)


def print_header(console: Console) -> None:
    """Print the branded ASCII art header."""
    console.print()
    txt = Text(LOGO, style=f"bold {TEAL}")
    console.print(txt)
    console.print("[dim]AI-powered design review for KiCad schematics[/]")
    console.print()


def print_step(console: Console, text: str) -> None:
    """Print a progress step: ``{square} {text}``."""
    txt = Text(f"\u25A0 {text}", style=TEAL)
    console.print(txt)


def print_summary(console: Console, report: ReviewReport) -> None:
    """Print a coloured summary line using the report's severity stats."""
    stats = report.stats
    line = Text("Found ")
    line.append(f"{stats.error} errors", style=f"bold {RED}")
    line.append(", ")
    line.append(f"{stats.warning} warnings", style=f"bold {AMBER}")
    line.append(", ")
    line.append(f"{stats.suggestion} suggestions", style=f"bold {TEAL}")
    console.print(line)


def print_finding_cards(console: Console, report: ReviewReport) -> None:
    """Print styled finding cards grouped by severity."""
    _SEVERITY_ORDER = [Severity.error, Severity.warning, Severity.suggestion]
    _SEVERITY_CFG: dict[Severity, tuple[str, str, str]] = {
        Severity.error:      ("\u2717", "ERROR", RED),
        Severity.warning:    ("\u25B2", "WARN",  AMBER),
        Severity.suggestion: ("\u25C6", "INFO",  TEAL),
    }

    for sev in _SEVERITY_ORDER:
        findings = [f for f in report.findings if f.severity == sev]
        if not findings:
            continue
        for finding in findings:
            icon, label, colour = _SEVERITY_CFG[sev]
            ref = finding.component_ref
            header = Text(f"{icon} {label} {ref}: {finding.title}", style=f"bold {colour}")
            console.print(header)
            # Indented description + recommendation
            console.print(f"  {finding.description}")
            console.print(f"  {finding.recommendation}")
            console.print()  # blank separator
