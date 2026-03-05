"""Tests for structured project constraints loading."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from revlo.constraints import (
    ProjectConstraints,
    constraints_path_for_schematic,
    load_project_constraints,
)


def test_constraints_path_defaults_to_sidecar_name(tmp_path: Path):
    schematic = tmp_path / "board.kicad_sch"
    path = constraints_path_for_schematic(schematic)
    assert path == tmp_path / "board.revlo-constraints.json"


def test_load_project_constraints_returns_none_when_missing(tmp_path: Path):
    schematic = tmp_path / "board.kicad_sch"
    schematic.write_text("(kicad_sch ...)")
    assert load_project_constraints(schematic) is None


def test_load_project_constraints_reads_sidecar(tmp_path: Path):
    schematic = tmp_path / "board.kicad_sch"
    schematic.write_text("(kicad_sch ...)")
    sidecar = tmp_path / "board.revlo-constraints.json"
    sidecar.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "constraints": [
                    {
                        "kind": "rail_voltage",
                        "name": "Main 3V3 rail",
                        "target": "3V3",
                        "value": "3.3",
                        "unit": "V",
                    }
                ],
            }
        )
    )

    loaded = load_project_constraints(schematic)

    assert loaded == ProjectConstraints(
        schema_version=1,
        schematic="board.kicad_sch",
        constraints=[
            {
                "kind": "rail_voltage",
                "name": "Main 3V3 rail",
                "target": "3V3",
                "value": "3.3",
                "unit": "V",
                "notes": "",
            }
        ],
        source_path=str(sidecar),
    )


def test_load_project_constraints_uses_override_path(tmp_path: Path):
    schematic = tmp_path / "board.kicad_sch"
    schematic.write_text("(kicad_sch ...)")
    override = tmp_path / "constraints.json"
    override.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "schematic": "custom-name.kicad_sch",
                "constraints": [],
            }
        )
    )

    loaded = load_project_constraints(schematic, override)

    assert loaded is not None
    assert loaded.source_path == str(override)
    assert loaded.schematic == "custom-name.kicad_sch"


def test_load_project_constraints_rejects_invalid_json(tmp_path: Path):
    schematic = tmp_path / "board.kicad_sch"
    schematic.write_text("(kicad_sch ...)")
    sidecar = tmp_path / "board.revlo-constraints.json"
    sidecar.write_text("{")

    with pytest.raises(ValueError, match="Invalid constraints file"):
        load_project_constraints(schematic)


def test_load_project_constraints_rejects_invalid_shape(tmp_path: Path):
    schematic = tmp_path / "board.kicad_sch"
    schematic.write_text("(kicad_sch ...)")
    sidecar = tmp_path / "board.revlo-constraints.json"
    sidecar.write_text(json.dumps({"schema_version": 1, "constraints": ["bad"]}))

    with pytest.raises(ValueError, match="Invalid constraints file"):
        load_project_constraints(schematic)
