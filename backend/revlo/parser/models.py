"""Pydantic v2 models for parsed KiCad schematic output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ParsedPin(BaseModel):
    number: str
    name: str
    position: tuple[float, float] = (0.0, 0.0)
    electrical_type: str = "unspecified"
    connected_net: str | None = None


class PinConnection(BaseModel):
    component_ref: str
    pin_number: str
    pin_name: str = ""


class ParsedComponent(BaseModel):
    reference: str
    value: str
    lib_id: str
    footprint: str = ""
    position: tuple[float, float] = (0.0, 0.0)
    rotation: float = 0.0
    pins: list[ParsedPin] = Field(default_factory=list)
    properties: dict[str, str] = Field(default_factory=dict)
    source_sheet: str = ""


class ParsedNet(BaseModel):
    name: str
    pins: list[PinConnection] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    is_power: bool = False


class ParsedSheet(BaseModel):
    name: str
    filename: str
    pins: list[dict[str, str]] = Field(default_factory=list)


class TitleBlockInfo(BaseModel):
    title: str = ""
    date: str = ""
    revision: str = ""
    company: str = ""


class ParsedSchematic(BaseModel):
    components: list[ParsedComponent] = Field(default_factory=list)
    nets: list[ParsedNet] = Field(default_factory=list)
    power_symbols: list[ParsedComponent] = Field(default_factory=list)
    sheets: list[ParsedSheet] = Field(default_factory=list)
    unconnected_pins: list[PinConnection] = Field(default_factory=list)
    title_block: TitleBlockInfo = Field(default_factory=TitleBlockInfo)
