"""Tests for revlo.datasheet.models — Pydantic v2 models for datasheet intelligence pipeline."""

import json

import pytest
from pydantic import ValidationError

from revlo.datasheet import (
    DatasheetCacheEntry,
    DatasheetSpec,
    NormalizedPartNumber,
    PinFunction,
)


# -------------------------------------------------------------------------
# NormalizedPartNumber
# -------------------------------------------------------------------------


def test_normalized_part_number_defaults():
    npn = NormalizedPartNumber(raw_value="STM32F103C8T6", mpn="STM32F103C8T6")
    assert npn.manufacturer == ""
    assert npn.is_generic is False
    assert npn.datasheet_url is None


def test_normalized_part_number_generic():
    npn = NormalizedPartNumber(raw_value="10k", mpn="R_Generic", is_generic=True)
    assert npn.is_generic is True
    assert npn.datasheet_url is None


def test_normalized_part_number_requires_fields():
    with pytest.raises(ValidationError):
        NormalizedPartNumber(raw_value="R1")


# -------------------------------------------------------------------------
# PinFunction
# -------------------------------------------------------------------------


def test_pin_function_defaults():
    pf = PinFunction(pin_number="1", name="VDD")
    assert pf.function_description == ""
    assert pf.electrical_type == ""


def test_pin_function_requires_fields():
    with pytest.raises(ValidationError):
        PinFunction(pin_number="1")


# -------------------------------------------------------------------------
# DatasheetSpec
# -------------------------------------------------------------------------


def test_datasheet_spec_minimal():
    spec = DatasheetSpec(mpn="STM32F103C8T6")
    assert spec.supply_voltage_min is None
    assert spec.supply_voltage_max is None
    assert spec.max_current is None
    assert spec.pin_functions == []
    assert spec.absolute_max_ratings == {}
    assert spec.recommended_operating == {}
    assert spec.notes == []


def test_datasheet_spec_full():
    spec = DatasheetSpec(
        mpn="STM32F103C8T6",
        manufacturer="STMicroelectronics",
        description="ARM Cortex-M3 MCU",
        supply_voltage_min=2.0,
        supply_voltage_max=3.6,
        max_current=150.0,
        pin_functions=[PinFunction(pin_number="1", name="VBAT", electrical_type="Power")],
        absolute_max_ratings={"VDD": "-0.3 to 4.0V"},
        recommended_operating={"VDD": "2.0 to 3.6V"},
        notes=["Crystal required for USB"],
    )
    assert spec.supply_voltage_min == 2.0
    assert len(spec.pin_functions) == 1
    assert spec.absolute_max_ratings["VDD"] == "-0.3 to 4.0V"


def test_datasheet_spec_requires_mpn():
    with pytest.raises(ValidationError):
        DatasheetSpec()


# -------------------------------------------------------------------------
# DatasheetCacheEntry
# -------------------------------------------------------------------------


def test_cache_entry_defaults():
    entry = DatasheetCacheEntry(mpn="STM32F103C8T6")
    assert entry.spec is None
    assert entry.pdf_path is None
    assert entry.pdf_sha256 is None
    assert entry.source_url == ""
    assert entry.fetched_at == ""
    assert entry.expires_at == ""


def test_cache_entry_with_nested_spec():
    spec = DatasheetSpec(mpn="LM7805", manufacturer="TI")
    entry = DatasheetCacheEntry(
        mpn="LM7805",
        spec=spec,
        pdf_path="/cache/lm7805.pdf",
        pdf_sha256="abc123",
        source_url="https://example.com/lm7805.pdf",
        fetched_at="2026-02-11T10:00:00Z",
        expires_at="2026-05-12T10:00:00Z",
    )
    assert entry.spec.manufacturer == "TI"
    assert entry.pdf_sha256 == "abc123"


def test_cache_entry_requires_mpn():
    with pytest.raises(ValidationError):
        DatasheetCacheEntry()


# -------------------------------------------------------------------------
# JSON round-trip
# -------------------------------------------------------------------------


def test_json_round_trip():
    spec = DatasheetSpec(
        mpn="LM7805",
        pin_functions=[PinFunction(pin_number="1", name="IN")],
        notes=["Heatsink required"],
    )
    entry = DatasheetCacheEntry(mpn="LM7805", spec=spec, pdf_path="/cache/lm7805.pdf")
    restored = DatasheetCacheEntry(**json.loads(entry.model_dump_json()))
    assert restored.spec.mpn == "LM7805"
    assert len(restored.spec.pin_functions) == 1


# -------------------------------------------------------------------------
# Package exports
# -------------------------------------------------------------------------


def test_package_exports():
    from revlo import datasheet

    expected = {"DatasheetCacheEntry", "DatasheetSpec", "NormalizedPartNumber", "PinFunction"}
    assert set(datasheet.__all__) == expected
