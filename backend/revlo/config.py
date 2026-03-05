"""Shared configuration constants for the Revlo project."""

from __future__ import annotations

import os
from enum import StrEnum


class LLMProvider(StrEnum):
    openai = "openai"
    anthropic = "anthropic"


# Anthropic model IDs
MODEL_OPUS = "claude-opus-4-6"
MODEL_SONNET = "claude-sonnet-4-5-20250929"
MODEL_HAIKU = "claude-haiku-4-5-20251001"

# OpenAI model IDs
MODEL_GPT54 = "gpt-5.4"
MODEL_GPT53 = "gpt-5.3"

# Global review default. Kept as a simple string for backward compatibility.
DEFAULT_MODEL = MODEL_GPT54
DEFAULT_PROVIDER = LLMProvider.openai

# Provider-specific defaults
DEFAULT_OPENAI_REVIEW_MODEL = MODEL_GPT54
DEFAULT_OPENAI_EXTRACTION_MODEL = MODEL_GPT53
DEFAULT_OPENAI_ASK_MODEL = MODEL_GPT54

DEFAULT_ANTHROPIC_REVIEW_MODEL = MODEL_OPUS
DEFAULT_ANTHROPIC_EXTRACTION_MODEL = MODEL_HAIKU
DEFAULT_ANTHROPIC_ASK_MODEL = MODEL_OPUS

DEFAULT_DATASHEET_CONCURRENCY = 4


def resolve_provider(provider: str | LLMProvider | None = None) -> LLMProvider:
    """Resolve the active LLM provider from an override or environment."""
    raw = provider or os.environ.get("REVLO_LLM_PROVIDER", DEFAULT_PROVIDER.value)
    if isinstance(raw, LLMProvider):
        return raw
    return LLMProvider(raw.strip().lower())


def required_api_key_env(provider: str | LLMProvider | None = None) -> str:
    """Return the API key env var required for the selected provider."""
    resolved = resolve_provider(provider)
    if resolved == LLMProvider.openai:
        return "OPENAI_API_KEY"
    return "ANTHROPIC_API_KEY"


def resolve_review_model(
    provider: str | LLMProvider | None = None,
    override: str | None = None,
) -> str:
    """Resolve the review model.

    The public config surface is OpenAI-first via ``REVLO_REVIEW_MODEL``.
    Provider-specific env vars remain as internal escape hatches.
    """
    if override:
        return override

    resolved = resolve_provider(provider)
    generic = os.environ.get("REVLO_REVIEW_MODEL")
    if generic and resolved == LLMProvider.openai:
        return generic
    env_key = (
        "REVLO_OPENAI_REVIEW_MODEL"
        if resolved == LLMProvider.openai
        else "REVLO_ANTHROPIC_REVIEW_MODEL"
    )
    return os.environ.get(
        env_key,
        DEFAULT_OPENAI_REVIEW_MODEL
        if resolved == LLMProvider.openai
        else DEFAULT_ANTHROPIC_REVIEW_MODEL,
    )


def resolve_extraction_model(
    provider: str | LLMProvider | None = None,
    override: str | None = None,
) -> str:
    """Resolve the datasheet extraction model.

    The public config surface is OpenAI-first via ``REVLO_EXTRACTION_MODEL``.
    Provider-specific env vars remain as internal escape hatches.
    """
    if override:
        return override

    resolved = resolve_provider(provider)
    generic = os.environ.get("REVLO_EXTRACTION_MODEL")
    if generic and resolved == LLMProvider.openai:
        return generic
    env_key = (
        "REVLO_OPENAI_EXTRACTION_MODEL"
        if resolved == LLMProvider.openai
        else "REVLO_ANTHROPIC_EXTRACTION_MODEL"
    )
    return os.environ.get(
        env_key,
        DEFAULT_OPENAI_EXTRACTION_MODEL
        if resolved == LLMProvider.openai
        else DEFAULT_ANTHROPIC_EXTRACTION_MODEL,
    )


def resolve_ask_model(
    provider: str | LLMProvider | None = None,
    override: str | None = None,
) -> str:
    """Resolve the Ask Mode model.

    The public config surface is OpenAI-first via ``REVLO_ASK_MODEL``.
    Provider-specific env vars remain as internal escape hatches.
    """
    if override:
        return override

    resolved = resolve_provider(provider)
    generic = os.environ.get("REVLO_ASK_MODEL")
    if generic and resolved == LLMProvider.openai:
        return generic
    env_key = (
        "REVLO_OPENAI_ASK_MODEL"
        if resolved == LLMProvider.openai
        else "REVLO_ANTHROPIC_ASK_MODEL"
    )
    return os.environ.get(
        env_key,
        DEFAULT_OPENAI_ASK_MODEL
        if resolved == LLMProvider.openai
        else DEFAULT_ANTHROPIC_ASK_MODEL,
    )


def resolve_datasheet_concurrency() -> int:
    """Return the configured datasheet enrichment concurrency."""
    raw = os.environ.get("REVLO_DATASHEET_CONCURRENCY", str(DEFAULT_DATASHEET_CONCURRENCY))
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_DATASHEET_CONCURRENCY
