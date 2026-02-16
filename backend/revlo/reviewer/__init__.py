"""Revlo reviewer package for schematic design review."""

from revlo.reviewer.chunker import ReviewChunk, chunk_schematic
from revlo.config import DEFAULT_MODEL, MODEL_OPUS, MODEL_SONNET
from revlo.reviewer.engine import review_schematic
from revlo.reviewer.models import (
    Finding,
    FindingCategory,
    ReviewReport,
    Severity,
    SeverityStats,
)
from revlo.reviewer.prompts import build_review_prompt, format_chunk_data

__all__ = [
    "DEFAULT_MODEL",
    "Finding",
    "FindingCategory",
    "MODEL_OPUS",
    "MODEL_SONNET",
    "ReviewChunk",
    "ReviewReport",
    "Severity",
    "SeverityStats",
    "build_review_prompt",
    "format_chunk_data",
    "chunk_schematic",
    "review_schematic",
]
