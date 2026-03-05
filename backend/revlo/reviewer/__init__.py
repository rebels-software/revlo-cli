"""Revlo reviewer package for schematic design review."""

from revlo.reviewer.chunker import ReviewChunk, chunk_schematic
from revlo.config import DEFAULT_MODEL, MODEL_OPUS, MODEL_SONNET
from revlo.reviewer.engine import review_schematic
from revlo.reviewer.models import (
    DatasheetEvidence,
    Finding,
    FindingCategory,
    FindingEvidence,
    FindingSourceType,
    ReviewReport,
    Severity,
    SeverityStats,
)
from revlo.reviewer.prompts import build_review_prompt, format_chunk_data
from revlo.reviewer.rules import (
    DeterministicRule,
    DeterministicRuleEngine,
    resolve_deterministic_checks_enabled,
    run_deterministic_checks,
)

__all__ = [
    "DEFAULT_MODEL",
    "DatasheetEvidence",
    "DeterministicRule",
    "DeterministicRuleEngine",
    "Finding",
    "FindingCategory",
    "FindingEvidence",
    "FindingSourceType",
    "MODEL_OPUS",
    "MODEL_SONNET",
    "ReviewChunk",
    "ReviewReport",
    "Severity",
    "SeverityStats",
    "build_review_prompt",
    "format_chunk_data",
    "chunk_schematic",
    "resolve_deterministic_checks_enabled",
    "review_schematic",
    "run_deterministic_checks",
]
