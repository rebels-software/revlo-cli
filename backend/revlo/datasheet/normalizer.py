"""Part number normalizer for KiCad component data.

Extracts manufacturer part numbers (MPNs) from parsed KiCad components,
identifies generic/passive parts, and collects datasheet URLs.
"""

from __future__ import annotations

import re

from revlo.datasheet.models import NormalizedPartNumber
from revlo.parser.models import ParsedComponent, ParsedSchematic

# lib_id prefixes that indicate generic/passive parts.
_GENERIC_LIB_PREFIXES = ("Device:", "power:")

# Reference designator prefixes for passive components.
_PASSIVE_REF_PREFIXES = ("R", "C", "L", "D")

# Pattern matching a simple passive value: number with optional decimal,
# followed by an SI unit suffix (e.g. "100nF", "10k", "4.7uF", "22pF",
# "1M", "470R", "2.2mH").
_PASSIVE_VALUE_RE = re.compile(
    r"^\d+\.?\d*\s*[pnuUmMkKRFHV]?[A-Za-z]?$"
)


def _extract_ref_prefix(reference: str) -> str:
    """Return the alphabetic prefix of a reference designator.

    Example: "R12" -> "R", "C3" -> "C", "U1" -> "U".
    """
    prefix = ""
    for ch in reference:
        if ch.isalpha():
            prefix += ch
        else:
            break
    return prefix


def _is_generic_part(comp: ParsedComponent) -> bool:
    """Determine whether a component is a generic/passive part.

    A component is generic if:
    - Its lib_id starts with a known generic prefix (e.g. "Device:"), OR
    - Its reference prefix is a passive type AND the value looks like a
      simple number+unit pattern (e.g. "100nF", "10k", "4.7uF").
    """
    # Check lib_id prefix first.
    for prefix in _GENERIC_LIB_PREFIXES:
        if comp.lib_id.startswith(prefix):
            return True

    # Check reference prefix + value pattern.
    ref_prefix = _extract_ref_prefix(comp.reference)
    if ref_prefix in _PASSIVE_REF_PREFIXES and _PASSIVE_VALUE_RE.match(
        comp.value.strip()
    ):
        return True

    return False


def _extract_mpn(comp: ParsedComponent) -> str:
    """Extract the manufacturer part number from a component.

    Priority order:
    1. Explicit MPN or Manufacturer_Part_Number property.
    2. Colon-suffix of lib_id (e.g. "MCU_ST_STM32:STM32F103CBT6" -> "STM32F103CBT6").
    3. Fallback to comp.value.
    """
    # 1. Explicit property.
    mpn = comp.properties.get("MPN") or comp.properties.get(
        "Manufacturer_Part_Number"
    )
    if mpn:
        return mpn.strip()

    # 2. lib_id colon suffix.
    if ":" in comp.lib_id:
        suffix = comp.lib_id.split(":", 1)[1]
        if suffix:
            return suffix.strip()

    # 3. Fallback.
    return comp.value


def _extract_datasheet_url(comp: ParsedComponent) -> str | None:
    """Extract a datasheet URL from component properties, if present."""
    url = comp.properties.get("Datasheet", "")
    if url.startswith("http"):
        return url
    return None


def normalize_part(comp: ParsedComponent) -> NormalizedPartNumber:
    """Normalize a single parsed component into a NormalizedPartNumber.

    Extracts the MPN, manufacturer, datasheet URL, and determines whether
    the part is a generic passive.

    Args:
        comp: A parsed KiCad component.

    Returns:
        A NormalizedPartNumber with extracted metadata.
    """
    return NormalizedPartNumber(
        raw_value=comp.value,
        mpn=_extract_mpn(comp),
        manufacturer=comp.properties.get("Manufacturer", ""),
        is_generic=_is_generic_part(comp),
        datasheet_url=_extract_datasheet_url(comp),
    )


def normalize_schematic_parts(
    schematic: ParsedSchematic,
) -> list[NormalizedPartNumber]:
    """Normalize all components in a parsed schematic.

    Args:
        schematic: A fully parsed KiCad schematic.

    Returns:
        A list of NormalizedPartNumber for each component.
    """
    return [normalize_part(comp) for comp in schematic.components]
