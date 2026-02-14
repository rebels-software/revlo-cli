"""Test suite for US-020: Chunk enrichment + enhanced prompts with datasheet specs."""

from revlo.datasheet.models import DatasheetSpec, PinFunction
from revlo.parser.models import ParsedComponent
from revlo.reviewer.chunker import ReviewChunk
from revlo.reviewer.prompts import build_review_prompt, format_chunk_data


# ---------------------------------------------------------------------------
# Test ReviewChunk.datasheet_specs field
# ---------------------------------------------------------------------------
class TestReviewChunkDatasheetSpecs:
    """Test the new datasheet_specs field on ReviewChunk."""

    def test_datasheet_specs_defaults_to_empty_dict(self):
        """ReviewChunk.datasheet_specs defaults to empty dict (backward compatible)."""
        chunk = ReviewChunk(chunk_type="ic_context", label="U1 - STM32")
        assert chunk.datasheet_specs == {}

    def test_datasheet_specs_accepts_dict(self):
        """ReviewChunk can accept datasheet_specs dict with DatasheetSpec values."""
        spec = DatasheetSpec(mpn="STM32F103CBT6", manufacturer="STMicroelectronics")
        chunk = ReviewChunk(
            chunk_type="ic_context",
            label="U1 - STM32",
            datasheet_specs={"U1": spec},
        )
        assert "U1" in chunk.datasheet_specs
        assert chunk.datasheet_specs["U1"].mpn == "STM32F103CBT6"



# ---------------------------------------------------------------------------
# Test format_chunk_data with datasheet specs
# ---------------------------------------------------------------------------
class TestFormatChunkDataWithSpecs:
    """Test that format_chunk_data renders datasheet spec section correctly."""

    def testformat_chunk_data_no_specs(self):
        """No datasheet section when datasheet_specs is empty."""
        chunk = ReviewChunk(
            chunk_type="ic_context",
            label="U1 - STM32",
            components=[
                ParsedComponent(reference="U1", value="STM32", lib_id="MCU:STM32")
            ],
        )
        output = format_chunk_data(chunk)
        assert "## Datasheet Specifications" not in output

    def testformat_chunk_data_with_minimal_spec(self):
        """Datasheet section appears with minimal spec (only mpn)."""
        spec = DatasheetSpec(mpn="LM358")
        chunk = ReviewChunk(
            chunk_type="ic_context",
            label="U2 - LM358",
            datasheet_specs={"U2": spec},
        )
        output = format_chunk_data(chunk)
        assert "## Datasheet Specifications" in output
        assert "### U2: LM358" in output

    def testformat_chunk_data_with_full_spec(self):
        """Datasheet section includes all fields when populated."""
        spec = DatasheetSpec(
            mpn="STM32F103CBT6",
            manufacturer="STMicroelectronics",
            description="ARM Cortex-M3 MCU",
            supply_voltage_min=2.0,
            supply_voltage_max=3.6,
            max_current=0.15,
            absolute_max_ratings={"VDD": "4.0V"},
            recommended_operating={"Temp": "-40°C to 85°C"},
            pin_functions=[
                PinFunction(
                    pin_number="1",
                    name="VBAT",
                    function_description="Battery backup",
                    electrical_type="power_in",
                )
            ],
            notes=["Requires external HSE crystal for USB"],
        )
        chunk = ReviewChunk(
            chunk_type="ic_context",
            label="U1 - STM32",
            datasheet_specs={"U1": spec},
        )
        output = format_chunk_data(chunk)
        assert "## Datasheet Specifications" in output
        assert "### U1: STM32F103CBT6" in output
        assert "- Manufacturer: STMicroelectronics" in output
        assert "- Description: ARM Cortex-M3 MCU" in output
        assert "- Supply Voltage: 2.0V to 3.6V" in output
        assert "- Max Current: 0.15A" in output
        assert "- Absolute Max Ratings:" in output
        assert "  - VDD: 4.0V" in output
        assert "- Recommended Operating:" in output
        assert "  - Temp: -40°C to 85°C" in output
        assert "- Pin Functions:" in output
        assert "  - Pin 1 (VBAT) [power_in] — Battery backup" in output
        assert "- Notes:" in output
        assert "  - Requires external HSE crystal for USB" in output

    def testformat_chunk_data_partial_voltage_range(self):
        """Datasheet section renders '?' for missing voltage bounds."""
        spec_min_only = DatasheetSpec(mpn="PART1", supply_voltage_min=1.8)
        chunk = ReviewChunk(
            chunk_type="ic_context",
            label="U1 - PART1",
            datasheet_specs={"U1": spec_min_only},
        )
        output = format_chunk_data(chunk)
        assert "- Supply Voltage: 1.8V to ?V" in output

        spec_max_only = DatasheetSpec(mpn="PART2", supply_voltage_max=5.5)
        chunk2 = ReviewChunk(
            chunk_type="ic_context",
            label="U2 - PART2",
            datasheet_specs={"U2": spec_max_only},
        )
        output2 = format_chunk_data(chunk2)
        assert "- Supply Voltage: ?V to 5.5V" in output2

    def testformat_chunk_data_multiple_specs_sorted(self):
        """Multiple component specs are rendered sorted by reference."""
        spec_u1 = DatasheetSpec(mpn="IC1")
        spec_u3 = DatasheetSpec(mpn="IC3")
        spec_u2 = DatasheetSpec(mpn="IC2")
        chunk = ReviewChunk(
            chunk_type="power_rail",
            label="Power Rail: VCC",
            datasheet_specs={"U1": spec_u1, "U3": spec_u3, "U2": spec_u2},
        )
        output = format_chunk_data(chunk)
        # Check that U1, U2, U3 appear in order
        u1_idx = output.find("### U1: IC1")
        u2_idx = output.find("### U2: IC2")
        u3_idx = output.find("### U3: IC3")
        assert u1_idx < u2_idx < u3_idx


