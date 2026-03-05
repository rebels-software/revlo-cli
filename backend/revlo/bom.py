"""BOM ingestion helpers for Revlo reviews.

CSV is the preferred interchange format for the first BOM foundation pass.
Supported columns are case-insensitive and may use common aliases such as:

- ``ref`` / ``refs`` / ``reference`` / ``designator``
- ``value``
- ``footprint`` / ``package``
- ``manufacturer``
- ``mpn`` / ``manufacturer_part_number`` / ``mfr_part_number``
- ``supplier``
- ``supplier_pn`` / ``supplier_part_number`` / ``sku``
- ``quantity`` / ``qty``
"""

from __future__ import annotations

import csv
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

_REF_HEADERS = ("ref", "refs", "reference", "references", "designator", "designators")
_VALUE_HEADERS = ("value",)
_FOOTPRINT_HEADERS = ("footprint", "package")
_MANUFACTURER_HEADERS = ("manufacturer", "mfr")
_MPN_HEADERS = ("mpn", "manufacturer_part_number", "mfr_part_number")
_SUPPLIER_HEADERS = ("supplier", "vendor", "distributor")
_SUPPLIER_PN_HEADERS = ("supplier_pn", "supplier_part_number", "sku", "supplier_sku")
_QUANTITY_HEADERS = ("quantity", "qty")


def _canonical_key(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


class BomItem(BaseModel):
    refs: list[str] = Field(default_factory=list)
    value: str = ""
    footprint: str = ""
    manufacturer: str = ""
    mpn: str = ""
    supplier: str = ""
    supplier_pn: str = ""
    quantity: int | None = None

    @field_validator("refs", mode="before")
    @classmethod
    def _normalize_refs(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            parts = [part.strip().upper() for part in value.replace(";", ",").split(",")]
            return [part for part in parts if part]
        return value


class BomDocument(BaseModel):
    schematic: str = ""
    source_path: str = ""
    items: list[BomItem] = Field(default_factory=list)


def bom_path_for_schematic(
    schematic_path: str | Path,
    override_path: str | Path | None = None,
) -> Path:
    """Resolve the active BOM path for a schematic."""
    if override_path is not None:
        return Path(override_path).expanduser()
    schematic = Path(schematic_path)
    return schematic.with_name(f"{schematic.stem}.revlo-bom.csv")


def _pick_field(row: dict[str, str], *candidates: str) -> str:
    for candidate in candidates:
        if candidate in row and row[candidate].strip():
            return row[candidate].strip()
    return ""


def load_bom(
    schematic_path: str | Path,
    override_path: str | Path | None = None,
) -> BomDocument | None:
    """Load a CSV BOM for a schematic, if present."""
    path = bom_path_for_schematic(schematic_path, override_path)
    if not path.exists():
        return None

    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ValueError(f"Invalid BOM file at {path}: missing header row")

            canonical_fields = [_canonical_key(name) for name in reader.fieldnames]
            if not any(field in canonical_fields for field in _REF_HEADERS):
                raise ValueError(
                    f"Invalid BOM file at {path}: missing reference/designator column"
                )

            items: list[BomItem] = []
            for raw_row in reader:
                row = {_canonical_key(key): (value or "") for key, value in raw_row.items()}
                refs = _pick_field(row, *_REF_HEADERS)
                if not refs:
                    continue
                quantity_raw = _pick_field(row, *_QUANTITY_HEADERS)
                quantity = None
                if quantity_raw:
                    try:
                        quantity = int(quantity_raw)
                    except ValueError as exc:
                        raise ValueError(
                            f"Invalid BOM file at {path}: quantity '{quantity_raw}' is not an integer"
                        ) from exc
                items.append(
                    BomItem(
                        refs=refs,
                        value=_pick_field(row, *_VALUE_HEADERS),
                        footprint=_pick_field(row, *_FOOTPRINT_HEADERS),
                        manufacturer=_pick_field(row, *_MANUFACTURER_HEADERS),
                        mpn=_pick_field(row, *_MPN_HEADERS),
                        supplier=_pick_field(row, *_SUPPLIER_HEADERS),
                        supplier_pn=_pick_field(row, *_SUPPLIER_PN_HEADERS),
                        quantity=quantity,
                    )
                )
    except OSError as exc:
        raise ValueError(f"Invalid BOM file at {path}: {exc}") from exc

    return BomDocument(
        schematic=Path(schematic_path).name,
        source_path=str(path),
        items=items,
    )
