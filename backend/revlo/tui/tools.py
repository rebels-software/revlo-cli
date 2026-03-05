"""Schematic query tools for Ask mode -- lets Opus explore the design."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from revlo.datasheet.models import DatasheetSpec
from revlo.parser.models import ParsedComponent, ParsedNet, ParsedSchematic
from revlo.constraints import ProjectConstraints
from revlo.reviewer.models import Finding, ReviewReport


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
    {
        "name": "find_decoupling_caps",
        "description": (
            "Find likely decoupling capacitors for a component and summarize the "
            "associated power nets."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    "description": "Target component reference, e.g. 'U1'",
                },
            },
            "required": ["ref"],
        },
    },
    {
        "name": "trace_power_tree",
        "description": (
            "Trace a power net through likely regulators and connected loads. "
            "Clearly distinguishes observed connectivity from inference."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "net_name": {
                    "type": "string",
                    "description": "Power net name, e.g. '+3V3' or 'VBAT'",
                },
            },
            "required": ["net_name"],
        },
    },
    {
        "name": "find_reset_chain",
        "description": (
            "Trace reset-related nets, pull components, supervisors, buttons, "
            "and likely MCU reset pins."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    "description": "Optional component reference to anchor the reset search",
                },
                "net_name": {
                    "type": "string",
                    "description": "Optional reset net name to trace directly",
                },
            },
            "required": [],
        },
    },
    {
        "name": "find_boot_straps",
        "description": (
            "Identify likely boot or mode pins and the pull-up or pull-down "
            "networks attached to them."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    "description": "Target component reference, e.g. 'U1'",
                },
            },
            "required": ["ref"],
        },
    },
    {
        "name": "find_interface_bundle",
        "description": (
            "Group nets and connected refs for one interface family such as USB, "
            "I2C, SPI, UART, or CAN."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "interface_type": {
                    "type": "string",
                    "enum": ["USB", "I2C", "SPI", "UART", "CAN"],
                    "description": "Interface family to group",
                },
            },
            "required": ["interface_type"],
        },
    },
    {
        "name": "compare_two_refs",
        "description": (
            "Compare two components by pins, connected nets, and key metadata."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ref_a": {
                    "type": "string",
                    "description": "First component reference, e.g. 'U1'",
                },
                "ref_b": {
                    "type": "string",
                    "description": "Second component reference, e.g. 'U2'",
                },
            },
            "required": ["ref_a", "ref_b"],
        },
    },
    {
        "name": "explain_finding_evidence",
        "description": (
            "Summarize the structured refs, nets, sheets, and datasheet context "
            "behind a finding."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "finding_ref": {
                    "type": "string",
                    "description": "Finding identifier or component reference in the current review context",
                },
            },
            "required": ["finding_ref"],
        },
    },
    {
        "name": "show_constraint_violations",
        "description": (
            "Show relevant project constraint violations or unverified constraints "
            "for a finding, ref, or net."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    "description": "Optional component reference",
                },
                "finding_ref": {
                    "type": "string",
                    "description": "Optional finding reference from the current review context",
                },
            },
            "required": [],
        },
    },
]


def execute_tool(
    name: str,
    args: dict[str, Any],
    schematic: ParsedSchematic,
    specs: dict[str, DatasheetSpec] | None = None,
    report: ReviewReport | None = None,
    constraints: ProjectConstraints | None = None,
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
    elif name == "find_decoupling_caps":
        return _find_decoupling_caps(args.get("ref", ""), schematic)
    elif name == "trace_power_tree":
        return _trace_power_tree(args.get("net_name", ""), schematic)
    elif name == "find_reset_chain":
        return _find_reset_chain(
            schematic,
            ref=args.get("ref"),
            net_name=args.get("net_name"),
        )
    elif name == "find_boot_straps":
        return _find_boot_straps(args.get("ref", ""), schematic)
    elif name == "find_interface_bundle":
        return _find_interface_bundle(args.get("interface_type", ""), schematic)
    elif name == "compare_two_refs":
        return _compare_two_refs(
            args.get("ref_a", ""),
            args.get("ref_b", ""),
            schematic,
        )
    elif name == "explain_finding_evidence":
        return _explain_finding_evidence(args.get("finding_ref", ""), report)
    elif name == "show_constraint_violations":
        return _show_constraint_violations(
            report=report,
            constraints=constraints,
            ref=args.get("ref"),
            finding_ref=args.get("finding_ref"),
        )
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


def _build_component_lookup(
    schematic: ParsedSchematic,
) -> dict[str, ParsedComponent]:
    return {component.reference.upper(): component for component in schematic.components}


def _build_net_lookup(schematic: ParsedSchematic) -> dict[str, ParsedNet]:
    lookup: dict[str, ParsedNet] = {}
    for net in schematic.nets:
        lookup[net.name.upper()] = net
    return lookup


def _find_component(
    schematic: ParsedSchematic,
    ref: str,
) -> ParsedComponent | None:
    return _build_component_lookup(schematic).get(ref.strip().upper())


def _component_nets(component: ParsedComponent) -> list[str]:
    return [pin.connected_net for pin in component.pins if pin.connected_net]


def _is_ground_net(net_name: str) -> bool:
    normalized = net_name.strip().upper()
    return any(token in normalized for token in ("GND", "VSS", "PGND", "AGND", "DGND"))


def _is_capacitor(component: ParsedComponent) -> bool:
    ref = component.reference.upper()
    lib_id = component.lib_id.upper()
    return ref.startswith("C") or lib_id.startswith("DEVICE:C")


def _is_resistor(component: ParsedComponent) -> bool:
    ref = component.reference.upper()
    lib_id = component.lib_id.upper()
    return ref.startswith("R") or lib_id.startswith("DEVICE:R")


def _find_decoupling_caps(ref: str, schematic: ParsedSchematic) -> str:
    """Find likely decoupling capacitors tied to a component's power nets."""
    component = _find_component(schematic, ref)
    if component is None:
        return f"Component '{ref}' not found in schematic."

    component_lookup = _build_component_lookup(schematic)
    power_nets = {
        pin.connected_net
        for pin in component.pins
        if pin.connected_net and (
            "power" in pin.electrical_type.lower()
            or _build_net_lookup(schematic).get(pin.connected_net.upper(), ParsedNet(name="")).is_power
        )
    }
    if not power_nets:
        return f"No power nets found on {component.reference}."

    lines = [f"Likely decoupling capacitors for {component.reference}:"]
    found_any = False
    for net_name in sorted(power_nets):
        matches: list[str] = []
        for candidate in schematic.components:
            if candidate.reference.upper() == component.reference.upper():
                continue
            if not _is_capacitor(candidate):
                continue
            candidate_nets = [pin.connected_net for pin in candidate.pins if pin.connected_net]
            if net_name in candidate_nets and any(
                ground_net and _is_ground_net(ground_net)
                for ground_net in candidate_nets
            ):
                value = f" ({candidate.value})" if candidate.value else ""
                matches.append(f"{candidate.reference}{value}")

        if matches:
            found_any = True
            lines.append(f"  {net_name}: {', '.join(sorted(matches))}")
        else:
            lines.append(f"  {net_name}: no obvious capacitor to ground found")

    if not found_any:
        lines.append("Observed power nets, but no likely decoupling capacitors were found.")
    return "\n".join(lines)


