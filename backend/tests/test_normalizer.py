"""Tests for revlo.datasheet.normalizer — part number extraction and normalization."""

import pytest

from revlo.datasheet.normalizer import normalize_part, normalize_schematic_parts
from revlo.parser.models import ParsedComponent, ParsedSchematic


# -------------------------------------------------------------------------
# MPN Extraction: Explicit Property
# -------------------------------------------------------------------------


def test_mpn_from_explicit_mpn_property():
    comp = ParsedComponent(
        reference="U1",
        value="STM32F103CBT6",
        lib_id="MCU_ST_STM32:STM32F103CBTx",
        properties={"MPN": "STM32F103CBT6"},
    )
    normalized = normalize_part(comp)
    assert normalized.mpn == "STM32F103CBT6"
    assert normalized.raw_value == "STM32F103CBT6"


def test_mpn_from_manufacturer_part_number_property():
    comp = ParsedComponent(
        reference="U2",
        value="LM7805",
        lib_id="Regulator_Linear:LM7805",
        properties={"Manufacturer_Part_Number": "LM7805CT"},
    )
    normalized = normalize_part(comp)
    assert normalized.mpn == "LM7805CT"


def test_mpn_property_takes_priority_over_lib_id():
    comp = ParsedComponent(
        reference="U3",
        value="MCU",
        lib_id="MCU_ST_STM32:STM32F103CBT6",
        properties={"MPN": "STM32F103CBT6-CUSTOM"},
    )
    normalized = normalize_part(comp)
    assert normalized.mpn == "STM32F103CBT6-CUSTOM"


# -------------------------------------------------------------------------
# MPN Extraction: lib_id Colon Suffix
# -------------------------------------------------------------------------


def test_mpn_from_lib_id_colon_suffix():
    comp = ParsedComponent(
        reference="U4",
        value="STM32F103CBT6",
        lib_id="MCU_ST_STM32:STM32F103CBT6",
    )
    normalized = normalize_part(comp)
    assert normalized.mpn == "STM32F103CBT6"


def test_lib_id_without_colon_falls_back_to_value():
    comp = ParsedComponent(
        reference="R1",
        value="10k",
        lib_id="Device",
    )
    normalized = normalize_part(comp)
    assert normalized.mpn == "10k"


def test_lib_id_with_empty_suffix_falls_back_to_value():
    comp = ParsedComponent(
        reference="C1",
        value="100nF",
        lib_id="Device:",
    )
    normalized = normalize_part(comp)
    assert normalized.mpn == "100nF"


# -------------------------------------------------------------------------
# MPN Extraction: Fallback to Value
# -------------------------------------------------------------------------


def test_mpn_fallback_to_value_when_no_property_or_lib_id_suffix():
    comp = ParsedComponent(
        reference="R2",
        value="4.7k",
        lib_id="Device",
    )
    normalized = normalize_part(comp)
    assert normalized.mpn == "4.7k"


def test_mpn_strips_whitespace():
    comp = ParsedComponent(
        reference="U5",
        value="LM7805",
        lib_id="Regulator_Linear:LM7805",
        properties={"MPN": "  LM7805CT  "},
    )
    normalized = normalize_part(comp)
    assert normalized.mpn == "LM7805CT"


# -------------------------------------------------------------------------
# Datasheet URL Extraction
# -------------------------------------------------------------------------


def test_datasheet_url_extracted_from_properties():
    comp = ParsedComponent(
        reference="U6",
        value="STM32F103CBT6",
        lib_id="MCU_ST_STM32:STM32F103CBT6",
        properties={"Datasheet": "https://www.st.com/resource/en/datasheet/stm32f103.pdf"},
    )
    normalized = normalize_part(comp)
    assert normalized.datasheet_url == "https://www.st.com/resource/en/datasheet/stm32f103.pdf"


def test_datasheet_url_http_accepted():
    comp = ParsedComponent(
        reference="U7",
        value="LM7805",
        lib_id="Regulator_Linear:LM7805",
        properties={"Datasheet": "http://www.ti.com/lit/ds/symlink/lm7805.pdf"},
    )
    normalized = normalize_part(comp)
    assert normalized.datasheet_url == "http://www.ti.com/lit/ds/symlink/lm7805.pdf"