# ---------------------------------------------------------------------------
# Test prompt builders with datasheet verification instruction
# ---------------------------------------------------------------------------
class TestPromptWithDatasheetVerification:
    """Test that prompts conditionally include datasheet verification instructions."""

    def test_ic_context_prompt_no_specs_no_instruction(self):
        """IC-context prompt without specs omits datasheet verification instruction."""
        chunk = ReviewChunk(
            chunk_type="ic_context",
            label="U1 - STM32",
            components=[
                ParsedComponent(reference="U1", value="STM32", lib_id="MCU:STM32")
            ],
        )
        prompt = build_review_prompt(chunk)
        assert "If datasheet specifications are provided" not in prompt
        assert "Component values match datasheet" not in prompt

    def test_ic_context_prompt_with_specs_includes_instruction(self):
        """IC-context prompt with specs includes datasheet verification instruction."""
        spec = DatasheetSpec(mpn="LM358")
        chunk = ReviewChunk(
            chunk_type="ic_context",
            label="U2 - LM358",
            components=[
                ParsedComponent(reference="U2", value="LM358", lib_id="Amplifier:LM358")
            ],
            datasheet_specs={"U2": spec},
        )
        prompt = build_review_prompt(chunk)
        assert "If datasheet specifications are provided" in prompt
        assert "Component values match datasheet recommended values" in prompt
        assert "Pin connections match datasheet pin functions" in prompt
        assert "Operating conditions are within datasheet limits" in prompt
        assert "Required external components (caps, resistors) are present per datasheet" in prompt

    def test_power_rail_prompt_no_specs_no_instruction(self):
        """Power-rail prompt without specs omits datasheet verification instruction."""
        chunk = ReviewChunk(
            chunk_type="power_rail",
            label="Power Rail: VCC",
            components=[
                ParsedComponent(reference="C1", value="100nF", lib_id="Device:C")
            ],
        )
        prompt = build_review_prompt(chunk)
        assert "If datasheet specifications are provided" not in prompt

    def test_power_rail_prompt_with_specs_includes_instruction(self):
        """Power-rail prompt with specs includes datasheet verification instruction."""
        spec = DatasheetSpec(mpn="AMS1117", supply_voltage_max=15.0)
        chunk = ReviewChunk(
            chunk_type="power_rail",
            label="Power Rail: 3V3",
            components=[
                ParsedComponent(reference="U1", value="AMS1117", lib_id="Regulator:AMS1117")
            ],
            datasheet_specs={"U1": spec},
        )
        prompt = build_review_prompt(chunk)
        assert "If datasheet specifications are provided" in prompt
        assert "Component values match datasheet recommended values" in prompt
