"""Schematic query tools for Ask mode -- lets Opus explore the design."""

from __future__ import annotations

from typing import Any

from revlo.datasheet.models import DatasheetSpec
from revlo.parser.models import ParsedSchematic


SCHEMATIC_TOOLS = [
    {
        "name": "lookup_component",
        "description": (
            "Look up a component by reference designator (e.g. U1, R4, C10). "
            "Returns all pin connections, nets, footprint, properties, and "
            "datasheet specs if available."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    "description": "Component reference designator, e.g. 'U1', 'R4', 'C10'",
                },
            },
            "required": ["ref"],
        },
    },
    {
        "name": "trace_net",
        "description": (
            "Trace a net by name to see every component and pin connected to it. "
            "Use this to understand signal paths and connectivity."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "net_name": {
                    "type": "string",
                    "description": "Net name, e.g. 'VCC', 'USB_D+', 'NRST'",
                },
            },
            "required": ["net_name"],
        },
    },
    {
        "name": "find_unconnected_pins",
        "description": "Find floating/unconnected pins. Optionally filter by component reference.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    "description": "Optional: filter by component reference",
                },
            },
            "required": [],
        },
    },
    {
        "name": "list_power_rails",
        "description": (
            "List all power nets (VCC, GND, +3V3, etc.) with the "
            "components connected to each."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


def execute_tool(
    name: str,
    args: dict[str, Any],
    schematic: ParsedSchematic,
    specs: dict[str, DatasheetSpec] | None = None,
) -> str:
    """Execute a schematic query tool and return a text result."""
    specs = specs or {}
    if name == "lookup_component":
        return _lookup_component(args.get("ref", ""), schematic, specs)
    elif name == "trace_net":
        return _trace_net(args.get("net_name", ""), schematic)
    elif name == "find_unconnected_pins":
        return _find_unconnected(args.get("ref"), schematic)
    elif name == "list_power_rails":
        return _list_power_rails(schematic)
    return f"Unknown tool: {name}"


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _lookup_component(
    ref: str,
    schematic: ParsedSchematic,
    specs: dict[str, DatasheetSpec],
) -> str:
    """Look up a component by reference designator."""
    ref_upper = ref.strip().upper()

    # Search components and power symbols
    comp = None
    for c in schematic.components:
        if c.reference.upper() == ref_upper:
            comp = c
            break
    if comp is None:
        for c in schematic.power_symbols:
            if c.reference.upper() == ref_upper:
                comp = c
                break
    if comp is None:
        return f"Component '{ref}' not found in schematic."

    lines: list[str] = []
    lines.append(f"{comp.reference}: {comp.value}")
    if comp.footprint:
        lines.append(f"Footprint: {comp.footprint}")
    if comp.source_sheet:
        lines.append(f"Source sheet: {comp.source_sheet}")

    # Build a net lookup: (ref, pin_number) -> net_name
    net_map: dict[tuple[str, str], str] = {}
    net_type_map: dict[str, bool] = {}
    for net in schematic.nets:
        net_type_map[net.name] = net.is_power
        for pin_conn in net.pins:
            net_map[(pin_conn.component_ref.upper(), pin_conn.pin_number)] = net.name

    # Build unconnected set
    unconnected: set[tuple[str, str]] = set()
    for uc in schematic.unconnected_pins:
        unconnected.add((uc.component_ref.upper(), uc.pin_number))

    # Pins
    if comp.pins:
        lines.append(f"Pins ({len(comp.pins)}):")
        for pin in comp.pins:
            key = (ref_upper, pin.number)
            net_name = net_map.get(key) or pin.connected_net
            if net_name:
                power_tag = " [power]" if net_type_map.get(net_name, False) else ""
                name_part = f" ({pin.name})" if pin.name else ""
                lines.append(f"  {pin.number}{name_part} -> net {net_name}{power_tag}")
            elif key in unconnected:
                name_part = f" ({pin.name})" if pin.name else ""
                lines.append(f"  {pin.number}{name_part} -> unconnected")
            else:
                name_part = f" ({pin.name})" if pin.name else ""
                etype = f" [{pin.electrical_type}]" if pin.electrical_type != "unspecified" else ""
                lines.append(f"  {pin.number}{name_part}{etype}")

    # Datasheet spec
    spec = specs.get(comp.reference)
    if spec:
        lines.append("")
        lines.append(f"Datasheet: {spec.mpn}")
        if spec.manufacturer:
            lines.append(f"  Manufacturer: {spec.manufacturer}")
        if spec.description:
            lines.append(f"  Description: {spec.description}")
        if spec.supply_voltage_min is not None or spec.supply_voltage_max is not None:
            vmin = spec.supply_voltage_min if spec.supply_voltage_min is not None else "?"
            vmax = spec.supply_voltage_max if spec.supply_voltage_max is not None else "?"
            lines.append(f"  Supply: {vmin}V to {vmax}V")
        if spec.pdf_path:
            pages = ""
            if spec.relevant_pages:
                pages = f" (pages {', '.join(str(p) for p in spec.relevant_pages[:10])})"
            lines.append(f"  PDF: {spec.pdf_path}{pages}")

    return "\n".join(lines)


def _trace_net(net_name: str, schematic: ParsedSchematic) -> str:
    """Trace a net by name to see all connected pins."""
    name_lower = net_name.strip().lower()

    # Try exact match first, then case-insensitive
    target = None
    for net in schematic.nets:
        if net.name == net_name.strip():
            target = net
            break
    if target is None:
        for net in schematic.nets:
            if net.name.lower() == name_lower:
                target = net
                break

    if target is None:
        # Suggest similar nets
        suggestions = [n.name for n in schematic.nets if name_lower in n.name.lower()][:5]
        msg = f"Net '{net_name}' not found."
        if suggestions:
            msg += f" Similar nets: {', '.join(suggestions)}"
        return msg

    kind = "power" if target.is_power else "signal"
    lines: list[str] = [f"Net: {target.name} ({kind})"]

    if target.pins:
        lines.append("Connected pins:")
        for pc in target.pins:
            name_part = f" ({pc.pin_name})" if pc.pin_name else ""
            lines.append(f"  {pc.component_ref} pin {pc.pin_number}{name_part}")

    if target.labels:
        lines.append(f"Labels: {', '.join(target.labels)}")

    return "\n".join(lines)


def _find_unconnected(
    ref: str | None,
    schematic: ParsedSchematic,
) -> str:
    """Find floating/unconnected pins, optionally filtered by component ref."""
    pins = schematic.unconnected_pins

    if ref:
        ref_upper = ref.strip().upper()
        pins = [p for p in pins if p.component_ref.upper() == ref_upper]

    if not pins:
        scope = f" on {ref}" if ref else ""
        return f"No unconnected pins found{scope}."

    # Build a pin type lookup from components
    pin_type_map: dict[tuple[str, str], str] = {}
    for comp in schematic.components:
        for pin in comp.pins:
            pin_type_map[(comp.reference.upper(), pin.number)] = pin.electrical_type

    lines: list[str] = [f"Unconnected pins ({len(pins)}):"]
    for pc in pins:
        etype = pin_type_map.get((pc.component_ref.upper(), pc.pin_number), "")
        etype_str = f" -- {etype}" if etype and etype != "unspecified" else ""
        name_part = f" ({pc.pin_name})" if pc.pin_name else ""
        lines.append(f"  {pc.component_ref} pin {pc.pin_number}{name_part}{etype_str}")

    return "\n".join(lines)


def _list_power_rails(schematic: ParsedSchematic) -> str:
    """List all power nets and the components connected to each."""
    power_nets = [n for n in schematic.nets if n.is_power]

    if not power_nets:
        return "No power nets found in schematic."

    # Sort by number of connections (descending)
    power_nets.sort(key=lambda n: len(n.pins), reverse=True)

    lines: list[str] = ["Power rails:"]
    for net in power_nets:
        # Collect unique component refs
        refs = sorted({pc.component_ref for pc in net.pins})
        refs_str = ", ".join(refs) if len(refs) <= 15 else ", ".join(refs[:15]) + "..."
        lines.append(f"  {net.name}: {len(refs)} components ({refs_str})")

    return "\n".join(lines)
