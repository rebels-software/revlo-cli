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

from revlo.parser import parse_schematic
from revlo.report import generate_markdown_report
from revlo.reviewer import MODEL_OPUS, MODEL_SONNET, review_schematic
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


def _build_parser() -> argparse.ArgumentParser:
    """Build and return the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="revlo",
        description="AI-powered design review for KiCad schematics",
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
    review.add_argument(
        "path",
        help="Path to a .kicad_sch file",
    )
    review.add_argument(
        "--output",
        metavar="FILE",
        help="Write report to FILE instead of stdout",
    )
    review.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output raw JSON instead of markdown",
    )
    review.add_argument(
        "--model",
        choices=["sonnet", "opus"],
        default=None,
        help="Claude model to use for review (default: sonnet via env/fallback)",
    )
    review.add_argument(
        "--skip-datasheet",
        action="store_true",
        dest="skip_datasheet",
        help="Skip datasheet enrichment and run basic review only",
    )
    review.add_argument(
        "--min-confidence",
        type=float,
        default=0.5,
        dest="min_confidence",
        help="Minimum confidence threshold for findings (0.0-1.0, default: 0.5)",
    )
    review.add_argument(
        "--no-tui",
        action="store_true",
        dest="no_tui",
        help="Print styled summary and finding cards to stderr, then exit (no TUI)",
    )
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

    # Validate API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "Error: ANTHROPIC_API_KEY environment variable is not set",
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

    # Datasheet enrichment (unless --skip-datasheet)
    datasheet_specs = None
    if not args.skip_datasheet:
        try:
            from revlo.datasheet.pipeline import enrich_schematic

            cache_dir = Path(path).parent / "datasheets"
            if show_rich:
                ds_counts: dict[str, int] = {
                    "cached": 0, "manual": 0, "fetched": 0, "failed": 0,
                }

                with Progress(
                    TextColumn(f"[{TEAL}]\u25A0 Fetching datasheets..."),
                    BenDayDotsColumn(bar_width=30),
                    TextColumn(f"[{TEAL}]{{task.completed}}/{{task.total}}"),
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
                                f"  [{TEAL}]{ref}: {mpn} (manual PDF)[/]"
                            )
                        elif source == "fetched":
                            progress.console.print(
                                f"  [{TEAL}]{ref}: {mpn} (fetched)[/]"
                            )
                        elif source == "failed":
                            progress.console.print(
                                f"  [{AMBER}]{ref}: Could not fetch datasheet for {mpn}[/]"
                            )

                    datasheet_specs = asyncio.run(
                        enrich_schematic(
                            parsed,
                            cache_dir,
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
                    f"[{TEAL}]\u25A0 Datasheets: {summary_text}[/]"
                )
            else:
                datasheet_specs = asyncio.run(
                    enrich_schematic(parsed, cache_dir)
                )
        except Exception as exc:
            logger.warning(
                "Datasheet enrichment failed, continuing without specs: %s", exc
            )
            if show_rich:
                print_error(console, f"Datasheet enrichment failed: {exc}")

    # Resolve model choice
    _model_map = {"sonnet": MODEL_SONNET, "opus": MODEL_OPUS}
    model: str | None = _model_map[args.model] if args.model else None

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
                        model=model,
                        datasheet_specs=datasheet_specs,
                        min_confidence=args.min_confidence,
                    )
                )
        else:
            report = asyncio.run(
                review_schematic(
                    parsed,
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

    app = RevloApp(report, path)
    app.run()


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

    report, meta = result
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

    app = RevloApp(report, path)
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
    if args.command == "review":
        _run_review(args)
    elif args.command == "open":
        _run_open(args)
    else:
        parser.print_help()
        sys.exit(1)