def test_datasheet_url_not_extracted_from_non_http():
    comp = ParsedComponent(
        reference="R3",
        value="10k",
        lib_id="Device:R",
        properties={"Datasheet": "~"},
    )
    normalized = normalize_part(comp)
    assert normalized.datasheet_url is None


def test_datasheet_url_missing_property_returns_none():
    comp = ParsedComponent(
        reference="C2",
        value="100nF",
        lib_id="Device:C",
    )
    normalized = normalize_part(comp)
    assert normalized.datasheet_url is None


# -------------------------------------------------------------------------
# Generic Part Detection: lib_id Prefix
# -------------------------------------------------------------------------


def test_generic_detected_from_device_lib_id_prefix():
    comp = ParsedComponent(
        reference="R4",
        value="10k",
        lib_id="Device:R",
    )
    normalized = normalize_part(comp)
    assert normalized.is_generic is True


def test_generic_detected_from_power_lib_id_prefix():
    comp = ParsedComponent(
        reference="#PWR01",
        value="GND",
        lib_id="power:GND",
    )
    normalized = normalize_part(comp)
    assert normalized.is_generic is True


# -------------------------------------------------------------------------
# Generic Part Detection: Passive Ref + Simple Value
# -------------------------------------------------------------------------


def test_generic_resistor_with_simple_value():
    comp = ParsedComponent(
        reference="R5",
        value="10k",
        lib_id="Custom:R",
    )
    normalized = normalize_part(comp)
    assert normalized.is_generic is True


def test_generic_capacitor_with_simple_value():
    comp = ParsedComponent(
        reference="C3",
        value="100nF",
        lib_id="Custom:C",
    )
    normalized = normalize_part(comp)
    assert normalized.is_generic is True


def test_generic_inductor_with_simple_value():
    comp = ParsedComponent(
        reference="L1",
        value="10uH",
        lib_id="Custom:L",
    )
    normalized = normalize_part(comp)
    assert normalized.is_generic is True


def test_generic_diode_with_simple_value():
    comp = ParsedComponent(
        reference="D1",
        value="LED",
        lib_id="Device:LED",
    )
    normalized = normalize_part(comp)
    assert normalized.is_generic is True


def test_generic_resistor_with_decimal_value():
    comp = ParsedComponent(
        reference="R6",
        value="4.7k",
        lib_id="Custom:R",
    )
    normalized = normalize_part(comp)
    assert normalized.is_generic is True


def test_generic_capacitor_with_whitespace_in_value():
    comp = ParsedComponent(
        reference="C4",
        value="10 uF",
        lib_id="Custom:C",
    )
    normalized = normalize_part(comp)
    assert normalized.is_generic is True


# -------------------------------------------------------------------------
# Non-Generic Part Detection
# -------------------------------------------------------------------------


def test_non_generic_ic_with_complex_value():
    comp = ParsedComponent(
        reference="U8",
        value="STM32F103CBT6",
        lib_id="MCU_ST_STM32:STM32F103CBT6",
    )
    normalized = normalize_part(comp)
    assert normalized.is_generic is False


def test_non_generic_resistor_with_mpn_like_value():
    comp = ParsedComponent(
        reference="R7",
        value="ERJ-6ENF1002V",
        lib_id="Resistor_SMD:R_0603",
    )
    normalized = normalize_part(comp)
    assert normalized.is_generic is False


def test_non_generic_capacitor_with_mpn_like_value():
    comp = ParsedComponent(
        reference="C5",
        value="GRM188R71C104KA01D",
        lib_id="Capacitor_SMD:C_0603",
    )
    normalized = normalize_part(comp)
    assert normalized.is_generic is False


def test_connector_is_generic_by_lib_id():
    comp = ParsedComponent(
        reference="J1",
        value="USB-C",
        lib_id="Connector:USB_C",
    )
    normalized = normalize_part(comp)
    assert normalized.is_generic is True


