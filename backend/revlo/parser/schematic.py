"""Main schematic parser using kicad-sch-api.

Loads a .kicad_sch file and returns a fully populated ParsedSchematic model.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import kicad_sch_api as ksa
from kicad_sch_api.core.connectivity import Net
from kicad_sch_api.core.types import PinShape, PinType, Point, SchematicPin

from revlo.parser.connectivity import build_merged_net_list, build_nets_from_netlist
from revlo.parser.models import (
    ParsedComponent,
    ParsedPin,
    ParsedSchematic,
    ParsedSheet,
    TitleBlockInfo,
)
from revlo.parser.netlist import NetlistData

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


# ---------------------------------------------------------------------------
# KiCad 9 pin patching
# ---------------------------------------------------------------------------
# KiCad 9 stores pin references (pin_uuids) in component instances but does
# not populate the ``pins`` list on ``SchematicSymbol``.  The actual pin
# definitions exist in the embedded ``(lib_symbols ...)`` section of the raw
# file content.  We parse them here and inject ``SchematicPin`` objects so
# that the kicad-sch-api connectivity analyser can trace wires to pins.

_PIN_TYPE_MAP: dict[str, PinType] = {
    "input": PinType.INPUT,
    "output": PinType.OUTPUT,
    "bidirectional": PinType.BIDIRECTIONAL,
    "passive": PinType.PASSIVE,
    "power_in": PinType.POWER_IN,
    "power_out": PinType.POWER_OUT,
    "tri_state": PinType.TRISTATE,
    "open_collector": PinType.OPEN_COLLECTOR,
    "open_emitter": PinType.OPEN_EMITTER,
    "unspecified": PinType.UNSPECIFIED,
    "free": PinType.FREE,
    "no_connect": PinType.NO_CONNECT,
}

_PIN_SHAPE_MAP: dict[str, PinShape] = {
    "line": PinShape.LINE,
    "inverted": PinShape.INVERTED,
    "clock": PinShape.CLOCK,
    "inverted_clock": PinShape.INVERTED_CLOCK,
    "input_low": PinShape.INPUT_LOW,
    "clock_low": PinShape.CLOCK_LOW,
    "output_low": PinShape.OUTPUT_LOW,
    "edge_clock_high": PinShape.EDGE_CLOCK_HIGH,
    "non_logic": PinShape.NON_LOGIC,
}

# Regex to extract individual pin blocks with positional data from a symbol
# S-expression.  Captures: pin_type, pin_shape, then we parse sub-elements.
_PIN_BLOCK_RE = re.compile(
    r"\(pin\s+(\w+)\s+(\w+)\s+"  # (pin TYPE SHAPE
    r"(.*?)"                       # body with (at ...) (length ...) etc.
    r"\)\s*\)\s*\)",               # close number, close pin
    re.DOTALL,
)

# Sub-element regexes for pin block body
_PIN_AT_RE = re.compile(
    r"\(at\s+([-\d.]+)\s+([-\d.]+)(?:\s+([-\d.]+))?\s*\)",
)
_PIN_LENGTH_RE = re.compile(r"\(length\s+([-\d.]+)\s*\)")
_PIN_NAME_RE = re.compile(r'\(name\s+"([^"]*)"')
_PIN_NUMBER_RE = re.compile(r'\(number\s+"([^"]*)"')


def _extract_symbol_block(raw_content: str, lib_id: str) -> str:
    """Extract the ``(symbol "<lib_id>" ...)`` S-expression block.

    Returns the full block string, or empty string if not found.
    """
    marker = f'(symbol "{lib_id}"'
    start = raw_content.find(marker)
    if start == -1:
        return ""

    depth = 0
    for i in range(start, len(raw_content)):
        if raw_content[i] == "(":
            depth += 1
        elif raw_content[i] == ")":
            depth -= 1
            if depth == 0:
                return raw_content[start : i + 1]
    return ""


def _parse_pins_from_symbol_block(
    symbol_block: str,
) -> dict[str, SchematicPin]:
    """Parse all ``(pin ...)`` definitions from a lib_symbol S-expression block.

    Searches recursively through all sub-symbols (e.g. ``R_1_1``,
    ``MSPM0G3507SPTR_1_1``) to collect every pin.

    Returns:
        Mapping of pin_number to ``SchematicPin`` with LOCAL coordinates
        (relative to the symbol origin).
    """
    pins: dict[str, SchematicPin] = {}

    # Find all (pin ...) blocks using parenthesis-balanced extraction
    idx = 0
    while True:
        pin_start = symbol_block.find("(pin ", idx)
        if pin_start == -1:
            break

        # Balanced-paren extraction of this pin block
        depth = 0
        pin_end = pin_start
        for i in range(pin_start, len(symbol_block)):
            if symbol_block[i] == "(":
                depth += 1
            elif symbol_block[i] == ")":
                depth -= 1
                if depth == 0:
                    pin_end = i + 1
                    break

        pin_text = symbol_block[pin_start:pin_end]
        idx = pin_end

        # Parse the pin block
        pin = _parse_single_pin_block(pin_text)
        if pin is not None:
            pins[pin.number] = pin

    return pins


def _parse_single_pin_block(pin_text: str) -> SchematicPin | None:
    """Parse a single ``(pin TYPE SHAPE ...)`` S-expression into a SchematicPin."""
    # Extract type and shape from the opening
    head_match = re.match(r"\(pin\s+(\w+)\s+(\w+)", pin_text)
    if not head_match:
        return None

    pin_type_str = head_match.group(1)
    pin_shape_str = head_match.group(2)

    # Extract sub-elements
    at_match = _PIN_AT_RE.search(pin_text)
    length_match = _PIN_LENGTH_RE.search(pin_text)
    name_match = _PIN_NAME_RE.search(pin_text)
    number_match = _PIN_NUMBER_RE.search(pin_text)

    if not number_match:
        return None

    x = float(at_match.group(1)) if at_match else 0.0
    y = float(at_match.group(2)) if at_match else 0.0
    rotation = float(at_match.group(3)) if at_match and at_match.group(3) else 0.0
    length = float(length_match.group(1)) if length_match else 2.54
    name = name_match.group(1) if name_match else ""
    number = number_match.group(1)

    return SchematicPin(
        number=number,
        name=name,
        position=Point(x=x, y=y),
        pin_type=_PIN_TYPE_MAP.get(pin_type_str, PinType.PASSIVE),
        pin_shape=_PIN_SHAPE_MAP.get(pin_shape_str, PinShape.LINE),
        length=length,
        rotation=rotation,
    )


def _patch_kicad9_pins(sch: ksa.Schematic) -> None:
    """Populate empty ``comp._data.pins`` from embedded lib_symbols for KiCad 9.

    KiCad 9 stores pin references (``pin_uuids``) in component instances but
    does not populate the ``pins`` list.  The actual pin definitions exist in
    the embedded ``(lib_symbols ...)`` section.  This function resolves them
    so that the kicad-sch-api connectivity analyser can trace wires to pins.

    This must be called RIGHT AFTER loading the schematic and BEFORE any
    connectivity analysis runs.
    """
    raw_content: str = sch._data.get("_original_content", "")
    if not raw_content:
        return

    # Cache of lib_id -> {pin_number: SchematicPin} from embedded lib_symbols
    lib_pin_cache: dict[str, dict[str, SchematicPin]] = {}

    for comp in sch.components:
        # Only patch components that have empty pins but non-empty pin_uuids
        if comp._data.pins:
            continue
        if not (hasattr(comp._data, "pin_uuids") and comp._data.pin_uuids):
            continue

        lib_id = comp.lib_id
        if lib_id not in lib_pin_cache:
            symbol_block = _extract_symbol_block(raw_content, lib_id)
            if symbol_block:
                lib_pin_cache[lib_id] = _parse_pins_from_symbol_block(
                    symbol_block,
                )
            else:
                lib_pin_cache[lib_id] = {}

        cached_pins = lib_pin_cache[lib_id]
        if not cached_pins:
            continue

        # Build the pins list using only pins that appear in pin_uuids
        # (these are the pins actually placed on this component instance).
        new_pins: list[SchematicPin] = []
        for pin_num in comp._data.pin_uuids:
            if pin_num in cached_pins:
                new_pins.append(cached_pins[pin_num])
            else:
                # Pin number in pin_uuids but not in lib_symbol -- create a
                # minimal placeholder so connectivity still has something.
                new_pins.append(
                    SchematicPin(
                        number=pin_num,
                        name=pin_num,
                        position=Point(x=0.0, y=0.0),
                    )
                )

        comp._data.pins = new_pins
        logger.debug(
            "Patched %d pins onto %s (%s)",
            len(new_pins),
            comp.reference,
            lib_id,
        )


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


def parse_schematic(path: str, netlist: NetlistData | None = None) -> ParsedSchematic:
    """Parse a KiCad schematic file into a structured ParsedSchematic model.

    Recursively discovers and loads hierarchical sub-sheets so that all
    components in a KiCad project are visible to the review engine.

    Args:
        path: Filesystem path to a .kicad_sch file.
        netlist: Optional ground-truth netlist data from kicad-cli export.
            When provided, pin connectivity is sourced from this data instead
            of kicad-sch-api's connectivity analyser.

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

    # Patch KiCad 9 empty pins from embedded lib_symbols BEFORE any
    # connectivity analysis runs.
    _patch_kicad9_pins(sch)

    title_block = _extract_title_block(sch)
    components, power_symbols = _extract_components(sch, netlist=netlist)
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
        netlist=netlist,
    )

    # Build nets: prefer ground-truth netlist when available.
    if netlist is not None:
        nets, unconnected_pins = build_nets_from_netlist(
            netlist, all_components + all_power_symbols
        )
    else:
        # Existing kicad-sch-api path
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
    netlist: NetlistData | None = None,
) -> None:
    """Recursively load hierarchical sub-sheets and collect their components.

    Args:
        parent_dir: Directory of the parent schematic (for relative path resolution).
        sheets: Parsed sheet metadata from the parent schematic.
        all_components: Accumulator for regular components across all sheets.
        all_power_symbols: Accumulator for power symbols across all sheets.
        sheet_pairs: Accumulator of (schematic, all_components) pairs for net merging.
        visited: Set of resolved absolute paths already visited (cycle detection).
        netlist: Optional ground-truth netlist data for pin connectivity.
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

        _patch_kicad9_pins(sub_sch)

        sub_components, sub_power = _extract_components(
            sub_sch,
            source_sheet=sheet.name,
            sheet_instance_uuid=sheet.uuid,
            netlist=netlist,
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
                netlist=netlist,
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
    netlist: NetlistData | None = None,
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
        netlist: Optional ground-truth netlist data for pin connectivity.

    Returns:
        A tuple of (regular_components, power_symbols).
    """
    components: list[ParsedComponent] = []
    power_symbols: list[ParsedComponent] = []

    for comp in sch.components:
        resolved_ref = _resolve_instance_reference(comp, sheet_instance_uuid)
        pins = _extract_pins(sch, comp, netlist=netlist, resolved_ref=resolved_ref)

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


