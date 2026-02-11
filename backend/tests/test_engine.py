"""Test suite for the async review engine (US-010).

All Anthropic API calls are fully mocked -- no real API traffic.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from revlo.parser.models import (
    ParsedComponent,
    ParsedNet,
    ParsedPin,
    ParsedSchematic,
    PinConnection,
    TitleBlockInfo,
)
from revlo.reviewer.engine import _build_summary, _review_chunk, review_schematic
from revlo.reviewer.models import (
    Finding,
    FindingCategory,
    ReviewReport,
    Severity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_text_block(text: str):
    """Create a mock content block with a .text attribute."""
    return SimpleNamespace(text=text)


def _make_api_response(text: str):
    """Create a mock API response with a single text content block."""
    return SimpleNamespace(content=[_make_text_block(text)])


def _valid_finding_dict(**overrides) -> dict:
    """Return a minimal valid Finding dict."""
    base = {
        "severity": "error",
        "category": "decoupling",
        "component_ref": "U1",
        "title": "Missing decoupling capacitor",
        "description": "U1 pin 1 (VCC) has no bypass cap",
        "recommendation": "Add a 100nF cap close to pin 1",
        "confidence": 0.9,
    }
    base.update(overrides)
    return base


def _make_schematic(**overrides) -> ParsedSchematic:
    """Create a minimal ParsedSchematic with one IC and supporting nets."""
    defaults = dict(
        components=[
            ParsedComponent(
                reference="U1",
                value="STM32F103",
                lib_id="MCU_ST:STM32F103",
                footprint="LQFP-48",
                pins=[
                    ParsedPin(
                        number="1",
                        name="VCC",
                        electrical_type="power_in",
                        connected_net="VCC",
                    ),
                    ParsedPin(
                        number="2",
                        name="PA0",
                        electrical_type="bidirectional",
                        connected_net="SIG1",
                    ),
                ],
            ),
            ParsedComponent(
                reference="C1",
                value="100nF",
                lib_id="Device:C",
                footprint="0402",
                pins=[
                    ParsedPin(
                        number="1",
                        name="1",
                        electrical_type="passive",
                        connected_net="VCC",
                    ),
                    ParsedPin(
                        number="2",
                        name="2",
                        electrical_type="passive",
                        connected_net="GND",
                    ),
                ],
            ),
        ],
        nets=[
            ParsedNet(
                name="VCC",
                pins=[
                    PinConnection(component_ref="U1", pin_number="1", pin_name="VCC"),
                    PinConnection(component_ref="C1", pin_number="1", pin_name="1"),
                ],
                is_power=True,
            ),
            ParsedNet(
                name="SIG1",
                pins=[
                    PinConnection(component_ref="U1", pin_number="2", pin_name="PA0"),
                ],
                is_power=False,
            ),
        ],
        power_symbols=[],
        unconnected_pins=[],
        title_block=TitleBlockInfo(title="Test Board"),
    )
    defaults.update(overrides)
    return ParsedSchematic(**defaults)


# ---------------------------------------------------------------------------
# _build_summary
# ---------------------------------------------------------------------------
class TestBuildSummary:
    def test_zero_findings(self):
        assert _build_summary([]) == "Found 0 issues (0 errors, 0 warnings, 0 suggestions)"

    def test_mixed_findings(self):
        findings = [
            Finding(**_valid_finding_dict(severity="error")),
            Finding(**_valid_finding_dict(severity="error")),
            Finding(**_valid_finding_dict(severity="warning")),
            Finding(**_valid_finding_dict(severity="suggestion")),
        ]
        result = _build_summary(findings)
        assert result == "Found 4 issues (2 errors, 1 warnings, 1 suggestions)"


# ---------------------------------------------------------------------------
# _review_chunk (unit-level)
# ---------------------------------------------------------------------------
class TestReviewChunk:
    @pytest.mark.asyncio
    async def test_valid_json_array(self):
        """Happy path: Claude returns a valid JSON array of findings."""
        from revlo.reviewer.chunker import ReviewChunk

        chunk = ReviewChunk(chunk_type="ic_context", label="U1 - STM32F103")
        findings_data = [_valid_finding_dict(), _valid_finding_dict(severity="warning")]
        response = _make_api_response(json.dumps(findings_data))

        client = MagicMock()
        client.messages.create = AsyncMock(return_value=response)

        result = await _review_chunk(client, chunk)
        assert len(result) == 2
        assert all(isinstance(f, Finding) for f in result)
        assert result[0].severity == Severity.error
        assert result[1].severity == Severity.warning

    @pytest.mark.asyncio
    async def test_malformed_json_logs_warning(self, caplog):
        """Garbage text from Claude should log a warning and return empty."""
        from revlo.reviewer.chunker import ReviewChunk

        chunk = ReviewChunk(chunk_type="ic_context", label="U1 - BadResponse")
        response = _make_api_response("This is not JSON at all!")

        client = MagicMock()
        client.messages.create = AsyncMock(return_value=response)

        with caplog.at_level(logging.WARNING):
            result = await _review_chunk(client, chunk)

        assert result == []
        assert "Malformed JSON" in caplog.text

    @pytest.mark.asyncio
    async def test_json_not_array_logs_warning(self, caplog):
        """A JSON object (not an array) should be rejected."""
        from revlo.reviewer.chunker import ReviewChunk

        chunk = ReviewChunk(chunk_type="ic_context", label="U1 - NotArray")
        response = _make_api_response(json.dumps({"severity": "error"}))

        client = MagicMock()
        client.messages.create = AsyncMock(return_value=response)

        with caplog.at_level(logging.WARNING):
            result = await _review_chunk(client, chunk)

        assert result == []
        assert "Expected JSON array" in caplog.text

    @pytest.mark.asyncio
    async def test_invalid_finding_skipped(self, caplog):
        """A finding that fails Pydantic validation is skipped; valid ones kept."""
        from revlo.reviewer.chunker import ReviewChunk

        chunk = ReviewChunk(chunk_type="ic_context", label="U1 - PartialBad")
        findings_data = [
            _valid_finding_dict(),
            {"severity": "error"},  # missing required fields
            _valid_finding_dict(severity="suggestion"),
        ]
        response = _make_api_response(json.dumps(findings_data))

        client = MagicMock()
        client.messages.create = AsyncMock(return_value=response)

        with caplog.at_level(logging.WARNING):
            result = await _review_chunk(client, chunk)

        assert len(result) == 2
        assert result[0].severity == Severity.error
        assert result[1].severity == Severity.suggestion
        assert "Invalid finding" in caplog.text

    @pytest.mark.asyncio
    async def test_empty_array_returns_no_findings(self):
        """Claude returns [] -- no issues found."""
        from revlo.reviewer.chunker import ReviewChunk

        chunk = ReviewChunk(chunk_type="ic_context", label="U1 - Clean")
        response = _make_api_response("[]")

        client = MagicMock()
        client.messages.create = AsyncMock(return_value=response)

        result = await _review_chunk(client, chunk)
        assert result == []

    @pytest.mark.asyncio
    async def test_api_exception_logs_warning(self, caplog):
        """An API exception should be caught and logged, returning empty."""
        from revlo.reviewer.chunker import ReviewChunk

        chunk = ReviewChunk(chunk_type="ic_context", label="U1 - APIFail")

        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=Exception("API down"))

        with caplog.at_level(logging.WARNING):
            result = await _review_chunk(client, chunk)

        assert result == []
        assert "API call failed" in caplog.text


# ---------------------------------------------------------------------------
# review_schematic (integration-level, fully mocked)
# ---------------------------------------------------------------------------
class TestReviewSchematic:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        """Full flow: schematic -> chunks -> prompts -> API -> report."""
        schematic = _make_schematic()
        findings_data = [_valid_finding_dict()]
        response = _make_api_response(json.dumps(findings_data))

        mock_create = AsyncMock(return_value=response)

        with patch("revlo.reviewer.engine.anthropic.AsyncAnthropic") as MockClient:
            MockClient.return_value.messages.create = mock_create
            report = await review_schematic(schematic)

        assert isinstance(report, ReviewReport)
        assert len(report.findings) > 0
        assert report.schematic_title == "Test Board"
        assert report.review_date == datetime.date.today().isoformat()
        assert "issues" in report.summary
        # Verify the API was called (once per chunk)
        assert mock_create.call_count > 0

    @pytest.mark.asyncio
    async def test_empty_schematic(self):
        """A schematic with no components produces no chunks and an empty report."""
        schematic = ParsedSchematic(title_block=TitleBlockInfo(title="Empty Board"))

        with patch("revlo.reviewer.engine.anthropic.AsyncAnthropic") as MockClient:
            mock_create = AsyncMock()
            MockClient.return_value.messages.create = mock_create
            report = await review_schematic(schematic)

        assert isinstance(report, ReviewReport)
        assert report.findings == []
        assert report.schematic_title == "Empty Board"
        assert report.review_date == datetime.date.today().isoformat()
        assert "0 issues" in report.summary
        # No API calls should have been made
        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_malformed_responses_skipped(self, caplog):
        """Chunks with malformed responses are skipped; report is still valid."""
        schematic = _make_schematic()

        # Return garbage for all chunks
        response = _make_api_response("NOT JSON {{{{")
        mock_create = AsyncMock(return_value=response)

        with patch("revlo.reviewer.engine.anthropic.AsyncAnthropic") as MockClient:
            MockClient.return_value.messages.create = mock_create
            with caplog.at_level(logging.WARNING):
                report = await review_schematic(schematic)

        assert report.findings == []
        assert "0 issues" in report.summary
        assert mock_create.call_count > 0

    @pytest.mark.asyncio
    async def test_mixed_valid_and_malformed(self, caplog):
        """Some chunks valid, some malformed -- only valid findings kept."""
        schematic = _make_schematic()
        valid_data = json.dumps([_valid_finding_dict()])
        malformed_data = "garbage text {"

        # Return alternating valid/malformed responses
        responses = [
            _make_api_response(valid_data),
            _make_api_response(malformed_data),
        ]
        call_count = 0

        async def side_effect(**kwargs):
            nonlocal call_count
            idx = call_count % len(responses)
            call_count += 1
            return responses[idx]

        with patch("revlo.reviewer.engine.anthropic.AsyncAnthropic") as MockClient:
            MockClient.return_value.messages.create = AsyncMock(side_effect=side_effect)
            with caplog.at_level(logging.WARNING):
                report = await review_schematic(schematic)

        # At least one finding from the valid response
        assert len(report.findings) >= 1
        assert all(isinstance(f, Finding) for f in report.findings)
        # The malformed chunk was logged
        assert "Malformed JSON" in caplog.text

    @pytest.mark.asyncio
    async def test_uses_correct_model(self):
        """Verify the engine sends requests to claude-sonnet-4-20250514."""
        schematic = _make_schematic()
        response = _make_api_response("[]")
        mock_create = AsyncMock(return_value=response)

        with patch("revlo.reviewer.engine.anthropic.AsyncAnthropic") as MockClient:
            MockClient.return_value.messages.create = mock_create
            await review_schematic(schematic)

        # Check that every call used the correct model
        for call in mock_create.call_args_list:
            assert call.kwargs["model"] == "claude-sonnet-4-20250514"

    @pytest.mark.asyncio
    async def test_uses_user_role_messages(self):
        """Verify prompts are sent as user-role messages."""
        schematic = _make_schematic()
        response = _make_api_response("[]")
        mock_create = AsyncMock(return_value=response)

        with patch("revlo.reviewer.engine.anthropic.AsyncAnthropic") as MockClient:
            MockClient.return_value.messages.create = mock_create
            await review_schematic(schematic)

        for call in mock_create.call_args_list:
            messages = call.kwargs["messages"]
            assert len(messages) == 1
            assert messages[0]["role"] == "user"
            assert isinstance(messages[0]["content"], str)

    @pytest.mark.asyncio
    async def test_concurrent_execution(self):
        """Verify chunks are processed concurrently via asyncio.gather."""
        schematic = _make_schematic()
        response = _make_api_response("[]")
        mock_create = AsyncMock(return_value=response)

        with (
            patch("revlo.reviewer.engine.anthropic.AsyncAnthropic") as MockClient,
            patch("revlo.reviewer.engine.asyncio.gather", wraps=asyncio.gather) as mock_gather,
        ):
            MockClient.return_value.messages.create = mock_create
            await review_schematic(schematic)

        # gather should be called once with all chunk coroutines
        mock_gather.assert_called_once()

    @pytest.mark.asyncio
    async def test_report_stats_computed(self):
        """Verify the report stats are correctly computed from findings."""
        schematic = _make_schematic()
        findings_data = [
            _valid_finding_dict(severity="error"),
            _valid_finding_dict(severity="warning"),
            _valid_finding_dict(severity="suggestion"),
        ]
        response = _make_api_response(json.dumps(findings_data))
        mock_create = AsyncMock(return_value=response)

        with patch("revlo.reviewer.engine.anthropic.AsyncAnthropic") as MockClient:
            MockClient.return_value.messages.create = mock_create
            report = await review_schematic(schematic)

        # Stats come from findings across all chunks
        assert report.stats.total == len(report.findings)
        assert report.stats.total >= 3  # at least from one chunk

    @pytest.mark.asyncio
    async def test_max_tokens_set(self):
        """Verify max_tokens is set in API calls."""
        schematic = _make_schematic()
        response = _make_api_response("[]")
        mock_create = AsyncMock(return_value=response)

        with patch("revlo.reviewer.engine.anthropic.AsyncAnthropic") as MockClient:
            MockClient.return_value.messages.create = mock_create
            await review_schematic(schematic)

        for call in mock_create.call_args_list:
            assert "max_tokens" in call.kwargs
            assert call.kwargs["max_tokens"] > 0


# ---------------------------------------------------------------------------
# Function signature
# ---------------------------------------------------------------------------
class TestFunctionSignature:
    def test_is_async(self):
        import inspect

        assert inspect.iscoroutinefunction(review_schematic)

    def test_accepts_parsed_schematic(self):
        import inspect

        sig = inspect.signature(review_schematic)
        params = list(sig.parameters.keys())
        assert "schematic" in params

    def test_return_annotation(self):
        import inspect

        hints = inspect.get_annotations(review_schematic, eval_str=True)
        assert hints["return"] is ReviewReport


# ---------------------------------------------------------------------------
# Re-export
# ---------------------------------------------------------------------------
class TestReExport:
    def test_importable_from_reviewer_package(self):
        from revlo.reviewer import review_schematic as fn

        assert callable(fn)

    def test_in_all(self):
        import revlo.reviewer as pkg

        assert "review_schematic" in pkg.__all__
