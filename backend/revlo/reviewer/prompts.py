"""Prompt templates for the schematic review engine.

Pure string functions that build Claude API prompts from ReviewChunks.
No API calls are made here -- only prompt text is constructed.
"""

from __future__ import annotations

import json

from revlo.reviewer.chunker import ReviewChunk
from revlo.reviewer.models import Finding


# ---------------------------------------------------------------------------
# Finding JSON schema (generated once at import time)
# ---------------------------------------------------------------------------
_FINDING_SCHEMA: str = json.dumps(Finding.model_json_schema(), indent=2)


# ---------------------------------------------------------------------------
# Layer 1 checklists
# ---------------------------------------------------------------------------
_IC_CONTEXT_CHECKLIST = """\
1. Decoupling capacitors are present and placed close to IC power pins.
2. Pull-up or pull-down resistors are present on open-drain / open-collector pins.
3. Unused pins are properly terminated (tied high, tied low, or left floating only when the datasheet allows it).
4. Reset pin has a proper RC circuit or a dedicated reset IC.
5. Clock / oscillator connections have proper load capacitors.
6. Signal integrity: series termination resistors are present on high-speed lines.
7. ESD protection is present on external-facing pins."""

_POWER_RAIL_CHECKLIST = """\
1. Bulk and bypass capacitors are present on the rail.
2. Voltage regulator connections are correct (input, output, enable).
3. Ground connections are verified for all components on this rail.
4. Power sequencing considerations are addressed.
5. Current capacity of traces / vias is sufficient (thermal).
6. Protection is present (reverse polarity, overcurrent)."""


# ---------------------------------------------------------------------------
# Chunk-data serialiser
# ---------------------------------------------------------------------------
def _format_chunk_data(chunk: ReviewChunk) -> str:
    """Serialize chunk data into human-readable text for embedding in a prompt."""
    sections: list[str] = []

    # -- Components ----------------------------------------------------------
    if chunk.components:
        lines: list[str] = ["## Components"]
        for comp in chunk.components:
            pins_summary = ", ".join(
                f"{p.number}({p.name}/{p.electrical_type}"
                f"{' -> ' + p.connected_net if p.connected_net else ''}"
                f")"
                for p in comp.pins
            )
            props = ""
            if comp.properties:
                props = f"  Properties: {comp.properties}"
            lines.append(
                f"- {comp.reference}: {comp.value}"
                f"  [lib={comp.lib_id}, footprint={comp.footprint}]"
            )
            if pins_summary:
                lines.append(f"  Pins: {pins_summary}")
            if props:
                lines.append(props)
        sections.append("\n".join(lines))

    # -- Nets ----------------------------------------------------------------
    if chunk.nets:
        lines = ["## Nets"]
        for net in chunk.nets:
            pin_refs = ", ".join(
                f"{p.component_ref}.{p.pin_number}" for p in net.pins
            )
            power_tag = " [POWER]" if net.is_power else ""
            labels_tag = f" labels={net.labels}" if net.labels else ""
            lines.append(f"- {net.name}{power_tag}{labels_tag}: {pin_refs}")
        sections.append("\n".join(lines))

    # -- Unconnected pins ----------------------------------------------------
    if chunk.unconnected_pins:
        lines = ["## Unconnected Pins"]
        for uc in chunk.unconnected_pins:
            lines.append(f"- {uc.component_ref} pin {uc.pin_number} ({uc.pin_name})")
        sections.append("\n".join(lines))

    # -- Datasheet Specifications --------------------------------------------
    if chunk.datasheet_specs:
        lines = ["## Datasheet Specifications"]
        for ref, spec in sorted(chunk.datasheet_specs.items()):
            lines.append(f"### {ref}: {spec.mpn}")
            if spec.manufacturer:
                lines.append(f"- Manufacturer: {spec.manufacturer}")
            if spec.description:
                lines.append(f"- Description: {spec.description}")
            if spec.supply_voltage_min is not None or spec.supply_voltage_max is not None:
                vmin = spec.supply_voltage_min if spec.supply_voltage_min is not None else "?"
                vmax = spec.supply_voltage_max if spec.supply_voltage_max is not None else "?"
                lines.append(f"- Supply Voltage: {vmin}V to {vmax}V")
            if spec.max_current is not None:
                lines.append(f"- Max Current: {spec.max_current}A")
            if spec.absolute_max_ratings:
                lines.append("- Absolute Max Ratings:")
                for k, v in spec.absolute_max_ratings.items():
                    lines.append(f"  - {k}: {v}")
            if spec.recommended_operating:
                lines.append("- Recommended Operating:")
                for k, v in spec.recommended_operating.items():
                    lines.append(f"  - {k}: {v}")
            if spec.pin_functions:
                lines.append("- Pin Functions:")
                for pf in spec.pin_functions:
                    desc = f" — {pf.function_description}" if pf.function_description else ""
                    etype = f" [{pf.electrical_type}]" if pf.electrical_type else ""
                    lines.append(f"  - Pin {pf.pin_number} ({pf.name}){etype}{desc}")
            if spec.notes:
                lines.append("- Notes:")
                for note in spec.notes:
                    lines.append(f"  - {note}")
        sections.append("\n".join(lines))

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Per-chunk-type prompt builders
# ---------------------------------------------------------------------------
_DATASHEET_VERIFICATION_INSTRUCTION = """\

If datasheet specifications are provided above, use them to verify:
- Component values match datasheet recommended values
- Pin connections match datasheet pin functions
- Operating conditions are within datasheet limits
- Required external components (caps, resistors) are present per datasheet"""


