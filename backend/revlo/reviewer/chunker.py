"""Schematic chunker — splits a ParsedSchematic into review-sized chunks."""

from __future__ import annotations

from pydantic import BaseModel, Field

from revlo.parser.models import (
    ParsedComponent,
    ParsedNet,
    ParsedSchematic,
    PinConnection,
)

# Reference prefixes considered "passive" (everything non-IC, non-power).
_PASSIVE_PREFIXES = ("R", "C", "L", "D", "Q", "F", "FB", "Y", "X", "J", "P", "SW", "K", "T")


class ReviewChunk(BaseModel):
    """A review-sized slice of a schematic, suitable for LLM analysis."""

    chunk_type: str  # "ic_context" or "power_rail"
    label: str  # e.g. "U1 - STM32F103" or "Power Rail: VCC"
    components: list[ParsedComponent] = Field(default_factory=list)
    nets: list[ParsedNet] = Field(default_factory=list)
    unconnected_pins: list[PinConnection] = Field(default_factory=list)


def _is_ic(comp: ParsedComponent) -> bool:
    """Return True if the component is an IC (reference starts with U)."""
    return comp.reference.startswith("U")


def _build_net_lookup(schematic: ParsedSchematic) -> dict[str, ParsedNet]:
    """Build a mapping from net name to ParsedNet."""
    return {net.name: net for net in schematic.nets}


def _build_comp_lookup(schematic: ParsedSchematic) -> dict[str, ParsedComponent]:
    """Build a mapping from component reference to ParsedComponent."""
    return {comp.reference: comp for comp in schematic.components}


def _refs_on_net(net: ParsedNet) -> set[str]:
    """Return the set of component references connected to a net."""
    return {pin.component_ref for pin in net.pins}


def _filter_unconnected(
    refs: set[str],
    all_unconnected: list[PinConnection],
) -> list[PinConnection]:
    """Return unconnected pins belonging to any of the given component refs."""
    return [uc for uc in all_unconnected if uc.component_ref in refs]


def _ic_context_chunks(
    schematic: ParsedSchematic,
    net_lookup: dict[str, ParsedNet],
    comp_lookup: dict[str, ParsedComponent],
) -> list[ReviewChunk]:
    """Create one chunk per IC with its directly-connected passives and nets."""
    power_symbol_refs = {ps.reference for ps in schematic.power_symbols}
    ic_components = [c for c in schematic.components if _is_ic(c)]
    chunks: list[ReviewChunk] = []

    for ic in ic_components:
        chunk_nets: dict[str, ParsedNet] = {}
        passive_refs: set[str] = set()

        # Walk every pin on the IC and find its connected net.
        for pin in ic.pins:
            net_name = pin.connected_net
            if net_name is None:
                continue
            net = net_lookup.get(net_name)
            if net is None:
                continue
            chunk_nets[net_name] = net

            # Collect non-IC, non-power-symbol components on the same net.
            for ref in _refs_on_net(net):
                if ref == ic.reference:
                    continue
                if ref in power_symbol_refs:
                    continue
                comp = comp_lookup.get(ref)
                if comp is not None and not _is_ic(comp):
                    passive_refs.add(ref)

        # Assemble component list: IC first, then passives sorted by ref.
        chunk_comps = [ic] + sorted(
            [comp_lookup[r] for r in passive_refs if r in comp_lookup],
            key=lambda c: c.reference,
        )

        all_refs = {ic.reference} | passive_refs
        unconnected = _filter_unconnected(all_refs, schematic.unconnected_pins)

        chunks.append(
            ReviewChunk(
                chunk_type="ic_context",
                label=f"{ic.reference} - {ic.value}",
                components=chunk_comps,
                nets=sorted(chunk_nets.values(), key=lambda n: n.name),
                unconnected_pins=unconnected,
            )
        )

    return chunks


def _power_rail_chunks(
    schematic: ParsedSchematic,
    net_lookup: dict[str, ParsedNet],
    comp_lookup: dict[str, ParsedComponent],
) -> list[ReviewChunk]:
    """Create one chunk per power net with all its connected components."""
    power_nets = [net for net in schematic.nets if net.is_power]
    chunks: list[ReviewChunk] = []

    for net in sorted(power_nets, key=lambda n: n.name):
        refs = _refs_on_net(net)
        comps = sorted(
            [comp_lookup[r] for r in refs if r in comp_lookup],
            key=lambda c: c.reference,
        )

        unconnected = _filter_unconnected(refs, schematic.unconnected_pins)

        chunks.append(
            ReviewChunk(
                chunk_type="power_rail",
                label=f"Power Rail: {net.name}",
                components=comps,
                nets=[net],
                unconnected_pins=unconnected,
            )
        )

    return chunks


def chunk_schematic(schematic: ParsedSchematic) -> list[ReviewChunk]:
    """Split a ParsedSchematic into review-sized ReviewChunks.

    Produces two kinds of chunks:
    - **ic_context**: one per IC (U-prefix component), containing the IC,
      its directly-connected passive components, relevant nets, and
      unconnected pins.
    - **power_rail**: one per power net, containing all components connected
      to that net and any unconnected pins.

    Chunks intentionally overlap -- a passive connected to both an IC and a
    power rail appears in both chunks.
    """
    net_lookup = _build_net_lookup(schematic)
    comp_lookup = _build_comp_lookup(schematic)

    ic_chunks = _ic_context_chunks(schematic, net_lookup, comp_lookup)
    power_chunks = _power_rail_chunks(schematic, net_lookup, comp_lookup)

    return ic_chunks + power_chunks