def _trace_power_tree(net_name: str, schematic: ParsedSchematic) -> str:
    """Trace a power net through observed loads and likely source components."""
    net = _build_net_lookup(schematic).get(net_name.strip().upper())
    if net is None:
        return f"Power net '{net_name}' not found."

    component_lookup = _build_component_lookup(schematic)
    lines = [f"Power trace for {net.name}:"]
    observed_refs = sorted({pin.component_ref for pin in net.pins})
    if observed_refs:
        lines.append(f"Observed connections: {', '.join(observed_refs)}")

    sources: list[str] = []
    loads: list[str] = []
    for ref in observed_refs:
        component = component_lookup.get(ref.upper())
        if component is None:
            continue
        attached_pins = [
            pin for pin in component.pins
            if pin.connected_net and pin.connected_net.upper() == net.name.upper()
        ]
        pin_names = {pin.name.upper() for pin in attached_pins}
        other_power_nets = sorted(
            {
                other_net
                for other_net in _component_nets(component)
                if other_net and other_net.upper() != net.name.upper()
                and (
                    _is_ground_net(other_net)
                    or _build_net_lookup(schematic).get(other_net.upper(), ParsedNet(name="")).is_power
                )
            }
        )
        if pin_names & {"OUT", "VOUT", "VO", "SW"}:
            source_text = component.reference
            if other_power_nets:
                source_text += f" (observed upstream nets: {', '.join(other_power_nets)})"
            sources.append(source_text)
        else:
            load_text = component.reference
            if other_power_nets:
                load_text += f" (also on {', '.join(other_power_nets)})"
            loads.append(load_text)

    if sources:
        lines.append(f"Likely source components: {', '.join(sources)}")
    else:
        lines.append("Likely source components: none identified from observed pin names")

    if loads:
        lines.append(f"Likely loads and dependent parts: {', '.join(loads)}")

    lines.append(
        "Inference note: regulator/source identification is heuristic and based on "
        "pin names plus connected power nets."
    )
    return "\n".join(lines)


