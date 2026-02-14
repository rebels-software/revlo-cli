"""Async review engine -- sends schematic chunks to Claude for analysis."""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
from typing import Any

import anthropic

from revlo.datasheet.models import DatasheetSpec
from revlo.parser.models import ParsedSchematic
from revlo.reviewer.chunker import ReviewChunk, chunk_schematic
from revlo.reviewer.models import Finding, ReviewReport
from revlo.reviewer.prompts import build_review_prompt, format_chunk_data

logger = logging.getLogger(__name__)

MODEL_SONNET = "claude-sonnet-4-5-20250929"
MODEL_OPUS = "claude-opus-4-6"
DEFAULT_MODEL = MODEL_OPUS

_MAX_TOKENS = 4096

# ---------------------------------------------------------------------------
# Severity ranking for dedup tie-breaking
# ---------------------------------------------------------------------------
_SEVERITY_RANK: dict[str, int] = {
    "error": 3,
    "warning": 2,
    "suggestion": 1,
}

# ---------------------------------------------------------------------------
# Tool-use schema for structured output (direct Anthropic API path)
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


# ---------------------------------------------------------------------------
# Output format schema for Agent SDK structured output
# ---------------------------------------------------------------------------
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
            temperature=0,
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


# ---------------------------------------------------------------------------
# Agent SDK dispatch
# ---------------------------------------------------------------------------
async def _review_chunk_with_agent(
    agent_name: str,
    chunk: ReviewChunk,
    agent_definitions: dict[str, Any],
) -> list[Finding]:
    """Dispatch a single chunk to a specialist agent via the Claude Agent SDK.

    Imports ``claude_agent_sdk`` lazily so that the module can be loaded even
    when the Claude Code CLI is not installed.

    Returns an empty list on any failure (logged as a warning).
    """
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    agent_def = agent_definitions[agent_name]
    chunk_text = format_chunk_data(chunk)

    prompt = f"Review the following schematic chunk ({chunk.label}):\n\n{chunk_text}"

    options = ClaudeAgentOptions(
        system_prompt=agent_def.prompt,
        output_format=_AGENT_OUTPUT_FORMAT,
        max_turns=1,
        permission_mode="default",
    )

    try:
        result_msg = None
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, ResultMessage):
                result_msg = msg
                break

        if result_msg is None:
            logger.warning(
                "No ResultMessage from agent %r for chunk %r, skipping",
                agent_name,
                chunk.label,
            )
            return []

        if result_msg.is_error:
            logger.warning(
                "Agent %r returned error for chunk %r, skipping",
                agent_name,
                chunk.label,
            )
            return []

        structured = result_msg.structured_output
        if structured is None:
            logger.warning(
                "No structured output from agent %r for chunk %r, skipping",
                agent_name,
                chunk.label,
            )
            return []

        raw_findings = structured.get("findings", []) if isinstance(structured, dict) else []
        if not isinstance(raw_findings, list):
            logger.warning(
                "Expected findings array from agent %r for chunk %r, got %s",
                agent_name,
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
                    "Invalid finding from agent %r for chunk %r, skipping: %s",
                    agent_name,
                    chunk.label,
                    item,
                )
        return findings

    except Exception:
        logger.warning(
            "Agent SDK call failed for agent %r, chunk %r, skipping",
            agent_name,
            chunk.label,
            exc_info=True,
        )
        return []


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------
def _deduplicate_findings(findings: list[Finding]) -> list[Finding]:
    """Deduplicate and sort findings per orchestrator.md rules.

    - Group by (component_ref, category).
    - When duplicates: keep highest confidence.
    - If tied confidence: keep highest severity (error > warning > suggestion).
    - Sort: severity desc, then component_ref asc.
    """
    groups: dict[tuple[str, str], list[Finding]] = {}
    for f in findings:
        key = (f.component_ref, f.category)
        groups.setdefault(key, []).append(f)

    deduped: list[Finding] = []
    for group in groups.values():
        if len(group) == 1:
            deduped.append(group[0])
        else:
            # Sort by confidence desc, then severity desc to pick the best.
            best = max(
                group,
                key=lambda f: (f.confidence, _SEVERITY_RANK.get(f.severity, 0)),
            )
            deduped.append(best)

    # Sort: severity desc (error=3, warning=2, suggestion=1), then ref asc.
    deduped.sort(
        key=lambda f: (-_SEVERITY_RANK.get(f.severity, 0), f.component_ref),
    )
    return deduped


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
    use_agents: bool = True,
) -> ReviewReport:
    """Review a parsed schematic by sending chunks to Claude concurrently.

    1. Splits the schematic into ReviewChunks via ``chunk_schematic()``.
    2. Builds a prompt for each chunk via ``build_review_prompt()``.
    3. Sends all prompts concurrently to the chosen Claude model.
    4. Collects findings and returns a ``ReviewReport``.
    5. Filters out findings below *min_confidence*.

    Args:
        schematic: The parsed schematic to review.
        model: Claude model ID to use. If *None*, reads from the
            ``REVLO_MODEL`` environment variable, defaulting to
            :data:`DEFAULT_MODEL`.
        datasheet_specs: Optional mapping of component reference to
            :class:`DatasheetSpec`. When provided, matching specs are
            injected into each chunk before prompt generation.
        min_confidence: Minimum confidence threshold (0.0--1.0). Findings
            with ``confidence < min_confidence`` are silently dropped.
            Defaults to ``0.5``.
        use_agents: When *True* (default), dispatch chunks to specialist
            agents via the Claude Agent SDK. Falls back to direct Anthropic
            API calls if the SDK is unavailable or raises an error.
            When *False*, always uses the direct Anthropic API path.

    Malformed responses are logged and skipped -- this function never raises
    due to bad LLM output.
    """
    resolved_model = model or os.environ.get("REVLO_MODEL", DEFAULT_MODEL)

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

    # -------------------------------------------------------------------
    # Agent SDK dispatch path
    # -------------------------------------------------------------------
    if use_agents:
        try:
            from revlo.agents.definitions import (
                get_agents_for_chunk,
                get_all_agent_definitions,
            )

            agent_defs = get_all_agent_definitions()

            tasks: list[asyncio.Task[list[Finding]]] = []
            for chunk in chunks:
                agent_names = get_agents_for_chunk(chunk)
                for agent_name in agent_names:
                    tasks.append(
                        asyncio.ensure_future(
                            _review_chunk_with_agent(agent_name, chunk, agent_defs)
                        )
                    )

            if tasks:
                results = await asyncio.gather(*tasks)
                all_findings: list[Finding] = []
                for chunk_findings in results:
                    all_findings.extend(chunk_findings)

                # Filter low-confidence, then dedup.
                all_findings = [f for f in all_findings if f.confidence >= min_confidence]
                all_findings = _deduplicate_findings(all_findings)

                return ReviewReport(
                    findings=all_findings,
                    summary=_build_summary(all_findings),
                    schematic_title=schematic.title_block.title,
                    review_date=datetime.date.today().isoformat(),
                )

        except Exception:
            logger.warning(
                "Agent SDK dispatch failed, falling back to direct API",
                exc_info=True,
            )
            # Fall through to direct API path below.

    # -------------------------------------------------------------------
    # Direct Anthropic API path (fallback or when use_agents=False)
    # -------------------------------------------------------------------
    client = anthropic.AsyncAnthropic()

    direct_tasks = [_review_chunk(client, chunk, model=resolved_model) for chunk in chunks]
    results = await asyncio.gather(*direct_tasks)

    all_findings_direct: list[Finding] = []
    for chunk_findings in results:
        all_findings_direct.extend(chunk_findings)

    # Filter out low-confidence findings.
    all_findings_direct = [f for f in all_findings_direct if f.confidence >= min_confidence]

    return ReviewReport(
        findings=all_findings_direct,
        summary=_build_summary(all_findings_direct),
        schematic_title=schematic.title_block.title,
        review_date=datetime.date.today().isoformat(),
    )
