"""CLI entry point for revlo -- review KiCad schematics with AI."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, TextColumn
from rich.status import Status

from revlo import __version__
from revlo.config import (
    required_api_key_env,
    resolve_review_profile,
    resolve_provider,
    resolve_review_model,
)
from revlo.parser import parse_schematic
from revlo.report import generate_markdown_report
from revlo.reviewer import review_schematic
from revlo.ui import (
    AMBER,
    GRADIENT_LOOP,
    TEAL,
    AnimatedGradient,
    BenDayDotsColumn,
    print_error,
    print_finding_cards,
    print_header,
    print_step,
    print_summary,
)

logger = logging.getLogger(__name__)


def _add_review_args(parser: argparse.ArgumentParser) -> None:
    """Attach shared review-style arguments to a subcommand parser."""
    parser.add_argument(
        "path",
        help="Path to a .kicad_sch file",
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        help="Write report to FILE instead of stdout",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output raw JSON instead of markdown",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model ID override for the configured provider",
    )
    parser.add_argument(
        "--full-review",
        action="store_true",
        dest="full_review",
        help="Enable datasheet enrichment for a slower, deeper review",
    )
    parser.add_argument(
        "--skip-datasheet",
        action="store_true",
        dest="skip_datasheet",
        help="Compatibility alias for fast review without datasheet enrichment",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.5,
        dest="min_confidence",
        help="Minimum confidence threshold for findings (0.0-1.0, default: 0.5)",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="Review profile override (default: generic)",
    )


def _build_parser() -> argparse.ArgumentParser:
    """Build and return the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="revlo",
        description="AI-powered design review for KiCad schematics",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"revlo {__version__}",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed debug output (logging, API calls, timings)",
    )
    subparsers = parser.add_subparsers(dest="command")

    review = subparsers.add_parser(
        "review",
        help="Review a .kicad_sch schematic file",
    )
    _add_review_args(review)
    review.add_argument(
        "--no-tui",
        action="store_true",
        dest="no_tui",
        help="Print styled summary and finding cards to stderr, then exit (no TUI)",
    )

    check = subparsers.add_parser(
        "check",
        help="Run a non-interactive review intended for automation and CI",
        description=(
            "Run Revlo without launching the TUI. Use --json or --output for "
            "machine-readable automation workflows."
        ),
    )
    _add_review_args(check)
    # -- open subcommand: view last stored review --
    open_cmd = subparsers.add_parser(
        "open",
        help="Open the last review for a schematic in the TUI",
    )
    open_cmd.add_argument("path", help="Path to a .kicad_sch file")
    open_cmd.add_argument(
        "--no-tui",
        action="store_true",
        dest="no_tui",
        help="Print finding cards instead of launching TUI",
    )
    open_cmd.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output stored review as JSON",
    )

    # -- history subcommand: browse past reviews/chats --
    history_cmd = subparsers.add_parser(
        "history",
        help="List past reviews and conversations for a schematic",
    )
    history_cmd.add_argument("path", help="Path to a .kicad_sch file")
    history_cmd.add_argument(
        "--load",
        type=int,
        metavar="N",
        default=None,
        help="Load the Nth entry (1 = latest)",
    )
    history_cmd.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output the loaded entry as JSON",
    )
    history_cmd.add_argument(
        "--no-tui",
        action="store_true",
        dest="no_tui",
        help="Print finding cards (review) or conversation (chat) instead of TUI",
    )

    return parser