def _find_reset_chain(
    schematic: ParsedSchematic,
    *,
    ref: str | None = None,
    net_name: str | None = None,
) -> str:
    """Trace reset-related nets, pulls, and connected parts."""
    target_nets: set[str] = set()
    if net_name:
        target_nets.add(net_name.strip())
    elif ref:
        component = _find_component(schematic, ref)
        if component is None:
            return f"Component '{ref}' not found in schematic."
        for pin in component.pins:
            pin_name = pin.name.upper()
            if "RST" in pin_name or "RESET" in pin_name or "NRST" in pin_name:
                if pin.connected_net:
                    target_nets.add(pin.connected_net)
    else:
        for net in schematic.nets:
            name = net.name.upper()
            if "RST" in name or "RESET" in name or "NRST" in name:
                target_nets.add(net.name)

    if not target_nets:
        scope = f" on {ref}" if ref else ""
        return f"No reset-related nets found{scope}."

    net_lookup = _build_net_lookup(schematic)
    component_lookup = _build_component_lookup(schematic)
    lines = ["Reset chain investigation:"]
    for target in sorted(target_nets):
        net = net_lookup.get(target.upper())
        if net is None:
            continue
        lines.append(f"Net {net.name}:")
        connected = sorted({pin.component_ref for pin in net.pins})
        lines.append(f"  Observed refs: {', '.join(connected)}")

        pulls: list[str] = []
        controls: list[str] = []
        for connected_ref in connected:
            component = component_lookup.get(connected_ref.upper())
            if component is None:
                continue
            other_nets = sorted(
                {
                    other_net
                    for other_net in _component_nets(component)
                    if other_net and other_net.upper() != net.name.upper()
                }
            )
            if _is_resistor(component):
                target_desc = ", ".join(other_nets) if other_nets else "other net unknown"
                pulls.append(f"{component.reference} -> {target_desc}")
            elif component.reference.upper().startswith("SW"):
                target_desc = ", ".join(other_nets) if other_nets else "other net unknown"
                controls.append(f"{component.reference} -> {target_desc}")
            elif any(
                token in component.value.upper() or token in component.lib_id.upper()
                for token in ("RESET", "SUPERVISOR", "WATCHDOG")
            ):
                controls.append(component.reference)

        if pulls:
            lines.append(f"  Pull network: {', '.join(sorted(pulls))}")
        if controls:
            lines.append(f"  Control path: {', '.join(sorted(controls))}")

    return "\n".join(lines)