def test_non_generic_ic():
    comp = ParsedComponent(
        reference="U11",
        value="TPS62160",
        lib_id="Regulator_Switching:TPS62160",
    )
    normalized = normalize_part(comp)
    assert normalized.is_generic is False


# -------------------------------------------------------------------------
# Manufacturer Extraction
# -------------------------------------------------------------------------


def test_manufacturer_extracted_from_properties():
    comp = ParsedComponent(
        reference="U9",
        value="STM32F103CBT6",
        lib_id="MCU_ST_STM32:STM32F103CBT6",
        properties={"Manufacturer": "STMicroelectronics"},
    )
    normalized = normalize_part(comp)
    assert normalized.manufacturer == "STMicroelectronics"


def test_manufacturer_empty_when_not_provided():
    comp = ParsedComponent(
        reference="U10",
        value="LM7805",
        lib_id="Regulator_Linear:LM7805",
    )
    normalized = normalize_part(comp)
    assert normalized.manufacturer == ""


# -------------------------------------------------------------------------
# Batch Processing: normalize_schematic_parts
# -------------------------------------------------------------------------


def test_normalize_schematic_parts_empty():
    schematic = ParsedSchematic(components=[])
    normalized = normalize_schematic_parts(schematic)
    assert normalized == []


def test_normalize_schematic_parts_single_component():
    comp = ParsedComponent(
        reference="R1",
        value="10k",
        lib_id="Device:R",
    )
    schematic = ParsedSchematic(components=[comp])
    normalized = normalize_schematic_parts(schematic)
    assert len(normalized) == 1
    assert normalized[0].mpn == "R"
    assert normalized[0].is_generic is True


def test_normalize_schematic_parts_multiple_components():
    comp1 = ParsedComponent(
        reference="R1",
        value="10k",
        lib_id="Device:R",
    )
    comp2 = ParsedComponent(
        reference="C1",
        value="100nF",
        lib_id="Device:C",
    )
    comp3 = ParsedComponent(
        reference="U1",
        value="STM32F103CBT6",
        lib_id="MCU_ST_STM32:STM32F103CBT6",
        properties={"Manufacturer": "STMicroelectronics"},
    )
    schematic = ParsedSchematic(components=[comp1, comp2, comp3])
    normalized = normalize_schematic_parts(schematic)
    assert len(normalized) == 3
    assert normalized[0].is_generic is True
    assert normalized[1].is_generic is True
    assert normalized[2].is_generic is False
    assert normalized[2].manufacturer == "STMicroelectronics"


def test_normalize_schematic_parts_preserves_order():
    comp1 = ParsedComponent(reference="U1", value="MCU1", lib_id="MCU:MCU1")
    comp2 = ParsedComponent(reference="U2", value="MCU2", lib_id="MCU:MCU2")
    comp3 = ParsedComponent(reference="U3", value="MCU3", lib_id="MCU:MCU3")
    schematic = ParsedSchematic(components=[comp1, comp2, comp3])
    normalized = normalize_schematic_parts(schematic)
    assert [n.mpn for n in normalized] == ["MCU1", "MCU2", "MCU3"]


# -------------------------------------------------------------------------
# Edge Cases
# -------------------------------------------------------------------------


def test_empty_value_handled():
    comp = ParsedComponent(
        reference="R8",
        value="",
        lib_id="Device:R",
    )
    normalized = normalize_part(comp)
    assert normalized.mpn == "R"
    assert normalized.raw_value == ""


def test_multi_letter_reference_prefix():
    comp = ParsedComponent(
        reference="LED1",
        value="Red",
        lib_id="Device:LED",
    )
    normalized = normalize_part(comp)
    assert normalized.mpn == "LED"


def test_reference_with_no_number():
    comp = ParsedComponent(
        reference="R",
        value="10k",
        lib_id="Device:R",
    )
    normalized = normalize_part(comp)
    assert normalized.is_generic is True