def _extract_pins(
    sch: ksa.Schematic,
    comp: ksa.Component,
    netlist: NetlistData | None = None,
    resolved_ref: str | None = None,
) -> list[ParsedPin]:
    """Extract pin data for a single component, including net connectivity.

    Supports two code paths:

    * **KiCad 6/7/8** -- ``comp.pins`` is populated directly by
      kicad-sch-api.
    * **KiCad 9** -- ``comp.pins`` is empty, but ``comp._data.pin_uuids``
      contains a ``{pin_number: uuid}`` dict.  Pin metadata (name,
      electrical type) is resolved from library symbols or the embedded
      ``(lib_symbols ...)`` section.

    When *netlist* is provided, pin connectivity comes from the ground-truth
    netlist data rather than kicad-sch-api's connectivity analyser.
    """
    parsed_pins: list[ParsedPin] = []
    # The netlist uses annotated refs (e.g. U1), so prefer resolved_ref.
    ref_for_netlist = resolved_ref or comp.reference

    if comp.pins:
        # Original path for KiCad 6/7/8.
        for pin in comp.pins:
            pin_pos = comp.get_pin_position(pin.number)
            position = (pin_pos.x, pin_pos.y) if pin_pos else (0.0, 0.0)

            if netlist is not None:
                connected_net = netlist.pin_nets.get(
                    (ref_for_netlist, pin.number)
                )
            else:
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

            if netlist is not None:
                connected_net = netlist.pin_nets.get(
                    (ref_for_netlist, pin_num)
                )
            else:
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