def _run_review(args: argparse.Namespace) -> None:
    """Execute the review subcommand."""
    path: str = args.path

    # Determine whether to show Rich progress output.
    # Suppress only when --json goes to stdout (no --output), to keep
    # the stream machine-readable.  When --output is set, JSON goes to
    # a file so stderr progress is fine.
    show_rich = not (args.json_output and not args.output)

    # Progress console always writes to stderr so it never pollutes stdout.
    console = Console(stderr=True)

    # Validate file exists
    if not os.path.isfile(path):
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    provider = resolve_provider()
    try:
        review_profile = resolve_review_profile(args.profile)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    api_key_env = required_api_key_env(provider)

    if not os.environ.get(api_key_env):
        print(
            f"Error: {api_key_env} environment variable is not set",
            file=sys.stderr,
        )
        sys.exit(1)

    # -- branded header --
    if show_rich:
        print_header(console)

    # Export netlist for ground-truth connectivity (if kicad-cli available)
    from revlo.parser.netlist import try_export_netlist

    netlist = None
    if show_rich:
        print_step(console, "Exporting netlist...")
    netlist = try_export_netlist(path)
    if show_rich:
        if netlist is not None:
            n_pins = len(netlist.pin_nets)
            print_step(console, f"Netlist: {n_pins} pin connections")
        else:
            console.print(
                f"  [{AMBER}]kicad-cli not found -- using fallback connectivity[/{AMBER}]"
            )

    # Parse schematic
    if show_rich:
        print_step(console, "Parsing schematic...")
    try:
        parsed = parse_schematic(path, netlist=netlist)
    except Exception as exc:
        print(f"Error: failed to parse schematic: {exc}", file=sys.stderr)
        sys.exit(1)

    if show_rich:
        n_comps = len(parsed.components)
        n_nets = len(parsed.nets)
        print_step(console, f"Found {n_comps} components, {n_nets} nets")

    datasheet_enabled = args.full_review and not args.skip_datasheet

    # Datasheet enrichment (full review only)
    datasheet_specs = None
    if datasheet_enabled:
        try:
            from revlo.datasheet.pipeline import enrich_schematic

            cache_dir = Path(path).parent / "datasheets"
            if show_rich:
                ds_counts: dict[str, int] = {
                    "cached": 0, "manual": 0, "fetched": 0, "failed": 0,
                }

                with Progress(
                    TextColumn(f"[{AMBER}]\u25A0 Fetching datasheets..."),
                    BenDayDotsColumn(bar_width=30),
                    TextColumn(f"[{AMBER}]{{task.completed}}/{{task.total}}"),
                    console=console,
                    transient=True,
                ) as progress:
                    task = progress.add_task("fetch", total=0)

                    def _on_progress(completed: int, total: int) -> None:
                        progress.update(task, completed=completed, total=total)

                    def _on_error(ref: str, msg: str) -> None:
                        progress.console.print(
                            f"  [{TEAL}]{ref}[/]: [{AMBER}]{msg}[/]"
                        )

                    def _on_status(ref: str, mpn: str, source: str) -> None:
                        ds_counts[source] = ds_counts.get(source, 0) + 1
                        if source == "cached":
                            progress.console.print(
                                f"  [dim]{ref}: {mpn} (cached)[/]"
                            )
                        elif source == "manual":
                            progress.console.print(
                                f"  [{AMBER}]{ref}: {mpn} (manual PDF)[/]"
                            )
                        elif source == "fetched":
                            progress.console.print(
                                f"  [{AMBER}]{ref}: {mpn} (fetched)[/]"
                            )
                        elif source == "failed":
                            progress.console.print(
                                f"  [{AMBER}]{ref}: Could not fetch datasheet for {mpn}[/]"
                            )

                    datasheet_specs = asyncio.run(
                        enrich_schematic(
                            parsed,
                            cache_dir,
                            provider=provider,
                            progress_callback=_on_progress,
                            error_callback=_on_error,
                            status_callback=_on_status,
                        )
                    )

                # Print summary after progress bar completes.
                parts = []
                for key in ("cached", "manual", "fetched"):
                    if ds_counts[key] > 0:
                        parts.append(f"{ds_counts[key]} {key}")
                failed_count = ds_counts["failed"]
                if failed_count > 0:
                    parts.append(f"[{AMBER}]{failed_count} failed[/]")
                else:
                    parts.append("0 failed")
                summary_text = ", ".join(parts)
                console.print(
                    f"[{AMBER}]\u25A0 Datasheets: {summary_text}[/]"
                )
            else:
                datasheet_specs = asyncio.run(
                    enrich_schematic(parsed, cache_dir, provider=provider)
                )
        except Exception as exc:
            logger.warning(
                "Datasheet enrichment failed, continuing without specs: %s", exc
            )
            if show_rich:
                print_error(console, f"Datasheet enrichment failed: {exc}")

    model = resolve_review_model(provider, override=args.model)

    # Run review
    try:
        if show_rich:
            with Status(
                AnimatedGradient("Running review...", GRADIENT_LOOP, bold=True, speed=0.5),
                console=console,
                spinner="dots",
            ):
                report = asyncio.run(
                    review_schematic(
                        parsed,
                        provider=provider,
                        model=model,
                        datasheet_specs=datasheet_specs,
                        min_confidence=args.min_confidence,
                    )
                )
        else:
            report = asyncio.run(
                review_schematic(
                    parsed,
                    provider=provider,
                    model=model,
                    datasheet_specs=datasheet_specs,
                    min_confidence=args.min_confidence,
                )
            )
    except Exception as exc:
        print(f"Error: review failed: {exc}", file=sys.stderr)
        sys.exit(1)

    # -- summary line --
    if show_rich:
        print_summary(console, report)

    # Persist execution metadata with the saved review.
    report.llm_provider = str(provider)
    report.llm_model = model
    report.datasheet_mode = "full" if datasheet_enabled else "fast"
    report.review_profile = review_profile

    # Auto-save review
    from revlo.storage import save_review

    saved_path = save_review(report, path)
    if show_rich:
        try:
            display_path = saved_path.relative_to(Path(path).parent)
        except ValueError:
            display_path = saved_path
        print_step(console, f"Review saved to {display_path}")

    # -- file / JSON output modes (highest priority) --
    if args.json_output or args.output:
        if args.json_output:
            output = report.model_dump_json(indent=2)
        else:
            output = generate_markdown_report(report)

        if args.output:
            try:
                with open(args.output, "w") as fh:
                    fh.write(output)
            except OSError as exc:
                print(
                    f"Error: could not write to {args.output}: {exc}",
                    file=sys.stderr,
                )
                sys.exit(1)
        else:
            print(output)
        return

    # -- no-tui mode: show finding cards then exit --
    if args.no_tui:
        print_finding_cards(console, report)
        return

    # -- default: launch interactive TUI --
    import time

    time.sleep(1.5)  # Let user read severity summary before TUI takes over.

    if show_rich:
        console.print("[white]Launching review browser...[/]")
        console.print()

    from revlo.tui import RevloApp

    app = RevloApp(
        report,
        path,
        review_path=saved_path,
        parsed_schematic=parsed,
        provider=provider,
    )
    app.run()


