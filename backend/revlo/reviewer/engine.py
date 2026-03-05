"""Async review engine -- sends schematic chunks to the EE review agent via direct Claude API."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import re

from revlo.datasheet.models import DatasheetSpec
from revlo.config import DEFAULT_PROVIDER, resolve_review_model
from revlo.constraints import ProjectConstraints
from revlo.llm import generate_text
from revlo.parser.models import ParsedSchematic
from revlo.reviewer.chunker import ReviewChunk, chunk_schematic
from revlo.reviewer.models import Finding, ReviewReport
from revlo.reviewer.prompts import build_review_prompt, format_chunk_data
from revlo.reviewer.rules import run_deterministic_checks
from revlo.skills import load_skill

logger = logging.getLogger(__name__)

_DEFAULT_REVIEW_BATCH_SIZE = 8


def _extract_json_from_response(text: str) -> object | None:
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
    provider: str,
    model: str,
) -> list[Finding]:
    """Send all chunks to the EE review agent via direct Claude API call.

    Returns an empty list on any failure (logged as a warning).
    """
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

    try:
        text = await generate_text(
            provider=provider,
            model=model,
            system_prompt=system_prompt,
            user_prompt=prompt,
            max_output_tokens=8192,
        )
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
    provider: str,
    model: str,
) -> list[Finding]:
    """Review a single chunk using a focused per-chunk prompt (generic fallback)."""
    prompt = build_review_prompt(chunk)

    try:
        text = await generate_text(
            provider=provider,
            model=model,
            user_prompt=prompt,
            max_output_tokens=4096,
        )
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


def _resolve_review_batch_size() -> int:
    """Return the configured review batch size."""
    raw = os.environ.get("REVLO_REVIEW_BATCH_SIZE", str(_DEFAULT_REVIEW_BATCH_SIZE))
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_REVIEW_BATCH_SIZE


def _split_review_batches(
    chunks: list[ReviewChunk],
    batch_size: int,
) -> list[list[ReviewChunk]]:
    """Split review chunks into bounded batches."""
    return [
        chunks[index : index + batch_size]
        for index in range(0, len(chunks), batch_size)
    ]


async def _review_chunk_batch(
    chunks: list[ReviewChunk],
    system_prompt: str,
    provider: str,
    model: str,
    batch_index: int,
    total_batches: int,
) -> list[Finding]:
    """Review one bounded batch, then fall back per chunk when needed."""
    findings = await _review_with_ee_agent(chunks, system_prompt, provider, model)
    if findings:
        return findings

    logger.info(
        "EE agent returned no findings for batch %d/%d, falling back to per-chunk generic review",
        batch_index,
        total_batches,
    )
    chunk_results = await asyncio.gather(
        *[_review_chunk_generic(chunk, provider, model) for chunk in chunks]
    )
    flattened: list[Finding] = []
    for chunk_findings in chunk_results:
        flattened.extend(chunk_findings)
    return flattened


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
    provider: str = DEFAULT_PROVIDER,
    model: str | None = None,
    datasheet_specs: dict[str, DatasheetSpec] | None = None,
    min_confidence: float = 0.5,
    enable_deterministic_checks: bool | None = None,
    project_constraints: ProjectConstraints | None = None,
) -> ReviewReport:
    """Review a parsed schematic by sending all chunks to the EE review agent.

    1. Splits the schematic into ReviewChunks via ``chunk_schematic()``.
    2. Loads the comprehensive EE system prompt from ``ee_review.md``.
    3. Sends ALL chunks to the EE agent in a single direct Claude API call.
    4. Collects findings, filters by min_confidence, and returns a ReviewReport.

    Args:
        schematic: The parsed schematic to review.
        provider: LLM provider to use for the review call.
        model: Provider-specific model ID. Defaults to the configured review model.
        datasheet_specs: Optional mapping of component reference to
            :class:`DatasheetSpec`. When provided, matching specs are
            injected into each chunk before prompt generation.
        min_confidence: Minimum confidence threshold (0.0--1.0). Findings
            with ``confidence < min_confidence`` are silently dropped.
            Defaults to ``0.5``.
        enable_deterministic_checks: Optional override for the deterministic
            rule scaffold. When ``None``, environment-based configuration is used.
        project_constraints: Optional structured project constraints loaded from
            a sidecar JSON file or explicit CLI path. Reserved for future prompt
            builders and deterministic checks.

    Malformed responses are logged and skipped -- this function never raises
    due to bad LLM output.
    """
    resolved_model = resolve_review_model(provider, model)
    chunks = chunk_schematic(schematic)
    deterministic_findings = run_deterministic_checks(
        schematic,
        enabled=enable_deterministic_checks,
    )

    # Inject datasheet specs into chunks when available.
    if datasheet_specs:
        for chunk in chunks:
            chunk.datasheet_specs = {
                ref: datasheet_specs[ref]
                for ref in [c.reference for c in chunk.components]
                if ref in datasheet_specs
            }

    if not chunks:
        deterministic_findings = [
            finding
            for finding in deterministic_findings
            if finding.confidence >= min_confidence
        ]
        return ReviewReport(
            findings=deterministic_findings,
            summary=_build_summary(deterministic_findings),
            schematic_title=schematic.title_block.title,
            review_date=datetime.date.today().isoformat(),
            datasheet_specs=datasheet_specs or {},
        )

    # Load the comprehensive EE system prompt.
    ee_prompt = load_skill("ee_review")

    batch_size = _resolve_review_batch_size()
    chunk_batches = _split_review_batches(chunks, batch_size)
    if len(chunk_batches) > 1:
        logger.info(
            "Reviewing %d chunks across %d bounded batches (batch size %d)",
            len(chunks),
            len(chunk_batches),
            batch_size,
        )

    batch_results = await asyncio.gather(
        *[
            _review_chunk_batch(
                batch,
                ee_prompt,
                str(provider),
                resolved_model,
                batch_index=index,
                total_batches=len(chunk_batches),
            )
            for index, batch in enumerate(chunk_batches, start=1)
        ]
    )
    all_findings = list(deterministic_findings)
    all_findings.extend(finding for batch in batch_results for finding in batch)

    # Filter low-confidence findings.
    all_findings = [f for f in all_findings if f.confidence >= min_confidence]

    return ReviewReport(
        findings=all_findings,
        summary=_build_summary(all_findings),
        schematic_title=schematic.title_block.title,
        review_date=datetime.date.today().isoformat(),
        datasheet_specs=datasheet_specs or {},
    )
