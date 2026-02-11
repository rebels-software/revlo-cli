"""Async review engine -- sends schematic chunks to Claude for analysis."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging

import anthropic

from revlo.parser.models import ParsedSchematic
from revlo.reviewer.chunker import ReviewChunk, chunk_schematic
from revlo.reviewer.models import Finding, ReviewReport
from revlo.reviewer.prompts import build_review_prompt

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-20250514"
_MAX_TOKENS = 4096


async def _review_chunk(
    client: anthropic.AsyncAnthropic,
    chunk: ReviewChunk,
) -> list[Finding]:
    """Send a single chunk to Claude and parse findings from the response.

    Returns an empty list and logs a warning if the response is malformed.
    """
    prompt = build_review_prompt(chunk)

    try:
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        logger.warning("API call failed for chunk %r, skipping", chunk.label)
        return []

    # Extract text from the response content blocks.
    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text

    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        logger.warning(
            "Malformed JSON response for chunk %r, skipping", chunk.label
        )
        return []

    if not isinstance(raw, list):
        logger.warning(
            "Expected JSON array for chunk %r, got %s, skipping",
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


async def review_schematic(schematic: ParsedSchematic) -> ReviewReport:
    """Review a parsed schematic by sending chunks to Claude concurrently.

    1. Splits the schematic into ReviewChunks via ``chunk_schematic()``.
    2. Builds a prompt for each chunk via ``build_review_prompt()``.
    3. Sends all prompts concurrently to ``claude-sonnet-4-20250514``.
    4. Collects findings and returns a ``ReviewReport``.

    Malformed responses are logged and skipped -- this function never raises
    due to bad LLM output.
    """
    chunks = chunk_schematic(schematic)

    if not chunks:
        return ReviewReport(
            findings=[],
            summary="Found 0 issues (0 errors, 0 warnings, 0 suggestions)",
            schematic_title=schematic.title_block.title,
            review_date=datetime.date.today().isoformat(),
        )

    client = anthropic.AsyncAnthropic()

    tasks = [_review_chunk(client, chunk) for chunk in chunks]
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
