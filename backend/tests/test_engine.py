"""Test suite for the async review engine (US-010).

All Claude API calls are fully mocked -- no real API traffic.
"""

from __future__ import annotations

import datetime
from unittest.mock import patch

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
        """EE agent returns no findings produces empty report."""
        schematic = _make_schematic()

        with patch(
            "revlo.reviewer.engine._review_with_ee_agent",
            side_effect=_mock_review_with_ee_agent([]),
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
