"""Test suite for review engine datasheet specs integration (US-021).

Tests that datasheet_specs parameter is accepted and specs are correctly injected
into chunks before prompt generation. All Claude API calls are fully mocked.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from revlo.datasheet.models import DatasheetSpec
from revlo.parser.models import (
    ParsedComponent,
    ParsedNet,
    ParsedPin,
    ParsedSchematic,
    PinConnection,
    TitleBlockInfo,
)
from revlo.reviewer.engine import review_schematic
from revlo.reviewer.models import ReviewReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
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


def _make_multi_ic_schematic() -> ParsedSchematic:
    """Create a schematic with multiple ICs for testing spec injection."""
    return ParsedSchematic(
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
                ],
            ),
            ParsedComponent(
                reference="U2",
                value="LM358",
                lib_id="Amplifier_Operational:LM358",
                footprint="SOIC-8",
                pins=[
                    ParsedPin(
                        number="8",
                        name="VCC",
                        electrical_type="power_in",
                        connected_net="VCC",
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
                    PinConnection(component_ref="U2", pin_number="8", pin_name="VCC"),
                    PinConnection(component_ref="C1", pin_number="1", pin_name="1"),
                ],
                is_power=True,
            ),
        ],
        power_symbols=[],
        unconnected_pins=[],
        title_block=TitleBlockInfo(title="Multi-IC Board"),
    )


async def _noop_review_with_ee_agent(chunks, system_prompt, model):
    """Mock _review_with_ee_agent that returns no findings."""
    return []


# ---------------------------------------------------------------------------
# Test datasheet_specs parameter acceptance
# ---------------------------------------------------------------------------
class TestDatasheetSpecsParameter:
    @pytest.mark.asyncio
    async def test_accepts_none(self):
        schematic = _make_schematic()

        with patch(
            "revlo.reviewer.engine._review_with_ee_agent",
            side_effect=_noop_review_with_ee_agent,
        ):
            report = await review_schematic(schematic, datasheet_specs=None)

        assert isinstance(report, ReviewReport)
        assert report.findings == []

    @pytest.mark.asyncio
    async def test_accepts_valid_specs_dict(self):
        schematic = _make_schematic()
        specs = {
            "U1": DatasheetSpec(
                mpn="STM32F103C8T6",
                manufacturer="STMicroelectronics",
                description="ARM Cortex-M3 MCU",
                supply_voltage_min=2.0,
                supply_voltage_max=3.6,
            )
        }

        with patch(
            "revlo.reviewer.engine._review_with_ee_agent",
            side_effect=_noop_review_with_ee_agent,
        ):
            report = await review_schematic(schematic, datasheet_specs=specs)

        assert isinstance(report, ReviewReport)


# ---------------------------------------------------------------------------
# Test spec injection into chunks
# ---------------------------------------------------------------------------
class TestSpecInjectionIntoChunks:
    @pytest.mark.asyncio
    async def test_specs_none_produces_empty_chunk_specs(self):
        schematic = _make_schematic()

        with (
            patch("revlo.reviewer.engine.chunk_schematic") as mock_chunk_schematic,
            patch(
                "revlo.reviewer.engine._review_with_ee_agent",
                side_effect=_noop_review_with_ee_agent,
            ),
        ):
            from revlo.reviewer.chunker import ReviewChunk

            test_chunk = ReviewChunk(
                chunk_type="ic_context",
                label="U1 - STM32F103",
                components=[schematic.components[0]],
            )
            mock_chunk_schematic.return_value = [test_chunk]

            await review_schematic(schematic, datasheet_specs=None)

            assert test_chunk.datasheet_specs == {}

    @pytest.mark.asyncio
    async def test_matching_specs_injected_into_chunk(self):
        schematic = _make_schematic()
        specs = {
            "U1": DatasheetSpec(
                mpn="STM32F103C8T6",
                manufacturer="STMicroelectronics",
                description="ARM Cortex-M3 MCU",
            )
        }

        with (
            patch("revlo.reviewer.engine.chunk_schematic") as mock_chunk_schematic,
            patch(
                "revlo.reviewer.engine._review_with_ee_agent",
                side_effect=_noop_review_with_ee_agent,
            ),
        ):
            from revlo.reviewer.chunker import ReviewChunk

            test_chunk = ReviewChunk(
                chunk_type="ic_context",
                label="U1 - STM32F103",
                components=[schematic.components[0]],
            )
            mock_chunk_schematic.return_value = [test_chunk]

            await review_schematic(schematic, datasheet_specs=specs)

            assert "U1" in test_chunk.datasheet_specs
            assert test_chunk.datasheet_specs["U1"] == specs["U1"]

    @pytest.mark.asyncio
    async def test_non_matching_specs_not_injected(self):
        schematic = _make_multi_ic_schematic()
        specs = {
            "U1": DatasheetSpec(mpn="STM32F103C8T6", manufacturer="STMicroelectronics"),
            "U2": DatasheetSpec(mpn="LM358", manufacturer="Texas Instruments"),
        }

        with (
            patch("revlo.reviewer.engine.chunk_schematic") as mock_chunk_schematic,
            patch(
                "revlo.reviewer.engine._review_with_ee_agent",
                side_effect=_noop_review_with_ee_agent,
            ),
        ):
            from revlo.reviewer.chunker import ReviewChunk

            chunk_u1 = ReviewChunk(
                chunk_type="ic_context",
                label="U1 - STM32F103",
                components=[schematic.components[0]],
            )
            chunk_u2 = ReviewChunk(
                chunk_type="ic_context",
                label="U2 - LM358",
                components=[schematic.components[1]],
            )
            mock_chunk_schematic.return_value = [chunk_u1, chunk_u2]

            await review_schematic(schematic, datasheet_specs=specs)

            assert "U1" in chunk_u1.datasheet_specs
            assert "U2" not in chunk_u1.datasheet_specs
            assert "U2" in chunk_u2.datasheet_specs
            assert "U1" not in chunk_u2.datasheet_specs

    @pytest.mark.asyncio
    async def test_chunk_with_multiple_components_gets_all_matching_specs(self):
        schematic = _make_multi_ic_schematic()
        specs = {
            "U1": DatasheetSpec(mpn="STM32F103C8T6", manufacturer="STMicroelectronics"),
            "U2": DatasheetSpec(mpn="LM358", manufacturer="Texas Instruments"),
            "C1": DatasheetSpec(mpn="Generic", manufacturer="Generic"),
        }

        with (
            patch("revlo.reviewer.engine.chunk_schematic") as mock_chunk_schematic,
            patch(
                "revlo.reviewer.engine._review_with_ee_agent",
                side_effect=_noop_review_with_ee_agent,
            ),
        ):
            from revlo.reviewer.chunker import ReviewChunk

            chunk = ReviewChunk(
                chunk_type="ic_context",
                label="U1 - STM32F103",
                components=[
                    schematic.components[0],  # U1
                    schematic.components[2],  # C1
                ],
            )
            mock_chunk_schematic.return_value = [chunk]

            await review_schematic(schematic, datasheet_specs=specs)

            assert "U1" in chunk.datasheet_specs
            assert "C1" in chunk.datasheet_specs
            assert "U2" not in chunk.datasheet_specs
