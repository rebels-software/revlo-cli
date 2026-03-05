"""Shared configuration constants for the Revlo project."""

from __future__ import annotations

import logging
import os
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


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
DEFAULT_REVIEW_PROFILE = "generic"
_VALID_REVIEW_PROFILES = {DEFAULT_REVIEW_PROFILE}


def _resolve_config_path() -> Path | None:
    """Locate the active ``revlo.toml`` config file, if any."""
    override = os.environ.get("REVLO_CONFIG")
    if override:
        path = Path(override).expanduser()
        return path if path.exists() else None

    cwd = Path.cwd().resolve()
    candidates = [cwd, *cwd.parents]
    for directory in candidates:
        path = directory / "revlo.toml"
        if path.exists():
            return path
    return None


def _load_toml_config() -> dict[str, Any]:
    """Load ``revlo.toml`` if present, otherwise return an empty config."""
    path = _resolve_config_path()
    if path is None:
        return {}

    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        logger.warning("Failed to load config from %s", path, exc_info=True)
        return {}

    return data if isinstance(data, dict) else {}


def _llm_config() -> dict[str, Any]:
    """Return the ``[llm]`` table from ``revlo.toml`` if present."""
    data = _load_toml_config().get("llm", {})
    return data if isinstance(data, dict) else {}


def _review_config() -> dict[str, Any]:
    """Return the ``[review]`` table from ``revlo.toml`` if present."""
    data = _load_toml_config().get("review", {})
    return data if isinstance(data, dict) else {}


def resolve_provider(provider: str | LLMProvider | None = None) -> LLMProvider:
    """Resolve the active LLM provider from override, env, config, or default."""
    raw = (
        provider
        or os.environ.get("REVLO_LLM_PROVIDER")
        or _llm_config().get("provider")
        or DEFAULT_PROVIDER.value
    )
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

    The public config surface is provider-agnostic via ``REVLO_REVIEW_MODEL``
    or ``revlo.toml``.
    Provider-specific env vars remain as internal escape hatches.
    """
    if override:
        return override

    resolved = resolve_provider(provider)
    config_value = _llm_config().get("review_model")
    generic = os.environ.get("REVLO_REVIEW_MODEL")
    if generic:
        return generic
    env_key = (
        "REVLO_OPENAI_REVIEW_MODEL"
        if resolved == LLMProvider.openai
        else "REVLO_ANTHROPIC_REVIEW_MODEL"
    )
    fallback = (
        config_value
        if isinstance(config_value, str) and config_value.strip()
        else DEFAULT_OPENAI_REVIEW_MODEL
        if resolved == LLMProvider.openai
        else DEFAULT_ANTHROPIC_REVIEW_MODEL
    )
    return os.environ.get(
        env_key,
        fallback,
    )


def resolve_extraction_model(
    provider: str | LLMProvider | None = None,
    override: str | None = None,
) -> str:
    """Resolve the datasheet extraction model.

    The public config surface is provider-agnostic via
    ``REVLO_EXTRACTION_MODEL`` or ``revlo.toml``.
    Provider-specific env vars remain as internal escape hatches.
    """
    if override:
        return override

    resolved = resolve_provider(provider)
    config_value = _llm_config().get("extraction_model")
    generic = os.environ.get("REVLO_EXTRACTION_MODEL")
    if generic:
        return generic
    env_key = (
        "REVLO_OPENAI_EXTRACTION_MODEL"
        if resolved == LLMProvider.openai
        else "REVLO_ANTHROPIC_EXTRACTION_MODEL"
    )
    fallback = (
        config_value
        if isinstance(config_value, str) and config_value.strip()
        else DEFAULT_OPENAI_EXTRACTION_MODEL
        if resolved == LLMProvider.openai
        else DEFAULT_ANTHROPIC_EXTRACTION_MODEL
    )
    return os.environ.get(
        env_key,
        fallback,
    )


def resolve_ask_model(
    provider: str | LLMProvider | None = None,
    override: str | None = None,
) -> str:
    """Resolve the Ask Mode model.

    The public config surface is provider-agnostic via ``REVLO_ASK_MODEL``
    or ``revlo.toml``.
    Provider-specific env vars remain as internal escape hatches.
    """
    if override:
        return override

    resolved = resolve_provider(provider)
    config_value = _llm_config().get("ask_model")
    generic = os.environ.get("REVLO_ASK_MODEL")
    if generic:
        return generic
    env_key = (
        "REVLO_OPENAI_ASK_MODEL"
        if resolved == LLMProvider.openai
        else "REVLO_ANTHROPIC_ASK_MODEL"
    )
    fallback = (
        config_value
        if isinstance(config_value, str) and config_value.strip()
        else DEFAULT_OPENAI_ASK_MODEL
        if resolved == LLMProvider.openai
        else DEFAULT_ANTHROPIC_ASK_MODEL
    )
    return os.environ.get(
        env_key,
        fallback,
    )


def resolve_datasheet_concurrency() -> int:
    """Return the configured datasheet enrichment concurrency."""
    raw = os.environ.get(
        "REVLO_DATASHEET_CONCURRENCY",
        str(_llm_config().get("datasheet_concurrency", DEFAULT_DATASHEET_CONCURRENCY)),
    )
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_DATASHEET_CONCURRENCY


def resolve_review_profile(override: str | None = None) -> str:
    """Resolve the active review profile from override, env, config, or default."""
    raw = (
        override
        or os.environ.get("REVLO_REVIEW_PROFILE")
        or _review_config().get("profile")
        or DEFAULT_REVIEW_PROFILE
    )
    value = str(raw).strip().lower()
    if value not in _VALID_REVIEW_PROFILES:
        valid = ", ".join(sorted(_VALID_REVIEW_PROFILES))
        raise ValueError(
            f"Unknown review profile '{value}'. Valid profiles: {valid}"
        )
    return value
