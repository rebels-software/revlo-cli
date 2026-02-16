"""Connectivity wrapper for net extraction from KiCad schematics.

Walks all component pins, queries the schematic for net connectivity,
deduplicates nets by name, and classifies them as power or signal.
"""

from __future__ import annotations

import logging
import re

import kicad_sch_api as ksa

from revlo.parser.models import ParsedComponent, ParsedNet, PinConnection
from revlo.parser.netlist import NetlistData

logger = logging.getLogger(__name__)

# Regex pattern matching common power net names.
# Matches: VCC, VDD, VSS, GND, GNDREF, GNDA, GNDD, VBUS,
# +3V3, +3.3V, +5V, +12V, -12V, +1V8, +2V5, etc.
_POWER_NET_RE = re.compile(
    r"^("
    r"V[CDS][CDS]"          # VCC, VDD, VSS, VDC, etc.
    r"|GND[A-Z]*"           # GND, GNDA, GNDD, GNDREF, etc.
    r"|VBUS"                # USB bus power
    r"|[+-]\d+V\d*"         # +5V, +12V, -12V, +3V3, +1V8
    r"|[+-]\d+\.\d+V"      # +3.3V, +1.8V, +2.5V
    r")$",
    re.IGNORECASE,
)


def _is_power_net(
    net_name: str,
    connected_refs: list[str],
) -> bool:
    """Determine whether a net is a power net.

    A net is classified as power if:
    - Any connected component has a reference starting with ``#PWR``, OR
    - The net name matches common power-rail naming patterns.

    Args:
        net_name: The net's name string.
        connected_refs: References of components whose pins connect to this net.

    Returns:
        True if the net should be classified as a power net.
    """
    if any(ref.startswith("#PWR") for ref in connected_refs):
        return True
    if _POWER_NET_RE.match(net_name):
        return True
    return False


def build_net_list(
    sch: ksa.Schematic,
    all_components: list[ParsedComponent],
) -> tuple[list[ParsedNet], list[PinConnection]]:
    """Build the net list and identify unconnected pins.

    Iterates every pin of every component and queries the schematic for its
    net.  Nets are deduplicated by name.  Pins with no net are collected into
    the unconnected list.

    Args:
        sch: A loaded ``kicad_sch_api.Schematic`` instance.
        all_components: All components including power symbols.

    Returns:
        A tuple of (nets, unconnected_pins).
    """
    # Build a label-text lookup keyed by UUID for resolving net label names.
    label_text_by_uuid: dict[str, str] = {}
    for label in sch.labels:
        label_text_by_uuid[label.uuid] = label.text

    nets_by_name: dict[str, ParsedNet] = {}
    # Track which component refs connect to each net (for power classification).
    net_refs: dict[str, list[str]] = {}
    unconnected_pins: list[PinConnection] = []

    for comp in all_components:
        for pin in comp.pins:
            try:
                net = sch.get_net_for_pin(comp.reference, pin.number)
            except Exception:
                net = None

            if net is None:
                unconnected_pins.append(
                    PinConnection(
                        component_ref=comp.reference,
                        pin_number=pin.number,
                        pin_name=pin.name,
                    )
                )
                continue

            net_name = net.name or ""

            if net_name not in nets_by_name:
                # Resolve label texts from UUIDs.
                label_texts: list[str] = []
                for label_uuid in net.labels:
                    text = label_text_by_uuid.get(label_uuid)
                    if text:
                        label_texts.append(text)

                # Collect connected component references from the net object
                # for power classification.
                refs_from_net: list[str] = []
                for pc in net.pins:
                    ref = getattr(pc, "reference", None)
                    if ref:
                        refs_from_net.append(ref)

                nets_by_name[net_name] = ParsedNet(
                    name=net_name,
                    pins=[],
                    labels=label_texts,
                    is_power=_is_power_net(net_name, refs_from_net),
                )
                net_refs[net_name] = refs_from_net

            # Add this pin connection to the net (avoid duplicates).
            pin_conn = PinConnection(
                component_ref=comp.reference,
                pin_number=pin.number,
                pin_name=pin.name,
            )
            existing = nets_by_name[net_name].pins
            if not any(
                p.component_ref == pin_conn.component_ref
                and p.pin_number == pin_conn.pin_number
                for p in existing
            ):
                existing.append(pin_conn)

    return list(nets_by_name.values()), unconnected_pins


