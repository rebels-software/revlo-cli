"""Test suite for the async review engine (US-010)."""

from __future__ import annotations

import datetime
import json
import logging
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
    _build_summary,
    review_schematic,
)
from revlo.reviewer.chunker import ReviewChunk
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

    async def _mock_impl(chunks, system_prompt, provider, model):
        return list(findings)

    return _mock_impl


def _mock_generate_text_responses(*responses: str):
    """Return a side effect for generate_text that yields canned responses."""
    queue = list(responses)

    async def _mock_impl(**kwargs):
        if not queue:
            raise AssertionError("generate_text called more times than expected")
        return queue.pop(0)

    return _mock_impl


def _make_review_chunk(index: int) -> ReviewChunk:
    """Create a minimal review chunk for batching tests."""
    return ReviewChunk(
        chunk_type="ic_context",
        label=f"U{index} - Test IC {index}",
        components=[
            ParsedComponent(
                reference=f"U{index}",
                value=f"TestIC{index}",
                lib_id="MCU_ST:TEST",
                footprint="QFN-32",
                pins=[],
            )
        ],
        nets=[],
        unconnected_pins=[],
    )


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

        async def _mock_chunk_generic(chunk, provider, model, review_profile):
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

    @pytest.mark.asyncio
    async def test_merges_deterministic_and_llm_findings(self):
        """Deterministic findings should be merged with LLM findings."""
        schematic = _make_schematic()
        deterministic = [
            Finding(**_valid_finding_dict(
                component_ref="C1",
                title="Scaffold deterministic issue",
                source_type="deterministic",
            ))
        ]
        llm_findings = [Finding(**_valid_finding_dict())]

        with patch(
            "revlo.reviewer.engine.run_deterministic_checks",
            return_value=deterministic,
        ) as mock_rules, patch(
            "revlo.reviewer.engine._review_with_ee_agent",
            side_effect=_mock_review_with_ee_agent(llm_findings),
        ):
            report = await review_schematic(schematic)

        mock_rules.assert_called_once_with(
            schematic,
            enabled=None,
            bom=None,
            project_constraints=None,
            custom_rule_packs=None,
        )
        assert [f.title for f in report.findings] == [
            "Scaffold deterministic issue",
            "Missing decoupling capacitor",
        ]

    @pytest.mark.asyncio
    async def test_can_disable_deterministic_checks_via_parameter(self):
        """Function parameter should disable deterministic checks."""
        schematic = _make_schematic()
        llm_findings = [Finding(**_valid_finding_dict())]

        with patch(
            "revlo.reviewer.engine.run_deterministic_checks",
            return_value=[],
        ) as mock_rules, patch(
            "revlo.reviewer.engine._review_with_ee_agent",
            side_effect=_mock_review_with_ee_agent(llm_findings),
        ):
            report = await review_schematic(
                schematic,
                enable_deterministic_checks=False,
            )

        mock_rules.assert_called_once_with(
            schematic,
            enabled=False,
            bom=None,
            project_constraints=None,
            custom_rule_packs=None,
        )
        assert [f.title for f in report.findings] == ["Missing decoupling capacitor"]

    @pytest.mark.asyncio
    async def test_empty_schematic_can_return_deterministic_findings(self):
        """Deterministic findings still surface when there are no review chunks."""
        schematic = ParsedSchematic(title_block=TitleBlockInfo(title="Empty Board"))
        deterministic = [Finding(**_valid_finding_dict(source_type="deterministic"))]

        with patch(
            "revlo.reviewer.engine.run_deterministic_checks",
            return_value=deterministic,
        ):
            report = await review_schematic(schematic)

        assert [f.source_type for f in report.findings] == ["deterministic"]
        assert report.summary == "Found 1 issues (1 errors, 0 warnings, 0 suggestions)"


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

    def test_deterministic_toggle_parameter_present(self):
        import inspect
        sig = inspect.signature(review_schematic)
        assert "enable_deterministic_checks" in sig.parameters


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