def _find_boot_straps(ref: str, schematic: ParsedSchematic) -> str:
    """Identify likely boot or mode pins and attached pull networks."""
    component = _find_component(schematic, ref)
    if component is None:
        return f"Component '{ref}' not found in schematic."

    candidate_pins = [
        pin for pin in component.pins
        if pin.connected_net and any(
            token in pin.name.upper()
            for token in ("BOOT", "MODE", "CFG", "SEL", "STRAP")
        )
    ]
    if not candidate_pins:
        return f"No likely boot or mode pins found on {component.reference}."

    lines = [f"Boot strap investigation for {component.reference}:"]
    net_lookup = _build_net_lookup(schematic)
    component_lookup = _build_component_lookup(schematic)
    for pin in candidate_pins:
        lines.append(f"Pin {pin.number} ({pin.name}) -> net {pin.connected_net}")
        net = net_lookup.get(pin.connected_net.upper())
        if net is None:
            continue
        pull_parts: list[str] = []
        for connection in net.pins:
            if connection.component_ref.upper() == component.reference.upper():
                continue
            candidate = component_lookup.get(connection.component_ref.upper())
            if candidate is None or not _is_resistor(candidate):
                continue
            other_nets = sorted(
                {
                    other_net
                    for other_net in _component_nets(candidate)
                    if other_net and other_net.upper() != net.name.upper()
                }
            )
            target_desc = ", ".join(other_nets) if other_nets else "other net unknown"
            pull_parts.append(f"{candidate.reference} -> {target_desc}")
        if pull_parts:
            lines.append(f"  Observed pull network: {', '.join(sorted(pull_parts))}")
        else:
            lines.append("  Observed pull network: none identified")
    return "\n".join(lines)


_INTERFACE_PATTERNS: dict[str, tuple[str, ...]] = {
    "USB": ("USB", "DP", "DM", "D+", "D-", "VBUS", "CC", "SBU"),
    "I2C": ("I2C", "SCL", "SDA"),
    "SPI": ("SPI", "MOSI", "MISO", "SCK", "CS", "NSS"),
    "UART": ("UART", "USART", "TX", "RX", "RTS", "CTS"),
    "CAN": ("CAN", "CANH", "CANL", "TXD", "RXD"),
}


def _find_interface_bundle(interface_type: str, schematic: ParsedSchematic) -> str:
    """Group likely nets and refs for one interface family."""
    interface_key = interface_type.strip().upper()
    patterns = _INTERFACE_PATTERNS.get(interface_key)
    if not patterns:
        return f"Unsupported interface type '{interface_type}'."

    matching_nets: list[ParsedNet] = []
    for net in schematic.nets:
        haystacks = [net.name.upper(), *(label.upper() for label in net.labels)]
        if any(pattern in haystack for pattern in patterns for haystack in haystacks):
            matching_nets.append(net)

    if not matching_nets:
        return f"No likely {interface_key} nets found."

    lines = [f"{interface_key} interface bundle:"]
    for net in sorted(matching_nets, key=lambda item: item.name):
        refs = sorted({pin.component_ref for pin in net.pins})
        labels = f" labels={', '.join(net.labels)}" if net.labels else ""
        lines.append(f"  {net.name}{labels}: {', '.join(refs)}")
    return "\n".join(lines)


def _compare_two_refs(
    ref_a: str,
    ref_b: str,
    schematic: ParsedSchematic,
) -> str:
    """Compare two components by metadata and connected nets."""
    component_a = _find_component(schematic, ref_a)
    if component_a is None:
        return f"Component '{ref_a}' not found in schematic."
    component_b = _find_component(schematic, ref_b)
    if component_b is None:
        return f"Component '{ref_b}' not found in schematic."

    nets_a = set(_component_nets(component_a))
    nets_b = set(_component_nets(component_b))
    common_nets = sorted(net for net in nets_a & nets_b if net)
    only_a = sorted(net for net in nets_a - nets_b if net)
    only_b = sorted(net for net in nets_b - nets_a if net)

    lines = [
        f"Comparing {component_a.reference} and {component_b.reference}:",
        f"  {component_a.reference}: value={component_a.value}, footprint={component_a.footprint or '-'}, sheet={component_a.source_sheet or '-'}",
        f"  {component_b.reference}: value={component_b.value}, footprint={component_b.footprint or '-'}, sheet={component_b.source_sheet or '-'}",
        f"  Pin counts: {component_a.reference}={len(component_a.pins)}, {component_b.reference}={len(component_b.pins)}",
        f"  Shared nets: {', '.join(common_nets) if common_nets else 'none'}",
        f"  Nets only on {component_a.reference}: {', '.join(only_a) if only_a else 'none'}",
        f"  Nets only on {component_b.reference}: {', '.join(only_b) if only_b else 'none'}",
    ]
    return "\n".join(lines)


