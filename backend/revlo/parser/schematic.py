"""Main schematic parser using kicad-sch-api.

Loads a .kicad_sch file and returns a fully populated ParsedSchematic model.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import kicad_sch_api as ksa
from kicad_sch_api.core.connectivity import Net

from revlo.parser.connectivity import build_merged_net_list
from revlo.parser.models import (
    ParsedComponent,
    ParsedPin,
    ParsedSchematic,
    ParsedSheet,
    TitleBlockInfo,
)

logger = logging.getLogger(__name__)


def _patch_net_hash() -> None:
    """Monkey-patch ``Net.__hash__`` to fix ``unhashable type: 'Net'``.

    kicad-sch-api's ``Net`` dataclass uses ``eq=True`` (the default) with
    mutable ``Set`` fields, causing Python to set ``__hash__ = None``.  The
    connectivity analyser then crashes when it tries to add a ``Net`` to a
    ``set``.  An identity-based hash is correct here because net merging in
    kicad-sch-api uses object identity.
    """
    if not getattr(Net, "_hash_patched", False):
        Net.__hash__ = lambda self: id(self)  # type: ignore[assignment]
        Net._hash_patched = True  # type: ignore[attr-defined]


# Apply the patch at import time so any code path that touches connectivity
# (including ``build_net_list`` and ``get_net_for_pin``) is safe.
_patch_net_hash()


def _detect_unsupported_format(sch_path: Path) -> None:
    """Detect legacy KiCad 5 or Eagle schematic formats and raise helpful errors.

    Reads the first few lines of the file to identify unsupported formats
    before kicad-sch-api attempts to parse it (which would give a generic error).

    Raises:
        ValueError: If the file is a recognised but unsupported format.
    """
    try:
        head = sch_path.read_text(encoding="utf-8", errors="ignore")[:2048]
    except OSError:
        return  # If we can't read the file, let ksa.Schematic.load() handle it

    if head.startswith("EESchema Schematic File Version"):
        raise ValueError(
            "This is a KiCad 5 (EESchema) file. Revlo only supports KiCad 6+ "
            "(.kicad_sch) format. Please open this file in KiCad 8 or 9 and "
            "re-save it to convert to the modern format."
        )

    if head.lstrip().startswith("<?xml") and "<eagle" in head:
        raise ValueError(
            "This is an Eagle schematic file. Revlo only supports KiCad 6+ "
            "(.kicad_sch) format."
        )

    if sch_path.suffix == ".sch":
        raise ValueError(
            "Unsupported schematic format. Revlo only supports KiCad 6+ "
            "(.kicad_sch) files."
        )


def parse_schematic(path: str) -> ParsedSchematic:
    """Parse a KiCad schematic file into a structured ParsedSchematic model.

    Recursively discovers and loads hierarchical sub-sheets so that all
    components in a KiCad project are visible to the review engine.

    Args:
        path: Filesystem path to a .kicad_sch file.

    Returns:
        A fully populated ParsedSchematic instance with components from all
        sheets flattened into a single list.

    Raises:
        FileNotFoundError: If the schematic file does not exist.
        ValueError: If the file is a recognised but unsupported format.
        kicad_sch_api.ValidationError: If the file cannot be parsed.
    """
    sch_path = Path(path)
    if not sch_path.exists():
        raise FileNotFoundError(f"Schematic file not found: {path}")

    _detect_unsupported_format(sch_path)

    sch = ksa.Schematic.load(str(sch_path))

    title_block = _extract_title_block(sch)
    components, power_symbols = _extract_components(sch)
    sheets = _extract_sheets(sch)

    # Collect (schematic, components) pairs for merged net building.
    # Start with root sheet.
    sheet_pairs: list[tuple[ksa.Schematic, list[ParsedComponent]]] = [
        (sch, components + power_symbols),
    ]

    # Recursively load sub-sheets.
    visited: set[str] = {str(sch_path.resolve())}
    all_components = list(components)
    all_power_symbols = list(power_symbols)

    _load_sub_sheets(
        parent_dir=sch_path.parent,
        sheets=sheets,
        all_components=all_components,
        all_power_symbols=all_power_symbols,
        sheet_pairs=sheet_pairs,
        visited=visited,
    )

    # Build merged nets across all sheets.
    nets, unconnected_pins = build_merged_net_list(sheet_pairs)

    return ParsedSchematic(
        components=all_components,
        nets=nets,
        power_symbols=all_power_symbols,
        sheets=sheets,
        unconnected_pins=unconnected_pins,
        title_block=title_block,
    )


def _load_sub_sheets(
    parent_dir: Path,
    sheets: list[ParsedSheet],
    all_components: list[ParsedComponent],
    all_power_symbols: list[ParsedComponent],
    sheet_pairs: list[tuple[ksa.Schematic, list[ParsedComponent]]],
    visited: set[str],
) -> None:
    """Recursively load hierarchical sub-sheets and collect their components.

    Args:
        parent_dir: Directory of the parent schematic (for relative path resolution).
        sheets: Parsed sheet metadata from the parent schematic.
        all_components: Accumulator for regular components across all sheets.
        all_power_symbols: Accumulator for power symbols across all sheets.
        sheet_pairs: Accumulator of (schematic, all_components) pairs for net merging.
        visited: Set of resolved absolute paths already visited (cycle detection).
    """
    for sheet in sheets:
        sub_path = parent_dir / sheet.filename
        resolved = str(sub_path.resolve())

        # Cycle detection: skip if already visited.
        if resolved in visited:
            logger.debug(
                "Skipping already-visited sub-sheet: %s", sheet.filename,
            )
            continue

        if not sub_path.is_file():
            logger.warning(
                "Sub-sheet file not found, skipping: %s", sub_path,
            )
            continue

        visited.add(resolved)

        try:
            sub_sch = ksa.Schematic.load(str(sub_path))
        except Exception:
            logger.warning(
                "Failed to load sub-sheet, skipping: %s", sub_path,
                exc_info=True,
            )
            continue

        sub_components, sub_power = _extract_components(
            sub_sch,
            source_sheet=sheet.name,
            sheet_instance_uuid=sheet.uuid,
        )
        all_components.extend(sub_components)
        all_power_symbols.extend(sub_power)
        sheet_pairs.append((sub_sch, sub_components + sub_power))

        # Recurse into sub-sub-sheets.
        sub_sheets = _extract_sheets(sub_sch)
        if sub_sheets:
            _load_sub_sheets(
                parent_dir=sub_path.parent,
                sheets=sub_sheets,
                all_components=all_components,
                all_power_symbols=all_power_symbols,
                sheet_pairs=sheet_pairs,
                visited=visited,
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


def _extract_properties(raw_props: dict | None) -> dict[str, str]:
    """Normalise component properties to a flat name->value string dict.

    kicad-sch-api returns a dict where:
    - Keys starting with ``__sexp_`` hold raw s-expression lists (skip them).
    - Other keys map to dicts with a ``'value'`` entry (extract it as str).
    - Occasionally a value may already be a plain string.

    Returns:
        A ``dict[str, str]`` suitable for the Pydantic model.
    """
    if not raw_props:
        return {}

    result: dict[str, str] = {}
    for key, val in raw_props.items():
        if key.startswith("__sexp_"):
            continue
        if isinstance(val, dict):
            result[key] = str(val.get("value", ""))
        elif isinstance(val, str):
            result[key] = val
        else:
            result[key] = str(val)
    return result


def _resolve_instance_reference(
    comp: ksa.Component,
    sheet_instance_uuid: str,
) -> str:
    """Resolve a component's annotated reference from its hierarchical instances.

    KiCad stores annotated references (e.g. ``U1``, ``C5``) in the
    ``instances`` section of each component.  The correct instance for a
    sub-sheet is the one whose ``.path`` ends with ``/<sheet_uuid>``.

    Args:
        comp: A kicad-sch-api Component object.
        sheet_instance_uuid: The UUID of the hierarchical sheet that contains
            this component.  Empty string means "do not resolve".

    Returns:
        The resolved reference string, or the component's default reference
        if no matching instance is found.
    """
    if not sheet_instance_uuid:
        return comp.reference

    suffix = f"/{sheet_instance_uuid}"
    try:
        instances = comp._data.instances
    except AttributeError:
        return comp.reference

    if not instances:
        return comp.reference

    for inst in instances:
        if inst.path.endswith(suffix):
            return inst.reference

    return comp.reference


def _extract_components(
    sch: ksa.Schematic,
    source_sheet: str = "",
    sheet_instance_uuid: str = "",
) -> tuple[list[ParsedComponent], list[ParsedComponent]]:
    """Extract components and separate power symbols.

    Args:
        sch: A loaded kicad_sch_api Schematic instance.
        source_sheet: Name of the sheet these components belong to.
            Empty string means root sheet.
        sheet_instance_uuid: UUID of the hierarchical sheet instance.
            When provided, component references are resolved from the
            ``instances`` section of the KiCad file so that sub-sheet
            components get their annotated designators (e.g. ``U1``
            instead of ``U?``).

    Returns:
        A tuple of (regular_components, power_symbols).
    """
    components: list[ParsedComponent] = []
    power_symbols: list[ParsedComponent] = []

    for comp in sch.components:
        resolved_ref = _resolve_instance_reference(comp, sheet_instance_uuid)
        pins = _extract_pins(sch, comp)

        parsed = ParsedComponent(
            reference=resolved_ref,
            value=comp.value,
            lib_id=comp.lib_id,
            footprint=comp.footprint or "",
            position=(comp.position.x, comp.position.y),
            rotation=comp.rotation,
            pins=pins,
            properties=_extract_properties(comp.properties),
            source_sheet=source_sheet,
        )

        if resolved_ref.startswith("#PWR"):
            power_symbols.append(parsed)
        else:
            components.append(parsed)

    return components, power_symbols


def _get_net_name(
    sch: ksa.Schematic,
    ref: str,
    pin_num: str,
) -> str | None:
    """Safely resolve the net name for a component pin.

    Wraps ``sch.get_net_for_pin`` with error handling so that a single
    failing pin does not abort the entire parse.
    """
    try:
        net = sch.get_net_for_pin(ref, pin_num)
        return net.name if net else None
    except Exception:
        logger.debug("Could not resolve net for %s pin %s", ref, pin_num)
        return None


# Regex for extracting pin definitions from a raw lib_symbols S-expression
# block.  Matches: (pin TYPE SHAPE ... (name "NAME" ...) (number "NUM" ...))
_SEXP_PIN_RE = re.compile(
    r"\(pin\s+(\w+)\s+\w+\s+.*?"
    r"\(name\s+\"([^\"]*)\"\s*.*?\)\s*"
    r"\(number\s+\"([^\"]*)\"\s*.*?\)\s*\)",
    re.DOTALL,
)


def _get_lib_symbol_pins(
    sch: ksa.Schematic,
    lib_id: str,
) -> dict[str, dict[str, str]]:
    """Look up pin metadata from the library symbol matching *lib_id*.

    Returns a mapping ``{pin_number: {"name": ..., "type": ...}}``.

    Two resolution strategies are tried in order:

    1. **Library cache** -- ``sch.library.get_symbol(lib_id)`` works for
       standard KiCad libraries (``Device:``, ``power:``, etc.).
    2. **Raw S-expression fallback** -- for custom / project-specific
       libraries whose ``.kicad_sym`` files are not installed, the symbol
       definition still exists inside the schematic's embedded
       ``(lib_symbols ...)`` section.  We parse it with a lightweight
       regex.
    """
    pins: dict[str, dict[str, str]] = {}

    # --- Strategy 1: library cache -------------------------------------------
    try:
        sym = sch.library.get_symbol(lib_id)
    except Exception:
        sym = None

    if sym and sym.pins:
        for p in sym.pins:
            pin_type = (
                p.pin_type.value
                if hasattr(p.pin_type, "value")
                else str(p.pin_type)
            )
            pins[p.number] = {"name": p.name, "type": pin_type}
        return pins

    # --- Strategy 2: raw S-expression in embedded lib_symbols ----------------
    raw_content: str = sch._data.get("_original_content", "")
    if not raw_content:
        return pins

    # Locate the ``(symbol "<lib_id>" ...)`` block inside ``(lib_symbols ...)``.
    marker = f'(symbol "{lib_id}"'
    start = raw_content.find(marker)
    if start == -1:
        return pins

    # Walk forward counting parentheses to find the matching close-paren.
    depth = 0
    end = start
    for i in range(start, len(raw_content)):
        ch = raw_content[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    symbol_block = raw_content[start:end]

    for match in _SEXP_PIN_RE.finditer(symbol_block):
        pin_type_raw, pin_name, pin_number = match.groups()
        pins[pin_number] = {"name": pin_name, "type": pin_type_raw}

    return pins


def _extract_pins(sch: ksa.Schematic, comp: ksa.Component) -> list[ParsedPin]:
    """Extract pin data for a single component, including net connectivity.

    Supports two code paths:

    * **KiCad 6/7/8** -- ``comp.pins`` is populated directly by
      kicad-sch-api.
    * **KiCad 9** -- ``comp.pins`` is empty, but ``comp._data.pin_uuids``
      contains a ``{pin_number: uuid}`` dict.  Pin metadata (name,
      electrical type) is resolved from library symbols or the embedded
      ``(lib_symbols ...)`` section.
    """
    parsed_pins: list[ParsedPin] = []

    if comp.pins:
        # Original path for KiCad 6/7/8.
        for pin in comp.pins:
            pin_pos = comp.get_pin_position(pin.number)
            position = (pin_pos.x, pin_pos.y) if pin_pos else (0.0, 0.0)
            connected_net = _get_net_name(sch, comp.reference, pin.number)

            parsed_pins.append(
                ParsedPin(
                    number=pin.number,
                    name=pin.name,
                    position=position,
                    electrical_type=(
                        pin.pin_type.value
                        if hasattr(pin.pin_type, "value")
                        else str(pin.pin_type)
                    ),
                    connected_net=connected_net,
                )
            )
    elif hasattr(comp._data, "pin_uuids") and comp._data.pin_uuids:
        # Fallback for KiCad 9 where comp.pins is empty.
        lib_pins = _get_lib_symbol_pins(sch, comp.lib_id)

        for pin_num in comp._data.pin_uuids:
            lib_pin = lib_pins.get(pin_num, {})
            pin_name = lib_pin.get("name", pin_num)
            electrical_type = lib_pin.get("type", "passive")

            try:
                pin_pos = comp.get_pin_position(pin_num)
                position = (
                    (pin_pos.x, pin_pos.y) if pin_pos else (0.0, 0.0)
                )
            except Exception:
                position = (0.0, 0.0)

            connected_net = _get_net_name(sch, comp.reference, pin_num)

            parsed_pins.append(
                ParsedPin(
                    number=pin_num,
                    name=pin_name,
                    position=position,
                    electrical_type=electrical_type,
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
        uuid = sheet_data.get("uuid", "")
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
                uuid=uuid,
                pins=pins,
            )
        )

    return sheets
