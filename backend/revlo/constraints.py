"""Structured project-constraint loading for Revlo reviews."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError


class ConstraintItem(BaseModel):
    """One structured project constraint."""

    kind: str
    name: str
    target: str = ""
    value: str = ""
    unit: str = ""
    notes: str = ""


class ProjectConstraints(BaseModel):
    """Project-local constraints loaded from a sidecar JSON file."""

    schema_version: int = 1
    schematic: str = ""
    constraints: list[ConstraintItem] = Field(default_factory=list)
    source_path: str = ""


def constraints_path_for_schematic(
    schematic_path: str | Path,
    override_path: str | Path | None = None,
) -> Path:
    """Resolve the active constraints file path for a schematic."""
    if override_path is not None:
        return Path(override_path).expanduser()

    schematic = Path(schematic_path)
    return schematic.with_name(f"{schematic.stem}.revlo-constraints.json")


def load_project_constraints(
    schematic_path: str | Path,
    override_path: str | Path | None = None,
) -> ProjectConstraints | None:
    """Load project-local constraints for a schematic, if present."""
    path = constraints_path_for_schematic(schematic_path, override_path)
    if not path.exists():
        return None

    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid constraints file at {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(f"Invalid constraints file at {path}: expected JSON object")

    try:
        constraints = ProjectConstraints.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"Invalid constraints file at {path}: {exc}") from exc

    if not constraints.schematic:
        constraints.schematic = Path(schematic_path).name
    constraints.source_path = str(path)
    return constraints