def test_value_with_mixed_case_units():
    comp = ParsedComponent(
        reference="C6",
        value="10UF",
        lib_id="Device:C",
    )
    normalized = normalize_part(comp)
    assert normalized.is_generic is True


def test_value_with_ohm_symbol():
    comp = ParsedComponent(
        reference="R9",
        value="100R",
        lib_id="Device:R",
    )
    normalized = normalize_part(comp)
    assert normalized.is_generic is True


# -------------------------------------------------------------------------
# Generic Part Detection: New lib_id Prefixes
# -------------------------------------------------------------------------


def test_generic_connector_generic_lib_id():
    comp = ParsedComponent(
        reference="J2",
        value="Conn_01x04",
        lib_id="Connector_Generic:Conn_01x04",
    )
    normalized = normalize_part(comp)
    assert normalized.is_generic is True


def test_generic_mounting_hole_lib_id():
    comp = ParsedComponent(
        reference="H1",
        value="MountingHole",
        lib_id="MountingHole:MountingHole_3.2mm",
    )
    normalized = normalize_part(comp)
    assert normalized.is_generic is True


def test_generic_mechanical_lib_id():
    comp = ParsedComponent(
        reference="MP1",
        value="Heatsink",
        lib_id="Mechanical:Heatsink",
    )
    normalized = normalize_part(comp)
    assert normalized.is_generic is True


def test_generic_test_point_lib_id():
    comp = ParsedComponent(
        reference="TP1",
        value="TestPoint",
        lib_id="TestPoint:TestPoint",
    )
    normalized = normalize_part(comp)
    assert normalized.is_generic is True


def test_generic_jumper_lib_id():
    comp = ParsedComponent(
        reference="JP1",
        value="SolderJumper_2_Open",
        lib_id="Jumper:SolderJumper_2_Open",
    )
    normalized = normalize_part(comp)
    assert normalized.is_generic is True


# -------------------------------------------------------------------------
# Generic Part Detection: _SKIP_REF_PREFIXES
# -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ref,value,lib_id",
    [
        ("H1", "MountingHole", "Custom:MountingHole"),
        ("MH1", "MountingHole", "Custom:MH"),
        ("J3", "USB-C", "Custom:USB_C"),
        ("P1", "Header_2x10", "Custom:Header"),
        ("TP2", "TestPoint", "Custom:TP"),
        ("JP2", "Jumper", "Custom:JP"),
        ("F1", "500mA", "Custom:Fuse"),
        ("FB1", "600R@100MHz", "Custom:FB"),
        ("SW1", "Push", "Custom:SW"),
        ("BT1", "CR2032", "Custom:Battery"),
        ("MP2", "Fiducial", "Custom:Fiducial"),
    ],
)
def test_generic_by_ref_prefix(ref, value, lib_id):
    """Parts with skip-ref prefixes are always generic regardless of lib_id."""
    comp = ParsedComponent(
        reference=ref,
        value=value,
        lib_id=lib_id,
    )
    normalized = normalize_part(comp)
    assert normalized.is_generic is True


def test_skip_ref_prefix_with_multi_digit_number():
    """Ref prefix extraction handles multi-digit suffixes."""
    comp = ParsedComponent(
        reference="J123",
        value="SomeConnector",
        lib_id="Custom:Conn",
    )
    normalized = normalize_part(comp)
    assert normalized.is_generic is True


def test_non_skip_ref_prefix_still_non_generic():
    """A component with a non-skip, non-passive ref is still non-generic."""
    comp = ParsedComponent(
        reference="U12",
        value="STM32F411",
        lib_id="MCU_ST_STM32:STM32F411",
    )
    normalized = normalize_part(comp)
    assert normalized.is_generic is False


def test_passive_ref_with_mpn_value_still_non_generic():
    """A resistor with a part-number value (not simple passive) stays non-generic."""
    comp = ParsedComponent(
        reference="R10",
        value="ERJ-6ENF1002V",
        lib_id="Resistor_SMD:R_0603",
    )
    normalized = normalize_part(comp)
    assert normalized.is_generic is False
