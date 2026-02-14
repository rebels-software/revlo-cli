"""Async review engine -- sends schematic chunks to the Team Lead agent for analysis."""

from __future__ import annotations

import asyncio
import datetime
import logging
from typing import Any

from revlo.datasheet.models import DatasheetSpec
from revlo.parser.models import ParsedSchematic
from revlo.reviewer.chunker import ReviewChunk, chunk_schematic
from revlo.reviewer.models import Finding, ReviewReport
from revlo.reviewer.prompts import format_chunk_data

logger = logging.getLogger(__name__)

MODEL_SONNET = "claude-sonnet-4-5-20250929"
MODEL_OPUS = "claude-opus-4-6"
DEFAULT_MODEL = MODEL_OPUS

# ---------------------------------------------------------------------------
# Output format schema for Agent SDK structured output
# ---------------------------------------------------------------------------
_FINDING_SCHEMA: dict[str, Any] = Finding.model_json_schema()

_AGENT_OUTPUT_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": _FINDING_SCHEMA,
            },
        },
        "required": ["findings"],
    },
}


# ---------------------------------------------------------------------------
# Team Lead agent dispatch
# ---------------------------------------------------------------------------
async def _review_chunk_with_team(
    chunk: ReviewChunk,
    orchestrator_prompt: str,
    agent_definitions: dict[str, Any],
) -> list[Finding]:
    """Dispatch a chunk to the Team Lead agent who delegates to specialists.

    Imports ``claude_agent_sdk`` lazily so that the module can be loaded even
    when the Claude Code CLI is not installed.

    Returns an empty list on any failure (logged as a warning).
    """
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    chunk_text = format_chunk_data(chunk)
    prompt = f"Review the following schematic chunk ({chunk.label}):\n\n{chunk_text}"

    options = ClaudeAgentOptions(
        system_prompt=orchestrator_prompt,
        agents=agent_definitions,
        output_format=_AGENT_OUTPUT_FORMAT,
        max_turns=10,
        permission_mode="bypassPermissions",
    )

    try:
        result_msg = None
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, ResultMessage):
                result_msg = msg
                break

        if result_msg is None:
            logger.warning(
                "No ResultMessage from Team Lead for chunk %r, skipping",
                chunk.label,
            )
            return []

        if result_msg.is_error:
            logger.warning(
                "Team Lead returned error for chunk %r, skipping",
                chunk.label,
            )
            return []

        structured = result_msg.structured_output
        if structured is None:
            logger.warning(
                "No structured output from Team Lead for chunk %r, skipping",
                chunk.label,
            )
            return []

        raw_findings = structured.get("findings", []) if isinstance(structured, dict) else []
        if not isinstance(raw_findings, list):
            logger.warning(
                "Expected findings array from Team Lead for chunk %r, got %s",
                chunk.label,
                type(raw_findings).__name__,
            )
            return []

        findings: list[Finding] = []
        for item in raw_findings:
            try:
                findings.append(Finding.model_validate(item))
            except Exception:
                logger.warning(
                    "Invalid finding from Team Lead for chunk %r, skipping: %s",
                    chunk.label,
                    item,
                )
        return findings

    except Exception:
        logger.warning(
            "Agent SDK call failed for chunk %r, skipping",
            chunk.label,
            exc_info=True,
        )
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
    """Review a parsed schematic by dispatching chunks to the Team Lead agent.

    1. Splits the schematic into ReviewChunks via ``chunk_schematic()``.
    2. Loads the Team Lead orchestrator prompt and specialist definitions.
    3. For each chunk, the Team Lead agent delegates to specialists and
       returns deduplicated findings.
    4. Collects findings, filters by min_confidence, and returns a ReviewReport.

    Args:
        schematic: The parsed schematic to review.
        model: Claude model ID (currently unused -- model selection is
            handled by agent definitions).
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
        )

    # Load orchestrator prompt and agent definitions once.
    from revlo.agents.definitions import (
        get_all_agent_definitions,
        get_orchestrator_prompt,
    )

    orchestrator_prompt = get_orchestrator_prompt()
    agent_defs = get_all_agent_definitions()

    # Dispatch all chunks to the Team Lead concurrently.
    tasks = [
        asyncio.ensure_future(
            _review_chunk_with_team(chunk, orchestrator_prompt, agent_defs)
        )
        for chunk in chunks
    ]

    results = await asyncio.gather(*tasks)

    all_findings: list[Finding] = []
    for chunk_findings in results:
        all_findings.extend(chunk_findings)

    # Filter low-confidence findings.
    all_findings = [f for f in all_findings if f.confidence >= min_confidence]

    return ReviewReport(
        findings=all_findings,
        summary=_build_summary(all_findings),
        schematic_title=schematic.title_block.title,
        review_date=datetime.date.today().isoformat(),
    )