def _build_ic_context_prompt(chunk: ReviewChunk) -> str:
    """Build a review prompt for an IC-context chunk."""
    chunk_data = _format_chunk_data(chunk)
    datasheet_instruction = _DATASHEET_VERIFICATION_INSTRUCTION if chunk.datasheet_specs else ""

    return f"""\
You are an expert electronic design engineer reviewing a KiCad schematic.

You are reviewing the IC context for **{chunk.label}**.

## Schematic Data

{chunk_data}

## Review Checklist

Evaluate the schematic data above against every item in this checklist:

{_IC_CONTEXT_CHECKLIST}

For each checklist item, determine whether the design meets the requirement based \
on the component data, net connections, and unconnected pins provided. If a \
checklist item is not applicable (e.g. no clock pins exist), skip it.
{datasheet_instruction}

## Output Format

Return ONLY a JSON array of Finding objects. Each Finding must conform to this \
JSON schema:

```json
{_FINDING_SCHEMA}
```

Rules:
- Be thorough: report every potential design issue you can identify, even if you are \
not fully certain. Use the `confidence` field to express certainty (0.0-1.0) rather \
than omitting uncertain findings. A low-confidence finding is more valuable than a \
missed issue.
- Return `[]` (empty array) only if you are confident no issues exist.
- Do NOT wrap the JSON in markdown code fences or add any text outside the array.
- The `component_ref` field must reference a component from the schematic data above.
- Be precise: cite specific pin numbers and net names in your descriptions.
- Prefer actionable recommendations over vague advice.
- NEVER report meta-findings about the schematic data itself (e.g. "incomplete data", \
"missing net info", "insufficient information"). The data provided is complete — focus \
exclusively on hardware design issues."""


def _build_power_rail_prompt(chunk: ReviewChunk) -> str:
    """Build a review prompt for a power-rail chunk."""
    chunk_data = _format_chunk_data(chunk)
    datasheet_instruction = _DATASHEET_VERIFICATION_INSTRUCTION if chunk.datasheet_specs else ""

    return f"""\
You are an expert electronic design engineer reviewing a KiCad schematic.

You are reviewing the power rail **{chunk.label}**.

## Schematic Data

{chunk_data}

## Review Checklist

Evaluate the schematic data above against every item in this checklist:

{_POWER_RAIL_CHECKLIST}

For each checklist item, determine whether the design meets the requirement based \
on the component data, net connections, and unconnected pins provided. If a \
checklist item is not applicable, skip it.
{datasheet_instruction}

## Output Format

Return ONLY a JSON array of Finding objects. Each Finding must conform to this \
JSON schema:

```json
{_FINDING_SCHEMA}
```

Rules:
- Be thorough: report every potential design issue you can identify, even if you are \
not fully certain. Use the `confidence` field to express certainty (0.0-1.0) rather \
than omitting uncertain findings. A low-confidence finding is more valuable than a \
missed issue.
- Return `[]` (empty array) only if you are confident no issues exist.
- Do NOT wrap the JSON in markdown code fences or add any text outside the array.
- The `component_ref` field must reference a component from the schematic data above.
- Be precise: cite specific pin numbers and net names in your descriptions.
- Prefer actionable recommendations over vague advice.
- NEVER report meta-findings about the schematic data itself (e.g. "incomplete data", \
"missing net info", "insufficient information"). The data provided is complete — focus \
exclusively on hardware design issues."""


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
_BUILDERS: dict[str, object] = {
    "ic_context": _build_ic_context_prompt,
    "power_rail": _build_power_rail_prompt,
}


def build_review_prompt(chunk: ReviewChunk) -> str:
    """Build a review prompt for the given ReviewChunk.

    Dispatches to the appropriate builder based on ``chunk.chunk_type``.

    Raises:
        ValueError: If the chunk type is not recognised.
    """
    builder = _BUILDERS.get(chunk.chunk_type)
    if builder is None:
        raise ValueError(
            f"Unknown chunk type: {chunk.chunk_type!r}. "
            f"Expected one of: {sorted(_BUILDERS)}"
        )
    return builder(chunk)  # type: ignore[operator]
