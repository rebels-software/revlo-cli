from __future__ import annotations

from textwrap import dedent

from revlo.config import (
    DEFAULT_REVIEW_PROFILE,
    LLMProvider,
    required_api_key_env,
    resolve_ask_model,
    resolve_datasheet_concurrency,
    resolve_extraction_model,
    resolve_provider,
    resolve_review_profile,
    resolve_review_model,
)


def test_defaults_to_openai_without_config(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REVLO_LLM_PROVIDER", raising=False)

    assert resolve_provider() == LLMProvider.openai
    assert required_api_key_env() == "OPENAI_API_KEY"
    assert resolve_review_model() == "gpt-5.4"
    assert resolve_extraction_model() == "gpt-5.3"
    assert resolve_ask_model() == "gpt-5.4"
    assert resolve_review_profile() == DEFAULT_REVIEW_PROFILE


def test_reads_provider_and_models_from_revlo_toml(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "revlo.toml").write_text(
        dedent(
            """
            [llm]
            provider = "anthropic"
            review_model = "claude-opus-4-6"
            extraction_model = "claude-haiku-4-5-20251001"
            ask_model = "claude-opus-4-6"
            datasheet_concurrency = 2

            [review]
            profile = "sensor-node"
            """
        )
    )

    assert resolve_provider() == LLMProvider.anthropic
    assert required_api_key_env() == "ANTHROPIC_API_KEY"
    assert resolve_review_model() == "claude-opus-4-6"
    assert resolve_extraction_model() == "claude-haiku-4-5-20251001"
    assert resolve_ask_model() == "claude-opus-4-6"
    assert resolve_datasheet_concurrency() == 2
    assert resolve_review_profile() == "sensor-node"


def test_env_overrides_revlo_toml(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "revlo.toml").write_text(
        dedent(
            """
            [llm]
            provider = "anthropic"
            review_model = "claude-opus-4-6"
            """
        )
    )
    monkeypatch.setenv("REVLO_LLM_PROVIDER", "openai")
    monkeypatch.setenv("REVLO_REVIEW_MODEL", "gpt-5.4")
    monkeypatch.setenv("REVLO_REVIEW_PROFILE", "mcu-board")

    assert resolve_provider() == LLMProvider.openai
    assert resolve_review_model() == "gpt-5.4"
    assert resolve_review_profile() == "mcu-board"


def test_invalid_review_profile_raises(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REVLO_REVIEW_PROFILE", "lab-rig")

    try:
        resolve_review_profile()
    except ValueError as exc:
        assert "Unknown review profile" in str(exc)
    else:
        raise AssertionError("Expected invalid review profile to raise ValueError")


def test_builtin_review_profiles_are_valid(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    for profile in ("generic", "mcu-board", "sensor-node", "power-supply"):
        monkeypatch.setenv("REVLO_REVIEW_PROFILE", profile)
        assert resolve_review_profile() == profile