def build_merged_net_list(
    sheet_pairs: list[tuple[ksa.Schematic, list[ParsedComponent]]],
) -> tuple[list[ParsedNet], list[PinConnection]]:
    """Build a merged net list across multiple sheets.

    Takes a list of (ksa.Schematic, components) pairs — one per sheet
    including the root — and merges nets by name across all sheets.
    Pin connections are deduplicated and labels are merged.

    Args:
        sheet_pairs: List of (schematic, all_components) tuples, one per sheet.

    Returns:
        A tuple of (nets, unconnected_pins) covering all sheets.
    """
    if not sheet_pairs:
        return [], []

    # If there is only a single sheet, delegate to the original builder
    # for backward compatibility and efficiency.
    if len(sheet_pairs) == 1:
        sch, comps = sheet_pairs[0]
        return build_net_list(sch, comps)

    # Collect per-sheet net lists and merge them.
    merged_nets: dict[str, ParsedNet] = {}
    all_unconnected: list[PinConnection] = []

    for sch, comps in sheet_pairs:
        sheet_nets, sheet_unconnected = build_net_list(sch, comps)
        all_unconnected.extend(sheet_unconnected)

        for net in sheet_nets:
            if net.name in merged_nets:
                existing = merged_nets[net.name]

                # Merge pin connections (deduplicate).
                for pin_conn in net.pins:
                    if not any(
                        p.component_ref == pin_conn.component_ref
                        and p.pin_number == pin_conn.pin_number
                        for p in existing.pins
                    ):
                        existing.pins.append(pin_conn)

                # Merge labels (deduplicate).
                existing_labels = set(existing.labels)
                for label in net.labels:
                    if label not in existing_labels:
                        existing.labels.append(label)
                        existing_labels.add(label)

                # Promote to power if any sheet classifies it as power.
                if net.is_power:
                    existing.is_power = True
            else:
                merged_nets[net.name] = net

    return list(merged_nets.values()), all_unconnected


def build_nets_from_netlist(
    netlist: NetlistData,
    all_components: list[ParsedComponent],
) -> tuple[list[ParsedNet], list[PinConnection]]:
    """Build nets + unconnected pins from kicad-cli netlist data.

    Uses ground-truth connectivity from ``kicad-cli sch export netlist``
    instead of kicad-sch-api's connectivity analyser.

    Args:
        netlist: Parsed netlist data with pin-to-net mappings.
        all_components: All components including power symbols.

    Returns:
        A tuple of (nets, unconnected_pins).
    """
    nets_by_name: dict[str, ParsedNet] = {}
    unconnected_pins: list[PinConnection] = []

    # Pre-compute refs per net for power classification (done once).
    _net_refs_cache: dict[str, list[str]] = {}

    for comp in all_components:
        for pin in comp.pins:
            net_name = netlist.pin_nets.get((comp.reference, pin.number))
            if net_name is None:
                unconnected_pins.append(
                    PinConnection(
                        component_ref=comp.reference,
                        pin_number=pin.number,
                        pin_name=pin.name,
                    )
                )
                continue

            if net_name not in nets_by_name:
                # Collect refs of all pins on this net for power classification.
                if net_name not in _net_refs_cache:
                    connected_refs = [
                        ref
                        for (ref, _pin), name in netlist.pin_nets.items()
                        if name == net_name
                    ]
                    _net_refs_cache[net_name] = connected_refs

                nets_by_name[net_name] = ParsedNet(
                    name=net_name,
                    pins=[],
                    labels=[],
                    is_power=_is_power_net(
                        net_name, _net_refs_cache[net_name]
                    ),
                )

            pin_conn = PinConnection(
                component_ref=comp.reference,
                pin_number=pin.number,
                pin_name=pin.name,
            )
            existing = nets_by_name[net_name].pins
            if not any(
                p.component_ref == pin_conn.component_ref
                and p.pin_number == pin_conn.pin_number
                for p in existing
            ):
                existing.append(pin_conn)

    return list(nets_by_name.values()), unconnected_pins
