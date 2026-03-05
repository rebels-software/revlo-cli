"""Provider-agnostic LLM helpers for Revlo."""

from __future__ import annotations

import json
import logging
from typing import TypeVar

from pydantic import BaseModel

from revlo.config import LLMProvider, resolve_provider

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def _extract_openai_text(response: object) -> str:
    """Extract text content from an OpenAI responses API object."""
    text = getattr(response, "output_text", "")
    if text:
        return text

    parts: list[str] = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) != "message":
            continue
        for content in getattr(item, "content", []) or []:
            content_type = getattr(content, "type", None)
            if content_type in {"output_text", "text"}:
                value = getattr(content, "text", "")
                if value:
                    parts.append(value)
    return "".join(parts)


async def generate_text(
    *,
    provider: str | LLMProvider,
    model: str,
    user_prompt: str,
    system_prompt: str | None = None,
    max_output_tokens: int = 8192,
) -> str:
    """Generate free-form text using the configured provider."""
    resolved = resolve_provider(provider)

    if resolved == LLMProvider.anthropic:
        import anthropic

        client = anthropic.AsyncAnthropic()
        response = await client.messages.create(
            model=model,
            max_tokens=max_output_tokens,
            system=system_prompt or anthropic.NOT_GIVEN,
            messages=[{"role": "user", "content": user_prompt}],
        )
        first = response.content[0] if response.content else None
        return getattr(first, "text", "") if first is not None else ""

    from openai import AsyncOpenAI

    client = AsyncOpenAI()
    response = await client.responses.create(
        model=model,
        instructions=system_prompt,
        input=user_prompt,
        max_output_tokens=max_output_tokens,
    )
    return _extract_openai_text(response)


async def generate_structured(
    *,
    provider: str | LLMProvider,
    model: str,
    schema_model: type[T],
    user_prompt: str,
    system_prompt: str | None = None,
    max_output_tokens: int = 4096,
    tool_name: str = "record_result",
    tool_description: str = "Record the structured output.",
) -> T | None:
    """Generate structured output using the configured provider."""
    resolved = resolve_provider(provider)

    if resolved == LLMProvider.anthropic:
        import anthropic

        client = anthropic.AsyncAnthropic()
        response = await client.messages.create(
            model=model,
            max_tokens=max_output_tokens,
            system=system_prompt or anthropic.NOT_GIVEN,
            messages=[{"role": "user", "content": user_prompt}],
            tools=[{
                "name": tool_name,
                "description": tool_description,
                "input_schema": schema_model.model_json_schema(),
            }],
            tool_choice={"type": "tool", "name": tool_name},
        )

        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                try:
                    return schema_model.model_validate(block.input)
                except Exception:
                    logger.warning("Failed to validate Anthropic structured output", exc_info=True)
                    return None
        return None

    from openai import AsyncOpenAI

    client = AsyncOpenAI()
    response = await client.responses.create(
        model=model,
        instructions=system_prompt,
        input=user_prompt,
        max_output_tokens=max_output_tokens,
        text={
            "format": {
                "type": "json_schema",
                "name": tool_name,
                "strict": True,
                "schema": schema_model.model_json_schema(),
            }
        },
    )

    text = _extract_openai_text(response)
    if not text:
        return None

    try:
        return schema_model.model_validate(json.loads(text))
    except Exception:
        logger.warning("Failed to validate OpenAI structured output", exc_info=True)
        return None