def _run_check(args: argparse.Namespace) -> None:
    """Execute the non-interactive check subcommand."""
    args.no_tui = True
    _run_review(args)


def _run_history(args: argparse.Namespace) -> None:
    """Execute the history subcommand."""
    import json as json_mod

    from rich.table import Table
    from rich.text import Text

    from revlo.storage import list_entries, load_entry

    path: str = args.path

    if not os.path.isfile(path):
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    entries = list_entries(path)

    # No --load: list all entries
    if args.load is None:
        console = Console(stderr=True)

        if not entries:
            console.print(
                f"[{AMBER}]No history found for {path}[/{AMBER}]"
            )
            return

        print_header(console)
        print_step(console, f"Review history for {Path(path).name}")
        console.print()

        table = Table(show_header=True, header_style=f"bold {TEAL}", box=None)
        table.add_column("#", style="bold white", width=4)
        table.add_column("Type", width=10)
        table.add_column("Date", width=20)
        table.add_column("Summary")

        for idx, entry in enumerate(entries, 1):
            # Type badge
            if entry.entry_type == "review":
                type_text = Text("review", style=TEAL)
            else:
                type_text = Text("chat", style=AMBER)

            # Timestamp
            saved_at = entry.meta.get("saved_at", "")
            if saved_at:
                try:
                    from datetime import datetime as _dt

                    dt = _dt.fromisoformat(saved_at)
                    date_str = dt.strftime("%Y-%m-%d %H:%M")
                except (ValueError, TypeError):
                    date_str = saved_at[:16]
            else:
                date_str = "unknown"

            table.add_row(str(idx), type_text, date_str, entry.summary)

        console.print(table)
        return

    # --load N: load a specific entry
    n = args.load
    if n < 1 or n > len(entries):
        print(
            f"Error: entry {n} out of range (1-{len(entries)})",
            file=sys.stderr,
        )
        sys.exit(1)

    entry = entries[n - 1]
    data, meta, entry_type = load_entry(entry.path)

    # --json: output raw JSON
    if args.json_output:
        if entry_type == "review":
            print(data.model_dump_json(indent=2))
        else:
            print(json_mod.dumps(data, indent=2))
        return

    # --no-tui: print finding cards (review) or conversation (chat)
    if args.no_tui:
        console = Console(stderr=True)
        print_header(console)
        saved_at = meta.get("saved_at", "unknown")
        print_step(console, f"Loaded {entry_type} from {saved_at}")

        if entry_type == "review":
            print_summary(console, data)
            print_finding_cards(console, data)
        else:
            # Chat: print messages
            messages = data.get("messages", [])
            for msg in messages:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                console.print(f"[bold]{role}:[/] {content}")
        return

    # Default: launch TUI (only for reviews)
    if entry_type == "review":
        console = Console(stderr=True)
        print_header(console)
        saved_at = meta.get("saved_at", "unknown")
        print_step(console, f"Loaded review from {saved_at}")
        print_summary(console, data)

        console.print("[white]Launching review browser...[/]")
        console.print()

        from revlo.tui import RevloApp

        app = RevloApp(data, path, review_path=entry.path, provider=resolve_provider())
        app.run()
    else:
        # Chat entries fall back to --no-tui display
        console = Console(stderr=True)
        print_header(console)
        saved_at = meta.get("saved_at", "unknown")
        print_step(console, f"Loaded chat from {saved_at}")
        messages = data.get("messages", [])
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            console.print(f"[bold]{role}:[/] {content}")


