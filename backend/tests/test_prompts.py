"""Test suite for prompt templates (US-009)."""

import json

import pytest

from revlo.parser.models import (
    ParsedComponent,
    ParsedNet,
    ParsedPin,
    PinConnection,
)
from revlo.reviewer.chunker import ReviewChunk
from revlo.reviewer.prompts import build_review_prompt, _format_chunk_data


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def ic_chunk() -> ReviewChunk:
    return ReviewChunk(
        chunk_type="ic_context",
        label="U1 - STM32F103",
        components=[
            ParsedComponent(
                reference="U1",
                value="STM32F103",
                lib_id="MCU_ST:STM32F103CBT6",
                footprint="LQFP-48",
                position=(100.0, 100.0),
                pins=[
                    ParsedPin(number="1", name="VBAT", electrical_type="power_in", connected_net="VCC"),
                    ParsedPin(number="2", name="PA0", electrical_type="bidirectional", connected_net="SIG1"),
                ],
            ),
            ParsedComponent(
                reference="C1",
                value="100nF",
                lib_id="Device:C",
                footprint="0402",
                position=(110.0, 100.0),
                pins=[
                    ParsedPin(number="1", name="1", electrical_type="passive", connected_net="VCC"),
                    ParsedPin(number="2", name="2", electrical_type="passive", connected_net="GND"),
                ],
            ),
        ],
        nets=[
            ParsedNet(name="VCC", pins=[
                PinConnection(component_ref="U1", pin_number="1", pin_name="VBAT"),
                PinConnection(component_ref="C1", pin_number="1", pin_name="1"),
            ], is_power=True),
            ParsedNet(name="SIG1", pins=[
                PinConnection(component_ref="U1", pin_number="2", pin_name="PA0"),
            ], is_power=False),
        ],
        unconnected_pins=[
            PinConnection(component_ref="U1", pin_number="3", pin_name="PA1"),
        ],
    )


@pytest.fixture
def power_chunk() -> ReviewChunk:
    return ReviewChunk(
        chunk_type="power_rail",
        label="Power Rail: VCC",
        components=[
            ParsedComponent(
                reference="U5",
                value="LM7805",
                lib_id="Regulator_Linear:LM7805",
                footprint="TO-220",
                position=(50.0, 50.0),
                pins=[
                    ParsedPin(number="3", name="OUT", electrical_type="power_out", connected_net="VCC"),
                ],
            ),
            ParsedComponent(
                reference="C10",
                value="10uF",
                lib_id="Device:C",
                footprint="0805",
                position=(60.0, 50.0),
                pins=[
                    ParsedPin(number="1", name="1", electrical_type="passive", connected_net="VCC"),
                ],
            ),
        ],
        nets=[
            ParsedNet(name="VCC", pins=[
                PinConnection(component_ref="U5", pin_number="3", pin_name="OUT"),
                PinConnection(component_ref="C10", pin_number="1", pin_name="1"),
            ], is_power=True, labels=["VCC_5V"]),
        ],
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
class TestDispatcher:
    def test_routes_both_chunk_types(self, ic_chunk, power_chunk):
        assert isinstance(build_review_prompt(ic_chunk), str)
        assert isinstance(build_review_prompt(power_chunk), str)

    def test_unknown_type_raises(self):
        bad = ReviewChunk(chunk_type="unknown", label="X")
        with pytest.raises(ValueError, match="Unknown chunk type"):
            build_review_prompt(bad)


# ---------------------------------------------------------------------------
# IC-context prompt
# ---------------------------------------------------------------------------
class TestICContextPrompt:
    def test_contains_checklist_and_schema(self, ic_chunk):
        p = build_review_prompt(ic_chunk)
        # Layer 1 checklist items
        for keyword in ["Decoupling", "Pull-up", "Unused pins", "Reset", "Clock", "Signal integrity", "ESD"]:
            assert keyword in p
        # Finding schema embedded as valid JSON
        start = p.find("```json")
        end = p.find("```", start + 7)
        schema = json.loads(p[start + 7 : end])
        assert "severity" in schema["properties"]

    def test_contains_chunk_data(self, ic_chunk):
        p = build_review_prompt(ic_chunk)
        # Components, nets, pins, unconnected
        for text in ["U1", "C1", "STM32F103", "100nF", "VCC", "SIG1", "VBAT", "PA0", "PA1", "Unconnected"]:
            assert text in p


# ---------------------------------------------------------------------------
# Power-rail prompt
# ---------------------------------------------------------------------------
class TestPowerRailPrompt:
    def test_contains_checklist_and_schema(self, power_chunk):
        p = build_review_prompt(power_chunk)
        for keyword in ["Bulk", "bypass", "regulator", "Ground", "sequencing", "Current capacity", "Protection"]:
            assert keyword.lower() in p.lower()
        start = p.find("```json")
        end = p.find("```", start + 7)
        schema = json.loads(p[start + 7 : end])
        assert "severity" in schema["properties"]

    def test_contains_chunk_data(self, power_chunk):
        p = build_review_prompt(power_chunk)
        for text in ["U5", "C10", "LM7805", "VCC", "VCC_5V"]:
            assert text in p


# ---------------------------------------------------------------------------
# Data formatting
# ---------------------------------------------------------------------------
class TestFormatChunkData:
    def test_empty_chunk(self):
        result = _format_chunk_data(ReviewChunk(chunk_type="ic_context", label="Empty"))
        assert result == ""

    def test_all_sections(self, ic_chunk):
        result = _format_chunk_data(ic_chunk)
        assert "## Components" in result
        assert "## Nets" in result
        assert "[POWER]" in result
        assert "## Unconnected Pins" in result
        assert "U1.1" in result  # pin connection format

    def test_properties_included(self):
        comp = ParsedComponent(reference="U1", value="STM32", lib_id="MCU:STM32", properties={"DNP": "false"})
        chunk = ReviewChunk(chunk_type="ic_context", label="Test", components=[comp])
        assert "Properties:" in _format_chunk_data(chunk)


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------
class TestPureFunctions:
    def test_no_anthropic_import_and_deterministic(self, ic_chunk):
        import inspect
        import revlo.reviewer.prompts as mod

        assert not inspect.iscoroutinefunction(build_review_prompt)
        assert "anthropic" not in str(dir(mod)).lower()
        assert build_review_prompt(ic_chunk) == build_review_prompt(ic_chunk)

    def test_export_from_reviewer_package(self):
        from revlo.reviewer import build_review_prompt as fn
        assert callable(fn)
