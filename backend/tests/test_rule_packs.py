"""Tests for custom deterministic rule-pack loading."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from revlo.rule_packs import (
    CustomRulePack,
    default_rule_pack_paths_for_schematic,
    load_rule_pack,
    load_rule_packs,
)


def _write_pack(path: Path, **overrides) -> None:
    payload = {
        "schema_version": 1,
        "name": "Company Rules",
        "description": "Internal review rules",
        "additive": True,
        "rules": [
            {
                "id": "rule-001",
                "title": "MCU must have local decoupling",
                "severity": "warning",
                "category": "decoupling",
                "remediation": "Add a 100nF capacitor close to each MCU supply pin.",
                "conditions": [
                    {"field": "component_ref", "operator": "starts_with", "value": "U"}
                ],
            }
        ],
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload))


def test_default_rule_pack_paths_for_schematic(tmp_path: Path):
    schematic = tmp_path / "board.kicad_sch"
    assert default_rule_pack_paths_for_schematic(schematic) == [
        tmp_path / "board.revlo-rules.json",
        tmp_path / "revlo-rules.json",
    ]


def test_load_rule_pack_round_trip(tmp_path: Path):
    path = tmp_path / "revlo-rules.json"
    _write_pack(path)

    pack = load_rule_pack(path)

    assert isinstance(pack, CustomRulePack)
    assert pack.name == "Company Rules"
    assert pack.rules[0].id == "rule-001"
    assert pack.source_path == str(path)


def test_load_rule_packs_uses_default_sidecars(tmp_path: Path):
    schematic = tmp_path / "board.kicad_sch"
    schematic.write_text("(kicad_sch ...)")
    project_pack = tmp_path / "revlo-rules.json"
    per_schematic_pack = tmp_path / "board.revlo-rules.json"
    _write_pack(project_pack, name="Project Rules")
    _write_pack(per_schematic_pack, name="Board Rules")

    packs = load_rule_packs(schematic)

    assert [pack.name for pack in packs] == ["Board Rules", "Project Rules"]


def test_load_rule_packs_uses_override_paths(tmp_path: Path):
    schematic = tmp_path / "board.kicad_sch"
    schematic.write_text("(kicad_sch ...)")
    custom = tmp_path / "custom-rules.json"
    _write_pack(custom, name="Override Rules")

    packs = load_rule_packs(schematic, [custom])

    assert len(packs) == 1
    assert packs[0].name == "Override Rules"


def test_load_rule_pack_rejects_invalid_json(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text("{")

    with pytest.raises(ValueError, match="Invalid rule pack"):
        load_rule_pack(path)


def test_load_rule_pack_rejects_invalid_shape(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"schema_version": 1, "name": "Bad", "rules": ["x"]}))

    with pytest.raises(ValueError, match="Invalid rule pack"):
        load_rule_pack(path)