def _find_report_finding(
    report: ReviewReport | None,
    finding_ref: str,
) -> Finding | None:
    """Resolve a finding by component ref, title, or combined label."""
    if report is None:
        return None
    needle = finding_ref.strip().lower()
    if not needle:
        return report.findings[0] if len(report.findings) == 1 else None
    for finding in report.findings:
        candidates = {
            finding.component_ref.lower(),
            finding.title.lower(),
            f"{finding.component_ref}: {finding.title}".lower(),
        }
        if needle in candidates:
            return finding
    return None


def _explain_finding_evidence(
    finding_ref: str,
    report: ReviewReport | None,
) -> str:
    """Summarize stored structured evidence for a finding."""
    if report is None:
        return "No review context is loaded, so finding evidence cannot be explained."

    finding = _find_report_finding(report, finding_ref)
    if finding is None:
        return (
            f"Finding '{finding_ref}' was not found in the active review context."
            if finding_ref.strip()
            else "Specify finding_ref when multiple findings are present."
        )

    evidence = finding.evidence
    lines = [
        f"Evidence for {finding.component_ref}: {finding.title}",
        f"Source type: {finding.source_type.value}",
    ]
    if evidence.refs:
        lines.append(f"Refs: {', '.join(evidence.refs)}")
    if evidence.nets:
        lines.append(f"Nets: {', '.join(evidence.nets)}")
    if evidence.sheet_paths:
        lines.append(f"Sheets: {', '.join(evidence.sheet_paths)}")
    if evidence.datasheets:
        lines.append("Datasheet context:")
        for datasheet in evidence.datasheets:
            parts = [datasheet.mpn or "Unknown part"]
            if datasheet.manufacturer:
                parts.append(datasheet.manufacturer)
            if datasheet.relevant_pages:
                parts.append("pages " + ", ".join(str(page) for page in datasheet.relevant_pages))
            lines.append(f"  - {' | '.join(parts)}")
    if evidence.notes:
        lines.append("Notes:")
        for note in evidence.notes:
            lines.append(f"  - {note}")
    if len(lines) == 2:
        lines.append("No structured evidence is attached to this finding yet.")
    return "\n".join(lines)


def _show_constraint_violations(
    *,
    report: ReviewReport | None,
    constraints: ProjectConstraints | None,
    ref: str | None,
    finding_ref: str | None,
) -> str:
    """Summarize matching violated or unverified project constraints."""
    if constraints is None or not constraints.constraints:
        return "No project constraints are loaded for this schematic."

    target_refs: set[str] = set()
    target_nets: set[str] = set()
    if ref:
        target_refs.add(ref.strip().upper())

    finding = _find_report_finding(report, finding_ref or "")
    if finding is not None:
        target_refs.add(finding.component_ref.upper())
        target_refs.update(item.upper() for item in finding.evidence.refs)
        target_nets.update(item.upper() for item in finding.evidence.nets)

    matched = []
    for constraint in constraints.constraints:
        target = constraint.target.strip().upper()
        if not target:
            continue
        if target in target_refs or target in target_nets:
            matched.append(constraint)

    if not matched:
        return (
            "No matching project constraints were found for the requested finding or ref."
        )

    subject = finding.component_ref if finding is not None else (ref or "selection")
    lines = [
        f"Constraint summary for {subject}:",
        "No stored violated constraints are attached to this context yet.",
        "Matching project constraints that still require verification:",
    ]
    for constraint in matched:
        summary = f"{constraint.kind}: {constraint.name}"
        if constraint.target:
            summary += f" [target={constraint.target}]"
        if constraint.value:
            summary += f" -> {constraint.value}"
            if constraint.unit:
                summary += f" {constraint.unit}"
        lines.append(f"  - {summary}")
        if constraint.notes:
            lines.append(f"    note: {constraint.notes}")
    return "\n".join(lines)
