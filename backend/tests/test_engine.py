"""Test suite for the async review engine (US-010).

All Claude API calls are fully mocked -- no real API traffic.
"""

from __future__ import annotations

import datetime
import json
import logging
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
from revlo.reviewer.engine import (
    DEFAULT_MODEL,
    MODEL_OPUS,
    MODEL_SONNET,
    _build_summary,
    _review_chunk_generic,
    review_schematic,
)
from revlo.reviewer.models import (
    Finding,
    ReviewReport,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
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


def _mock_review_with_ee_agent(findings: list[Finding] | None = None):
    """Return a mock for _review_with_ee_agent that returns findings."""
    if findings is None:
        findings = [Finding(**_valid_finding_dict())]

    async def _mock_impl(chunks, system_prompt, model):
        return list(findings)

    return _mock_impl


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
# review_schematic (integration-level, fully mocked)
# ---------------------------------------------------------------------------
class TestReviewSchematic:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        """Full flow: schematic -> chunks -> EE agent -> report."""
        schematic = _make_schematic()
        findings = [Finding(**_valid_finding_dict())]

        with patch(
            "revlo.reviewer.engine._review_with_ee_agent",
            side_effect=_mock_review_with_ee_agent(findings),
        ):
            report = await review_schematic(schematic)

        assert isinstance(report, ReviewReport)
        assert len(report.findings) > 0
        assert report.schematic_title == "Test Board"
        assert report.review_date == datetime.date.today().isoformat()
        assert "issues" in report.summary

    @pytest.mark.asyncio
    async def test_empty_schematic(self):
        """A schematic with no components produces no chunks and an empty report."""
        schematic = ParsedSchematic(title_block=TitleBlockInfo(title="Empty Board"))

        report = await review_schematic(schematic)

        assert isinstance(report, ReviewReport)
        assert report.findings == []
        assert report.schematic_title == "Empty Board"
        assert report.review_date == datetime.date.today().isoformat()
        assert "0 issues" in report.summary

    @pytest.mark.asyncio
    async def test_agent_returns_empty_findings(self):
        """EE agent returns no findings and fallback also empty produces empty report."""
        schematic = _make_schematic()

        async def _mock_chunk_generic(chunk, model):
            return []

        with patch(
            "revlo.reviewer.engine._review_with_ee_agent",
            side_effect=_mock_review_with_ee_agent([]),
        ), patch(
            "revlo.reviewer.engine._review_chunk_generic",
            side_effect=_mock_chunk_generic,
        ):
            report = await review_schematic(schematic)

        assert report.findings == []
        assert "0 issues" in report.summary

    @pytest.mark.asyncio
    async def test_confidence_filtering(self):
        """Findings below min_confidence are filtered out."""
        schematic = _make_schematic()
        findings = [
            Finding(**_valid_finding_dict(confidence=0.9)),
            Finding(**_valid_finding_dict(confidence=0.3)),
        ]

        with patch(
            "revlo.reviewer.engine._review_with_ee_agent",
            side_effect=_mock_review_with_ee_agent(findings),
        ):
            report = await review_schematic(schematic, min_confidence=0.5)

        for f in report.findings:
            assert f.confidence >= 0.5

    @pytest.mark.asyncio
    async def test_report_stats_computed(self):
        """Verify the report stats are correctly computed from findings."""
        schematic = _make_schematic()
        findings = [
            Finding(**_valid_finding_dict(severity="error")),
            Finding(**_valid_finding_dict(severity="warning")),
            Finding(**_valid_finding_dict(severity="suggestion")),
        ]

        with patch(
            "revlo.reviewer.engine._review_with_ee_agent",
            side_effect=_mock_review_with_ee_agent(findings),
        ):
            report = await review_schematic(schematic)

        assert report.stats.total == len(report.findings)
        assert report.stats.total >= 3


# ---------------------------------------------------------------------------
# Function signature
# ---------------------------------------------------------------------------
class TestFunctionSignature:
    def test_is_async(self):
        import inspect
        assert inspect.iscoroutinefunction(review_schematic)

    def test_no_use_agents_parameter(self):
        """Verify use_agents parameter was removed."""
        import inspect
        sig = inspect.signature(review_schematic)
        assert "use_agents" not in sig.parameters


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


# ---------------------------------------------------------------------------
# Per-chunk generic fallback
# ---------------------------------------------------------------------------
def _mock_anthropic_response(text: str):
    """Build a mock Anthropic messages.create response with given text."""
    content_block = MagicMock()
    content_block.text = text
    response = MagicMock()
    response.content = [content_block]
    return response


class TestGenericFallback:
    """Test that per-chunk generic review is triggered when the EE agent fails."""

    @pytest.mark.asyncio
    async def test_fallback_called_when_ee_returns_unparseable(self):
        """When EE agent returns non-JSON text, fallback produces findings."""
        schematic = _make_schematic()
        finding_dict = _valid_finding_dict()
        generic_response_json = json.dumps([finding_dict])

        # EE agent returns garbage text (not JSON).
        ee_response = _mock_anthropic_response("This is not valid JSON at all.")
        # Generic fallback returns valid findings.
        generic_response = _mock_anthropic_response(generic_response_json)

        call_count = 0

        async def _fake_create(**kwargs):
            nonlocal call_count
            call_count += 1
            # First call is the EE agent (has system= kwarg).
            if "system" in kwargs:
                return ee_response
            # Subsequent calls are per-chunk generic review.
            return generic_response

        mock_client = MagicMock()
        mock_client.messages.create = _fake_create

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            report = await review_schematic(schematic)

        # The fallback should have produced findings.
        assert len(report.findings) > 0
        assert report.findings[0].category == "decoupling"
        # Should have been called more than once (EE + at least 1 fallback chunk).
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_no_fallback_when_ee_succeeds(self):
        """When EE agent returns valid findings, fallback is NOT triggered."""
        schematic = _make_schematic()
        finding_dict = _valid_finding_dict()
        ee_response_json = json.dumps([finding_dict])

        ee_response = _mock_anthropic_response(ee_response_json)

        call_count = 0

        async def _fake_create(**kwargs):
            nonlocal call_count
            call_count += 1
            return ee_response

        mock_client = MagicMock()
        mock_client.messages.create = _fake_create

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            report = await review_schematic(schematic)

        assert len(report.findings) > 0
        # Only the single EE agent call, no fallback.
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_fallback_with_dict_findings_format(self):
        """Generic fallback handles {'findings': [...]} response format."""
        schematic = _make_schematic()
        finding_dict = _valid_finding_dict()
        generic_response_json = json.dumps({"findings": [finding_dict]})

        ee_response = _mock_anthropic_response("not json")
        generic_response = _mock_anthropic_response(generic_response_json)

        async def _fake_create(**kwargs):
            if "system" in kwargs:
                return ee_response
            return generic_response

        mock_client = MagicMock()
        mock_client.messages.create = _fake_create

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            report = await review_schematic(schematic)

        assert len(report.findings) > 0


class TestDebugLogging:
    """Test that warning logs include raw response text for debugging."""

    @pytest.mark.asyncio
    async def test_ee_agent_logs_unparseable_response(self, caplog):
        """When EE agent returns non-JSON, warning log includes response text."""
        schematic = _make_schematic()
        garbage_text = "TRUNCATED JSON: {findings: [incomplete..."

        ee_response = _mock_anthropic_response(garbage_text)
        # Generic fallback also returns empty to avoid masking the log.
        generic_response = _mock_anthropic_response("[]")

        async def _fake_create(**kwargs):
            if "system" in kwargs:
                return ee_response
            return generic_response

        mock_client = MagicMock()
        mock_client.messages.create = _fake_create

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            with caplog.at_level(logging.WARNING, logger="revlo.reviewer.engine"):
                await review_schematic(schematic)

        # Check the warning log includes the response snippet.
        assert any(
            "Could not extract JSON from EE agent response" in record.message
            and "TRUNCATED JSON" in record.message
            for record in caplog.records
        ), f"Expected warning log with response text, got: {[r.message for r in caplog.records]}"

    @pytest.mark.asyncio
    async def test_fallback_info_log_on_empty_ee(self, caplog):
        """Info log is emitted when falling back to per-chunk review."""
        schematic = _make_schematic()

        ee_response = _mock_anthropic_response("no json here")
        generic_response = _mock_anthropic_response("[]")

        async def _fake_create(**kwargs):
            if "system" in kwargs:
                return ee_response
            return generic_response

        mock_client = MagicMock()
        mock_client.messages.create = _fake_create

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            with caplog.at_level(logging.INFO, logger="revlo.reviewer.engine"):
                await review_schematic(schematic)

        assert any(
            "falling back to per-chunk generic review" in record.message
            for record in caplog.records
        ), f"Expected fallback info log, got: {[r.message for r in caplog.records]}"
