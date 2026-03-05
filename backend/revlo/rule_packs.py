"""Project-local custom deterministic rule-pack loading."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError


class RulePackMatchCondition(BaseModel):
    """Declarative condition for a custom rule."""

    field: str
    operator: str
    value: str


class CustomRuleDefinition(BaseModel):
    """One custom deterministic rule definition."""

    id: str
    title: str
    severity: str
    category: str
    remediation: str
    conditions: list[RulePackMatchCondition] = Field(default_factory=list)
    notes: str = ""


class CustomRulePack(BaseModel):
    """A validated project-local custom rule pack."""

    schema_version: int = 1
    name: str
    description: str = ""
    additive: bool = True
    rules: list[CustomRuleDefinition] = Field(default_factory=list)
    source_path: str = ""


def default_rule_pack_paths_for_schematic(schematic_path: str | Path) -> list[Path]:
    """Return the default custom rule-pack sidecar paths for a schematic."""
    schematic = Path(schematic_path)
    return [
        schematic.with_name(f"{schematic.stem}.revlo-rules.json"),
        schematic.parent / "revlo-rules.json",
    ]


def _coerce_rule_pack_paths(
    schematic_path: str | Path,
    override_paths: list[str | Path] | None = None,
) -> list[Path]:
    if override_paths:
        return [Path(path).expanduser() for path in override_paths]
    return default_rule_pack_paths_for_schematic(schematic_path)


def load_rule_pack(path: str | Path) -> CustomRulePack:
    """Load one custom rule pack from disk with actionable validation errors."""
    resolved = Path(path).expanduser()
    try:
        raw = json.loads(resolved.read_text())
    except FileNotFoundError as exc:
        raise ValueError(f"Rule pack file not found: {resolved}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid rule pack at {resolved}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(f"Invalid rule pack at {resolved}: expected JSON object")

    try:
        pack = CustomRulePack.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"Invalid rule pack at {resolved}: {exc}") from exc

    pack.source_path = str(resolved)
    return pack


def load_rule_packs(
    schematic_path: str | Path,
    override_paths: list[str | Path] | None = None,
) -> list[CustomRulePack]:
    """Load zero or more custom rule packs for a schematic."""
    packs: list[CustomRulePack] = []
    for path in _coerce_rule_pack_paths(schematic_path, override_paths):
        if not path.exists():
            continue
        packs.append(load_rule_pack(path))
    return packs
