"""Main schematic parser using kicad-sch-api.

Loads a .kicad_sch file and returns a fully populated ParsedSchematic model.
"""

from __future__ import annotations

import logging
from pathlib import Path

import kicad_sch_api as ksa

from revlo.parser.connectivity import build_net_list
from revlo.parser.models import (
    ParsedComponent,
    ParsedPin,
    ParsedSchematic,
    ParsedSheet,
    TitleBlockInfo,
)

logger = logging.getLogger(__name__)


def parse_schematic(path: str) -> ParsedSchematic:
    """Parse a KiCad schematic file into a structured ParsedSchematic model.

    Args:
        path: Filesystem path to a .kicad_sch file.

    Returns:
        A fully populated ParsedSchematic instance.

    Raises:
        FileNotFoundError: If the schematic file does not exist.
        kicad_sch_api.ValidationError: If the file cannot be parsed.
    """
    sch_path = Path(path)
    if not sch_path.exists():
        raise FileNotFoundError(f"Schematic file not found: {path}")

    sch = ksa.Schematic.load(str(sch_path))

    title_block = _extract_title_block(sch)
    components, power_symbols = _extract_components(sch)
    nets, unconnected_pins = build_net_list(sch, components + power_symbols)
    sheets = _extract_sheets(sch)

    return ParsedSchematic(
        components=components,
        nets=nets,
        power_symbols=power_symbols,
        sheets=sheets,
        unconnected_pins=unconnected_pins,
        title_block=title_block,
    )


def _extract_title_block(sch: ksa.Schematic) -> TitleBlockInfo:
    """Extract title block metadata from the schematic."""
    tb = sch.title_block or {}
    return TitleBlockInfo(
        title=tb.get("title", ""),
        date=tb.get("date", ""),
        revision=tb.get("rev", ""),
        company=tb.get("company", ""),
    )


def _extract_components(
    sch: ksa.Schematic,
) -> tuple[list[ParsedComponent], list[ParsedComponent]]:
    """Extract components and separate power symbols.

    Returns:
        A tuple of (regular_components, power_symbols).
    """
    components: list[ParsedComponent] = []
    power_symbols: list[ParsedComponent] = []

    for comp in sch.components:
        pins = _extract_pins(sch, comp)

        parsed = ParsedComponent(
            reference=comp.reference,
            value=comp.value,
            lib_id=comp.lib_id,
            footprint=comp.footprint or "",
            position=(comp.position.x, comp.position.y),
            rotation=comp.rotation,
            pins=pins,
            properties=dict(comp.properties) if comp.properties else {},
        )

        if comp.reference.startswith("#PWR"):
            power_symbols.append(parsed)
        else:
            components.append(parsed)

    return components, power_symbols


def _extract_pins(sch: ksa.Schematic, comp: ksa.Component) -> list[ParsedPin]:
    """Extract pin data for a single component, including net connectivity."""
    parsed_pins: list[ParsedPin] = []

    for pin in comp.pins:
        # Get absolute pin position
        pin_pos = comp.get_pin_position(pin.number)
        position = (pin_pos.x, pin_pos.y) if pin_pos else (0.0, 0.0)

        # Determine connected net
        connected_net: str | None = None
        try:
            net = sch.get_net_for_pin(comp.reference, pin.number)
            if net is not None:
                connected_net = net.name
        except Exception:
            logger.debug(
                "Could not resolve net for %s pin %s",
                comp.reference,
                pin.number,
            )

        parsed_pins.append(
            ParsedPin(
                number=pin.number,
                name=pin.name,
                position=position,
                electrical_type=pin.pin_type.value
                if hasattr(pin.pin_type, "value")
                else str(pin.pin_type),
                connected_net=connected_net,
            )
        )

    return parsed_pins


def _extract_sheets(sch: ksa.Schematic) -> list[ParsedSheet]:
    """Extract hierarchical sheet information from the schematic."""
    sheets: list[ParsedSheet] = []

    # Sheets are stored in the raw data dict.
    raw_sheets = sch._data.get("sheets", [])
    for sheet_data in raw_sheets:
        name = sheet_data.get("name", "")
        filename = sheet_data.get("filename", "")
        raw_pins = sheet_data.get("pins", [])

        # Normalise pin data to list[dict[str, str]].
        pins: list[dict[str, str]] = []
        for rp in raw_pins:
            if isinstance(rp, dict):
                pins.append({k: str(v) for k, v in rp.items()})

        sheets.append(
            ParsedSheet(
                name=name,
                filename=filename,
                pins=pins,
            )
        )

    return sheets