def _run_open(args: argparse.Namespace) -> None:
    """Open the last stored review for a schematic."""
    from revlo.storage import load_latest_review

    path = args.path
    if not os.path.isfile(path):
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    result = load_latest_review(path)
    if result is None:
        print(
            f"No review found for {path}. Run 'revlo review {path}' first.",
            file=sys.stderr,
        )
        sys.exit(1)

    report, meta, review_file = result
    console = Console(stderr=True)

    saved_at = meta.get("saved_at", "unknown")
    print_header(console)
    print_step(console, f"Loaded review from {saved_at}")
    print_summary(console, report)

    if args.json_output:
        print(report.model_dump_json(indent=2))
        return

    if args.no_tui:
        print_finding_cards(console, report)
        return

    from revlo.tui import RevloApp

    app = RevloApp(report, path, review_path=review_file, provider=resolve_provider())
    app.run()


def main() -> None:
    """CLI entry point."""
    try:
        _main_inner()
    except KeyboardInterrupt:
        sys.exit(130)


def _main_inner() -> None:
    """Actual CLI logic, wrapped by :func:`main` for clean Ctrl-C handling."""
    from dotenv import load_dotenv

    load_dotenv()

    parser = _build_parser()
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.ERROR
    logging.basicConfig(
        level=log_level,
        format="%(name)s: %(message)s",
        stream=sys.stderr,
    )
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    if args.command == "review":
        _run_review(args)
    elif args.command == "check":
        _run_check(args)
    elif args.command == "open":
        _run_open(args)
    elif args.command == "history":
        _run_history(args)
    else:
        parser.print_help()
        sys.exit(1)
