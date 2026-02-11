"""Test suite for datasheet spec extractor (US-017).

All Anthropic API calls are fully mocked -- no real API traffic.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from revlo.datasheet.extractor import _MAX_TOKENS, _MODEL, extract_spec
from revlo.datasheet.models import DatasheetSpec, PinFunction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_tool_use_block(spec_input: dict):
    """Create a mock tool_use content block with DatasheetSpec input."""
    return SimpleNamespace(
        type="tool_use",
        id="toolu_test",
        name="record_datasheet_spec",
        input=spec_input,
    )


def _make_api_response(spec_input: dict):
    """Create a mock API response with a tool_use content block."""
    return SimpleNamespace(content=[_make_tool_use_block(spec_input)])


def _make_text_only_response(text: str):
    """Create a mock API response with only a text block (no tool_use)."""
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def _valid_spec_dict(**overrides) -> dict:
    """Return a minimal valid DatasheetSpec dict."""
    base = {
        "mpn": "STM32F103CBT6",
        "manufacturer": "STMicroelectronics",
        "description": "ARM Cortex-M3 microcontroller",
        "supply_voltage_min": 2.0,
        "supply_voltage_max": 3.6,
        "max_current": 0.15,
        "pin_functions": [
            {
                "pin_number": "1",
                "name": "VBAT",
                "function_description": "Battery backup power",
                "electrical_type": "power_in",
            },
        ],
        "absolute_max_ratings": {"VDD": "4.0V"},
        "recommended_operating": {"VDD": "2.0V to 3.6V"},
        "notes": ["Requires external crystal for USB"],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Successful extraction
# ---------------------------------------------------------------------------
class TestSuccessfulExtraction:
    @pytest.mark.asyncio
    async def test_valid_tool_use_returns_datasheet_spec(self):
        """Happy path: Claude returns valid DatasheetSpec via tool_use."""
        pdf_text = "STM32F103CBT6 datasheet text..."
        mpn = "STM32F103CBT6"
        spec_data = _valid_spec_dict()
        response = _make_api_response(spec_data)

        with patch("revlo.datasheet.extractor.anthropic.AsyncAnthropic") as MockClient:
            mock_create = AsyncMock(return_value=response)
            MockClient.return_value.messages.create = mock_create

            result = await extract_spec(pdf_text, mpn)

        assert isinstance(result, DatasheetSpec)
        assert result.mpn == "STM32F103CBT6"
        assert result.manufacturer == "STMicroelectronics"
        assert result.description == "ARM Cortex-M3 microcontroller"
        assert result.supply_voltage_min == 2.0
        assert result.supply_voltage_max == 3.6
        assert result.max_current == 0.15
        assert len(result.pin_functions) == 1
        assert result.pin_functions[0].pin_number == "1"
        assert result.absolute_max_ratings == {"VDD": "4.0V"}
        assert result.recommended_operating == {"VDD": "2.0V to 3.6V"}
        assert result.notes == ["Requires external crystal for USB"]

    @pytest.mark.asyncio
    async def test_minimal_spec_with_defaults(self):
        """Spec with only required fields uses model defaults."""
        pdf_text = "Minimal datasheet..."
        mpn = "TEST123"
        spec_data = {"mpn": "TEST123"}
        response = _make_api_response(spec_data)

        with patch("revlo.datasheet.extractor.anthropic.AsyncAnthropic") as MockClient:
            mock_create = AsyncMock(return_value=response)
            MockClient.return_value.messages.create = mock_create

            result = await extract_spec(pdf_text, mpn)

        assert isinstance(result, DatasheetSpec)
        assert result.mpn == "TEST123"
        assert result.manufacturer == ""
        assert result.description == ""
        assert result.supply_voltage_min is None
        assert result.supply_voltage_max is None
        assert result.max_current is None
        assert result.pin_functions == []
        assert result.absolute_max_ratings == {}
        assert result.recommended_operating == {}
        assert result.notes == []


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_api_exception_returns_none(self, caplog):
        """API exception should be caught and return None."""
        pdf_text = "Some datasheet text..."
        mpn = "STM32F103CBT6"

        with patch("revlo.datasheet.extractor.anthropic.AsyncAnthropic") as MockClient:
            mock_create = AsyncMock(side_effect=Exception("API unavailable"))
            MockClient.return_value.messages.create = mock_create

            with caplog.at_level(logging.WARNING):
                result = await extract_spec(pdf_text, mpn)

        assert result is None
        assert "API call failed" in caplog.text
        assert "STM32F103CBT6" in caplog.text

    @pytest.mark.asyncio
    async def test_no_tool_use_block_returns_none(self, caplog):
        """Response with no tool_use block should return None."""
        pdf_text = "Datasheet text..."
        mpn = "STM32F103CBT6"
        response = _make_text_only_response("I cannot extract specs")

        with patch("revlo.datasheet.extractor.anthropic.AsyncAnthropic") as MockClient:
            mock_create = AsyncMock(return_value=response)
            MockClient.return_value.messages.create = mock_create

            with caplog.at_level(logging.WARNING):
                result = await extract_spec(pdf_text, mpn)

        assert result is None
        assert "No tool_use block" in caplog.text
        assert "STM32F103CBT6" in caplog.text

    @pytest.mark.asyncio
    async def test_validation_error_returns_none(self, caplog):
        """Malformed tool input that fails validation should return None."""
        pdf_text = "Datasheet text..."
        mpn = "STM32F103CBT6"
        # Missing required 'mpn' field
        spec_data = {"manufacturer": "Test Corp"}
        response = _make_api_response(spec_data)

        with patch("revlo.datasheet.extractor.anthropic.AsyncAnthropic") as MockClient:
            mock_create = AsyncMock(return_value=response)
            MockClient.return_value.messages.create = mock_create

            with caplog.at_level(logging.WARNING):
                result = await extract_spec(pdf_text, mpn)

        assert result is None
        assert "Failed to validate DatasheetSpec" in caplog.text
        assert "STM32F103CBT6" in caplog.text


# ---------------------------------------------------------------------------
# Text truncation
# ---------------------------------------------------------------------------
class TestTextTruncation:
    @pytest.mark.asyncio
    async def test_truncates_to_100k_chars(self):
        """PDF text longer than 100K chars should be truncated."""
        # Create text longer than limit
        long_text = "A" * 150_000
        mpn = "STM32F103CBT6"
        spec_data = _valid_spec_dict()
        response = _make_api_response(spec_data)

        with patch("revlo.datasheet.extractor.anthropic.AsyncAnthropic") as MockClient:
            mock_create = AsyncMock(return_value=response)
            MockClient.return_value.messages.create = mock_create

            result = await extract_spec(long_text, mpn)

        assert result is not None
        # Verify the truncated text was used in the prompt
        call_args = mock_create.call_args
        user_message = call_args.kwargs["messages"][0]["content"]
        # The prompt should contain truncated text (100K chars), not the full 150K
        assert len(user_message) < len(long_text)
        # Verify it's around 100K + prompt template overhead
        assert "A" * 100_000 in user_message


# ---------------------------------------------------------------------------
# API parameters
# ---------------------------------------------------------------------------
class TestAPIParameters:
    @pytest.mark.asyncio
    async def test_sends_correct_api_parameters(self):
        """Verify model, max_tokens, system, user message, tools, and tool_choice."""
        pdf_text = "Custom datasheet content for testing"
        mpn = "CUSTOM123"
        spec_data = _valid_spec_dict(mpn="CUSTOM123")
        response = _make_api_response(spec_data)

        with patch("revlo.datasheet.extractor.anthropic.AsyncAnthropic") as MockClient:
            mock_create = AsyncMock(return_value=response)
            MockClient.return_value.messages.create = mock_create

            await extract_spec(pdf_text, mpn)

        call_args = mock_create.call_args

        # Model
        assert call_args.kwargs["model"] == _MODEL
        assert call_args.kwargs["model"] == "claude-haiku-4-5-20251001"

        # Max tokens
        assert call_args.kwargs["max_tokens"] == _MAX_TOKENS
        assert call_args.kwargs["max_tokens"] == 4096

        # System prompt
        assert "system" in call_args.kwargs
        assert "expert electronics engineer" in call_args.kwargs["system"].lower()

        # User message contains MPN and PDF text
        messages = call_args.kwargs["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        user_content = messages[0]["content"]
        assert "CUSTOM123" in user_content
        assert "Custom datasheet content for testing" in user_content

        # Tools parameter
        assert "tools" in call_args.kwargs
        tools = call_args.kwargs["tools"]
        assert len(tools) == 1
        assert tools[0]["name"] == "record_datasheet_spec"
        assert "input_schema" in tools[0]

        # Tool choice forces the tool
        assert "tool_choice" in call_args.kwargs
        tool_choice = call_args.kwargs["tool_choice"]
        assert tool_choice["type"] == "tool"
        assert tool_choice["name"] == "record_datasheet_spec"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------
class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_multiple_pin_functions(self):
        """Spec with multiple pin functions are all preserved."""
        pdf_text = "Multi-pin datasheet..."
        mpn = "MULTI123"
        spec_data = _valid_spec_dict(
            mpn="MULTI123",
            pin_functions=[
                {
                    "pin_number": "1",
                    "name": "VDD",
                    "function_description": "Power supply",
                    "electrical_type": "power_in",
                },
                {
                    "pin_number": "2",
                    "name": "GND",
                    "function_description": "Ground",
                    "electrical_type": "power_in",
                },
                {
                    "pin_number": "3",
                    "name": "PA0",
                    "function_description": "GPIO",
                    "electrical_type": "bidirectional",
                },
            ],
        )
        response = _make_api_response(spec_data)

        with patch("revlo.datasheet.extractor.anthropic.AsyncAnthropic") as MockClient:
            mock_create = AsyncMock(return_value=response)
            MockClient.return_value.messages.create = mock_create

            result = await extract_spec(pdf_text, mpn)

        assert len(result.pin_functions) == 3
        assert all(isinstance(pf, PinFunction) for pf in result.pin_functions)
        assert result.pin_functions[0].pin_number == "1"
        assert result.pin_functions[1].pin_number == "2"
        assert result.pin_functions[2].pin_number == "3"

    @pytest.mark.asyncio
    async def test_none_values_preserved(self):
        """Optional None fields are preserved correctly."""
        pdf_text = "Partial datasheet..."
        mpn = "PARTIAL123"
        spec_data = {
            "mpn": "PARTIAL123",
            "manufacturer": "Test Corp",
            "description": "Test part",
            "supply_voltage_min": None,
            "supply_voltage_max": None,
            "max_current": None,
        }
        response = _make_api_response(spec_data)

        with patch("revlo.datasheet.extractor.anthropic.AsyncAnthropic") as MockClient:
            mock_create = AsyncMock(return_value=response)
            MockClient.return_value.messages.create = mock_create

            result = await extract_spec(pdf_text, mpn)

        assert result.supply_voltage_min is None
        assert result.supply_voltage_max is None
        assert result.max_current is None
