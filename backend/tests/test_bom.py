"""Tests for BOM ingestion foundations."""

from __future__ import annotations

from pathlib import Path

import pytest

from revlo.bom import BomDocument, bom_path_for_schematic, load_bom


def test_bom_path_defaults_to_sidecar_name(tmp_path: Path):
    schematic = tmp_path / "board.kicad_sch"
    assert bom_path_for_schematic(schematic) == tmp_path / "board.revlo-bom.csv"


def test_load_bom_returns_none_when_missing(tmp_path: Path):
    schematic = tmp_path / "board.kicad_sch"
    schematic.write_text("(kicad_sch ...)")
    assert load_bom(schematic) is None


def test_load_bom_reads_csv_sidecar(tmp_path: Path):
    schematic = tmp_path / "board.kicad_sch"
    schematic.write_text("(kicad_sch ...)")
    bom = tmp_path / "board.revlo-bom.csv"
    bom.write_text(
        "Ref,Value,Footprint,Manufacturer,MPN,Supplier,Supplier_PN,Qty\n"
        "U1,STM32F103,LQFP-48,ST,STM32F103C8T6,Mouser,511-STM32F103C8T6,1\n"
        "\"C1,C2\",100nF,0402,,CL05B104,, ,2\n"
    )

    loaded = load_bom(schematic)

    assert loaded == BomDocument(
        schematic="board.kicad_sch",
        source_path=str(bom),
        items=[
            {
                "refs": ["U1"],
                "value": "STM32F103",
                "footprint": "LQFP-48",
                "manufacturer": "ST",
                "mpn": "STM32F103C8T6",
                "supplier": "Mouser",
                "supplier_pn": "511-STM32F103C8T6",
                "quantity": 1,
            },
            {
                "refs": ["C1", "C2"],
                "value": "100nF",
                "footprint": "0402",
                "manufacturer": "",
                "mpn": "CL05B104",
                "supplier": "",
                "supplier_pn": "",
                "quantity": 2,
            },
        ],
    )


def test_load_bom_uses_override_path(tmp_path: Path):
    schematic = tmp_path / "board.kicad_sch"
    schematic.write_text("(kicad_sch ...)")
    bom = tmp_path / "custom.csv"
    bom.write_text("Designator,Value,Qty\nR1,10k,1\n")

    loaded = load_bom(schematic, bom)

    assert loaded is not None
    assert loaded.source_path == str(bom)
    assert loaded.items[0].refs == ["R1"]


def test_load_bom_rejects_missing_reference_column(tmp_path: Path):
    schematic = tmp_path / "board.kicad_sch"
    schematic.write_text("(kicad_sch ...)")
    bom = tmp_path / "board.revlo-bom.csv"
    bom.write_text("Value,Qty\n10k,1\n")

    with pytest.raises(ValueError, match="missing reference/designator column"):
        load_bom(schematic)


def test_load_bom_rejects_invalid_quantity(tmp_path: Path):
    schematic = tmp_path / "board.kicad_sch"
    schematic.write_text("(kicad_sch ...)")
    bom = tmp_path / "board.revlo-bom.csv"
    bom.write_text("Ref,Qty\nR1,one\n")

    with pytest.raises(ValueError, match="quantity 'one' is not an integer"):
        load_bom(schematic)
