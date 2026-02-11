"""Async review engine -- sends schematic chunks to Claude for analysis."""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
from typing import Any

import anthropic

from revlo.parser.models import ParsedSchematic
from revlo.reviewer.chunker import ReviewChunk, chunk_schematic
from revlo.reviewer.models import Finding, ReviewReport
from revlo.reviewer.prompts import build_review_prompt

logger = logging.getLogger(__name__)

MODEL_SONNET = "claude-sonnet-4-5-20250929"
MODEL_OPUS = "claude-opus-4-6"
DEFAULT_MODEL = MODEL_SONNET

_MAX_TOKENS = 4096

# ---------------------------------------------------------------------------
# Tool-use schema for structured output
# ---------------------------------------------------------------------------
_FINDING_SCHEMA: dict[str, Any] = Finding.model_json_schema()

_FINDINGS_TOOL: dict[str, Any] = {
    "name": "record_findings",
    "description": (
        "Record the list of design-review findings for this schematic chunk. "
        "Pass an empty array if no issues are found."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": _FINDING_SCHEMA,
                "description": "List of review findings (may be empty).",
            },
        },
        "required": ["findings"],
    },
}

_TOOL_CHOICE: dict[str, str] = {"type": "tool", "name": "record_findings"}


async def _review_chunk(
    client: anthropic.AsyncAnthropic,
    chunk: ReviewChunk,
    model: str = DEFAULT_MODEL,
) -> list[Finding]:
    """Send a single chunk to Claude and parse findings from the response.

    Uses tool-use (structured output) to guarantee a well-formed JSON
    response.  Returns an empty list and logs a warning if the response
    cannot be parsed.
    """
    prompt = build_review_prompt(chunk)

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
            tools=[_FINDINGS_TOOL],
            tool_choice=_TOOL_CHOICE,
        )
    except Exception:
        logger.warning("API call failed for chunk %r, skipping", chunk.label)
        return []

    # Extract the tool_use block from the response.
    tool_input: dict[str, Any] | None = None
    for block in response.content:
        if getattr(block, "type", None) == "tool_use":
            tool_input = block.input
            break

    if tool_input is None:
        logger.warning(
            "No tool_use block in response for chunk %r, skipping",
            chunk.label,
        )
        return []

    raw = tool_input.get("findings")
    if not isinstance(raw, list):
        logger.warning(
            "Expected findings array for chunk %r, got %s, skipping",
            chunk.label,
            type(raw).__name__,
        )
        return []

    findings: list[Finding] = []
    for item in raw:
        try:
            findings.append(Finding.model_validate(item))
        except Exception:
            logger.warning(
                "Invalid finding in chunk %r, skipping item: %s",
                chunk.label,
                item,
            )
    return findings


def _build_summary(findings: list[Finding]) -> str:
    """Build a human-readable summary string from a list of findings."""
    errors = sum(1 for f in findings if f.severity == "error")
    warnings = sum(1 for f in findings if f.severity == "warning")
    suggestions = sum(1 for f in findings if f.severity == "suggestion")
    total = len(findings)
    return (
        f"Found {total} issues "
        f"({errors} errors, {warnings} warnings, {suggestions} suggestions)"
    )


async def review_schematic(
    schematic: ParsedSchematic,
    model: str | None = None,
) -> ReviewReport:
    """Review a parsed schematic by sending chunks to Claude concurrently.

    1. Splits the schematic into ReviewChunks via ``chunk_schematic()``.
    2. Builds a prompt for each chunk via ``build_review_prompt()``.
    3. Sends all prompts concurrently to the chosen Claude model.
    4. Collects findings and returns a ``ReviewReport``.

    Args:
        schematic: The parsed schematic to review.
        model: Claude model ID to use. If *None*, reads from the
            ``REVLO_MODEL`` environment variable, defaulting to
            :data:`DEFAULT_MODEL` (Sonnet).

    Malformed responses are logged and skipped -- this function never raises
    due to bad LLM output.
    """
    resolved_model = model or os.environ.get("REVLO_MODEL", DEFAULT_MODEL)

    chunks = chunk_schematic(schematic)

    if not chunks:
        return ReviewReport(
            findings=[],
            summary="Found 0 issues (0 errors, 0 warnings, 0 suggestions)",
            schematic_title=schematic.title_block.title,
            review_date=datetime.date.today().isoformat(),
        )

    client = anthropic.AsyncAnthropic()

    tasks = [_review_chunk(client, chunk, model=resolved_model) for chunk in chunks]
    results = await asyncio.gather(*tasks)

    all_findings: list[Finding] = []
    for chunk_findings in results:
        all_findings.extend(chunk_findings)

    return ReviewReport(
        findings=all_findings,
        summary=_build_summary(all_findings),
        schematic_title=schematic.title_block.title,
        review_date=datetime.date.today().isoformat(),
    )
