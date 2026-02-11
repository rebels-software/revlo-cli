"""Pydantic v2 models for the datasheet intelligence pipeline."""

from __future__ import annotations

from pydantic import BaseModel, Field


class NormalizedPartNumber(BaseModel):
    raw_value: str
    mpn: str
    manufacturer: str = ""
    is_generic: bool = False
    datasheet_url: str | None = None


class PinFunction(BaseModel):
    pin_number: str
    name: str
    function_description: str = ""
    electrical_type: str = ""


class DatasheetSpec(BaseModel):
    mpn: str
    manufacturer: str = ""
    description: str = ""
    supply_voltage_min: float | None = None
    supply_voltage_max: float | None = None
    max_current: float | None = None
    pin_functions: list[PinFunction] = Field(default_factory=list)
    absolute_max_ratings: dict[str, str] = Field(default_factory=dict)
    recommended_operating: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class DatasheetCacheEntry(BaseModel):
    mpn: str
    spec: DatasheetSpec | None = None
    pdf_path: str | None = None
    pdf_sha256: str | None = None
    source_url: str = ""
    fetched_at: str = ""
    expires_at: str = ""