class TestGenericFallback:
    """Test that per-chunk generic review is triggered when the EE agent fails."""

    @pytest.mark.asyncio
    async def test_fallback_called_when_ee_returns_unparseable(self):
        """When EE agent returns non-JSON text, fallback produces findings."""
        schematic = _make_schematic()
        finding_dict = _valid_finding_dict()
        generic_response_json = json.dumps([finding_dict])

        with patch(
            "revlo.reviewer.engine.generate_text",
            side_effect=_mock_generate_text_responses(
                "This is not valid JSON at all.",
                generic_response_json,
                generic_response_json,
            ),
        ) as mock_generate_text:
            report = await review_schematic(schematic)

        # The fallback should have produced findings.
        assert len(report.findings) > 0
        assert report.findings[0].category == "decoupling"
        # Should have been called more than once (EE + at least 1 fallback chunk).
        assert mock_generate_text.await_count >= 2

    @pytest.mark.asyncio
    async def test_no_fallback_when_ee_succeeds(self):
        """When EE agent returns valid findings, fallback is NOT triggered."""
        schematic = _make_schematic()
        finding_dict = _valid_finding_dict()
        ee_response_json = json.dumps([finding_dict])

        with patch(
            "revlo.reviewer.engine.generate_text",
            side_effect=_mock_generate_text_responses(ee_response_json),
        ) as mock_generate_text:
            report = await review_schematic(schematic)

        assert len(report.findings) > 0
        # Only the single EE agent call, no fallback.
        assert mock_generate_text.await_count == 1

    @pytest.mark.asyncio
    async def test_fallback_with_dict_findings_format(self):
        """Generic fallback handles {'findings': [...]} response format."""
        schematic = _make_schematic()
        finding_dict = _valid_finding_dict()
        generic_response_json = json.dumps({"findings": [finding_dict]})

        with patch(
            "revlo.reviewer.engine.generate_text",
            side_effect=_mock_generate_text_responses(
                "not json",
                generic_response_json,
                generic_response_json,
            ),
        ):
            report = await review_schematic(schematic)

        assert len(report.findings) > 0


class TestDebugLogging:
    """Test that warning logs include raw response text for debugging."""

    @pytest.mark.asyncio
    async def test_ee_agent_logs_unparseable_response(self, caplog):
        """When EE agent returns non-JSON, warning log includes response text."""
        schematic = _make_schematic()
        garbage_text = "TRUNCATED JSON: {findings: [incomplete..."

        with patch(
            "revlo.reviewer.engine.generate_text",
            side_effect=_mock_generate_text_responses(garbage_text, "[]", "[]"),
        ):
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

        with patch(
            "revlo.reviewer.engine.generate_text",
            side_effect=_mock_generate_text_responses("no json here", "[]", "[]"),
        ):
            with caplog.at_level(logging.INFO, logger="revlo.reviewer.engine"):
                await review_schematic(schematic)

        assert any(
            "falling back to per-chunk generic review" in record.message
            for record in caplog.records
        ), f"Expected fallback info log, got: {[r.message for r in caplog.records]}"


class TestBoundedBatchReview:
    @pytest.mark.asyncio
    async def test_large_schematic_is_split_into_bounded_batches(self, monkeypatch):
        monkeypatch.setenv("REVLO_REVIEW_BATCH_SIZE", "2")
        schematic = _make_schematic()
        chunks = [_make_review_chunk(i) for i in range(1, 6)]
        seen_batch_sizes: list[int] = []

        async def _mock_batched_review(batch, system_prompt, provider, model):
            seen_batch_sizes.append(len(batch))
            batch_number = len(seen_batch_sizes)
            return [
                Finding(
                    **_valid_finding_dict(
                        component_ref=batch[0].components[0].reference,
                        title=f"Batch {batch_number} finding",
                    )
                )
            ]

        with patch(
            "revlo.reviewer.engine.chunk_schematic",
            return_value=chunks,
        ), patch(
            "revlo.reviewer.engine._review_with_ee_agent",
            side_effect=_mock_batched_review,
        ), patch(
            "revlo.reviewer.engine._review_chunk_generic",
        ) as mock_chunk_generic:
            report = await review_schematic(schematic)

        assert seen_batch_sizes == [2, 2, 1]
        assert len(report.findings) == 3
        mock_chunk_generic.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_batch_falls_back_only_for_that_batch(self, monkeypatch):
        monkeypatch.setenv("REVLO_REVIEW_BATCH_SIZE", "2")
        schematic = _make_schematic()
        chunks = [_make_review_chunk(i) for i in range(1, 5)]
        fallback_chunks: list[str] = []

        async def _mock_batched_review(batch, system_prompt, provider, model):
            if batch[0].label.startswith("U1"):
                return [Finding(**_valid_finding_dict(component_ref="U1"))]
            return []

        async def _mock_chunk_generic(chunk, provider, model, review_profile):
            fallback_chunks.append(chunk.label)
            return [
                Finding(
                    **_valid_finding_dict(
                        component_ref=chunk.components[0].reference,
                        title=f"Fallback for {chunk.label}",
                    )
                )
            ]

        with patch(
            "revlo.reviewer.engine.chunk_schematic",
            return_value=chunks,
        ), patch(
            "revlo.reviewer.engine._review_with_ee_agent",
            side_effect=_mock_batched_review,
        ), patch(
            "revlo.reviewer.engine._review_chunk_generic",
            side_effect=_mock_chunk_generic,
        ):
            report = await review_schematic(schematic)

        assert fallback_chunks == [chunks[2].label, chunks[3].label]
        assert len(report.findings) == 3
