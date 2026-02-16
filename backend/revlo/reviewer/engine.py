"""Async review engine -- sends schematic chunks to the EE review agent via direct Claude API."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import re
from typing import Any

from revlo.datasheet.models import DatasheetSpec
from revlo.parser.models import ParsedSchematic
from revlo.config import DEFAULT_MODEL
from revlo.reviewer.chunker import ReviewChunk, chunk_schematic
from revlo.reviewer.models import Finding, ReviewReport
from revlo.reviewer.prompts import build_review_prompt, format_chunk_data
from revlo.skills import load_skill

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON extraction helper
# ---------------------------------------------------------------------------
def _extract_json_from_response(text: str) -> Any:
    """Extract a JSON object or array from an LLM response.

    Handles responses that are:
    - Pure JSON
    - JSON wrapped in markdown code fences (```json ... ```)
    """
    # Try direct parse first.
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code fences.
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Last resort: find the first { or [ and parse from there.
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start_idx = text.find(start_char)
        if start_idx == -1:
            continue
        end_idx = text.rfind(end_char)
        if end_idx == -1 or end_idx <= start_idx:
            continue
        try:
            return json.loads(text[start_idx : end_idx + 1])
        except json.JSONDecodeError:
            continue

    return None


# ---------------------------------------------------------------------------
# EE review agent dispatch (single call with all chunks)
# ---------------------------------------------------------------------------
async def _review_with_ee_agent(
    chunks: list[ReviewChunk],
    system_prompt: str,
    model: str,
) -> list[Finding]:
    """Send all chunks to the EE review agent via direct Claude API call.

    Returns an empty list on any failure (logged as a warning).
    """
    import anthropic

    # Build a single prompt listing all chunks.
    chunk_sections: list[str] = []
    for idx, chunk in enumerate(chunks, start=1):
        chunk_text = format_chunk_data(chunk)
        chunk_sections.append(
            f"## Chunk {idx}: {chunk.label}\n\n{chunk_text}"
        )

    all_chunks_text = "\n\n".join(chunk_sections)
    prompt = (
        f"Review the following schematic with {len(chunks)} chunks:\n\n"
        f"{all_chunks_text}"
    )

    client = anthropic.AsyncAnthropic()

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=8192,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text
        parsed = _extract_json_from_response(text)

        if parsed is None:
            logger.warning(
                "Could not extract JSON from EE agent response (len=%d), skipping. "
                "First 500 chars: %.500s",
                len(text),
                text,
            )
            return []

        # The response may be {"findings": [...]} or just [...]
        if isinstance(parsed, dict):
            raw_findings = parsed.get("findings", [])
        elif isinstance(parsed, list):
            raw_findings = parsed
        else:
            logger.warning(
                "Unexpected JSON type from EE agent: %s",
                type(parsed).__name__,
            )
            return []

        if not isinstance(raw_findings, list):
            logger.warning(
                "Expected findings array from EE agent, got %s",
                type(raw_findings).__name__,
            )
            return []

        findings: list[Finding] = []
        for item in raw_findings:
            try:
                findings.append(Finding.model_validate(item))
            except Exception:
                logger.warning(
                    "Invalid finding from EE agent, skipping: %s",
                    item,
                )
        return findings

    except Exception:
        logger.warning(
            "EE agent API call failed, skipping",
            exc_info=True,
        )
        return []


# ---------------------------------------------------------------------------
# Per-chunk generic fallback
# ---------------------------------------------------------------------------
async def _review_chunk_generic(
    chunk: ReviewChunk,
    model: str,
) -> list[Finding]:
    """Review a single chunk using a focused per-chunk prompt (generic fallback)."""
    import anthropic

    prompt = build_review_prompt(chunk)
    client = anthropic.AsyncAnthropic()

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
        parsed = _extract_json_from_response(text)

        if parsed is None:
            logger.warning(
                "Could not extract JSON from generic review of chunk %r (len=%d). "
                "First 500 chars: %.500s",
                chunk.label,
                len(text),
                text,
            )
            return []

        # Handle both [...] and {"findings": [...]} formats
        if isinstance(parsed, dict):
            raw_findings = parsed.get("findings", [])
        elif isinstance(parsed, list):
            raw_findings = parsed
        else:
            return []

        findings: list[Finding] = []
        for item in raw_findings:
            try:
                findings.append(Finding.model_validate(item))
            except Exception:
                logger.warning("Invalid finding from generic review, skipping: %s", item)
        return findings
    except Exception:
        logger.warning("Generic review API call failed for chunk %r", chunk.label, exc_info=True)
        return []


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
    datasheet_specs: dict[str, DatasheetSpec] | None = None,
    min_confidence: float = 0.5,
) -> ReviewReport:
    """Review a parsed schematic by sending all chunks to the EE review agent.

    1. Splits the schematic into ReviewChunks via ``chunk_schematic()``.
    2. Loads the comprehensive EE system prompt from ``ee_review.md``.
    3. Sends ALL chunks to the EE agent in a single direct Claude API call.
    4. Collects findings, filters by min_confidence, and returns a ReviewReport.

    Args:
        schematic: The parsed schematic to review.
        model: Claude model ID. Defaults to ``DEFAULT_MODEL``.
        datasheet_specs: Optional mapping of component reference to
            :class:`DatasheetSpec`. When provided, matching specs are
            injected into each chunk before prompt generation.
        min_confidence: Minimum confidence threshold (0.0--1.0). Findings
            with ``confidence < min_confidence`` are silently dropped.
            Defaults to ``0.5``.

    Malformed responses are logged and skipped -- this function never raises
    due to bad LLM output.
    """
    chunks = chunk_schematic(schematic)

    # Inject datasheet specs into chunks when available.
    if datasheet_specs:
        for chunk in chunks:
            chunk.datasheet_specs = {
                ref: datasheet_specs[ref]
                for ref in [c.reference for c in chunk.components]
                if ref in datasheet_specs
            }

    if not chunks:
        return ReviewReport(
            findings=[],
            summary="Found 0 issues (0 errors, 0 warnings, 0 suggestions)",
            schematic_title=schematic.title_block.title,
            review_date=datetime.date.today().isoformat(),
            datasheet_specs=datasheet_specs or {},
        )

    # Load the comprehensive EE system prompt.
    ee_prompt = load_skill("ee_review")

    # Dispatch ALL chunks to the EE agent in a single call.
    all_findings = await _review_with_ee_agent(
        chunks, ee_prompt, model or DEFAULT_MODEL
    )

    # Fallback: if EE agent produced no findings, try per-chunk generic review.
    if not all_findings and chunks:
        logger.info(
            "EE agent returned no findings, falling back to per-chunk generic review"
        )
        chunk_results = await asyncio.gather(
            *[_review_chunk_generic(chunk, model or DEFAULT_MODEL) for chunk in chunks]
        )
        for chunk_findings in chunk_results:
            all_findings.extend(chunk_findings)

    # Filter low-confidence findings.
    all_findings = [f for f in all_findings if f.confidence >= min_confidence]

    return ReviewReport(
        findings=all_findings,
        summary=_build_summary(all_findings),
        schematic_title=schematic.title_block.title,
        review_date=datetime.date.today().isoformat(),
        datasheet_specs=datasheet_specs or {},
    )
