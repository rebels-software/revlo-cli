"""CLI entry point for revlo -- review KiCad schematics with AI."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from revlo.parser import parse_schematic
from revlo.report import generate_markdown_report
from revlo.reviewer import MODEL_OPUS, MODEL_SONNET, review_schematic

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    """Build and return the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="revlo",
        description="AI-powered design review for KiCad schematics",
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

    return parser


def _run_review(args: argparse.Namespace) -> None:
    """Execute the review subcommand."""
    path: str = args.path

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

    # Parse schematic
    try:
        parsed = parse_schematic(path)
    except Exception as exc:
        print(f"Error: failed to parse schematic: {exc}", file=sys.stderr)
        sys.exit(1)

    # Datasheet enrichment (unless --skip-datasheet)
    datasheet_specs = None
    if not args.skip_datasheet:
        try:
            from revlo.datasheet.pipeline import enrich_schematic

            cache_dir = Path(path).parent / "datasheets"
            datasheet_specs = asyncio.run(enrich_schematic(parsed, cache_dir))
        except Exception as exc:
            logger.warning("Datasheet enrichment failed, continuing without specs: %s", exc)

    # Resolve model choice
    _model_map = {"sonnet": MODEL_SONNET, "opus": MODEL_OPUS}
    model: str | None = _model_map[args.model] if args.model else None

    # Run review
    try:
        report = asyncio.run(
            review_schematic(parsed, model=model, datasheet_specs=datasheet_specs)
        )
    except Exception as exc:
        print(f"Error: review failed: {exc}", file=sys.stderr)
        sys.exit(1)

    # Format output
    if args.json_output:
        output = report.model_dump_json(indent=2)
    else:
        output = generate_markdown_report(report)

    # Write output
    if args.output:
        try:
            with open(args.output, "w") as fh:
                fh.write(output)
        except OSError as exc:
            print(f"Error: could not write to {args.output}: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        print(output)


def main() -> None:
    """CLI entry point."""
    from dotenv import load_dotenv

    load_dotenv()

    logging.basicConfig()

    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "review":
        _run_review(args)
    else:
        parser.print_help()
        sys.exit(1)
