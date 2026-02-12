"""Persistent review storage in .revlo/ directory alongside schematics."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from revlo.reviewer.models import ReviewReport


def save_review(report: ReviewReport, schematic_path: str) -> Path:
    """Save review report as JSON in .revlo/ next to the schematic.

    Filename format: {stem}-review-{timestamp}.json
    Returns the path to the saved file.
    """
    sch = Path(schematic_path)
    revlo_dir = sch.parent / ".revlo"
    revlo_dir.mkdir(exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    filename = f"{sch.stem}-review-{timestamp}.json"
    out_path = revlo_dir / filename

    # Add metadata
    data = report.model_dump()
    data["_meta"] = {
        "schematic": sch.name,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "revlo_version": "0.1.0",
    }

    out_path.write_text(json.dumps(data, indent=2))
    return out_path


def load_latest_review(schematic_path: str) -> tuple[ReviewReport, dict] | None:
    """Load the most recent review for a schematic.

    Returns (report, metadata) or None if no reviews exist.
    """
    sch = Path(schematic_path)
    revlo_dir = sch.parent / ".revlo"

    if not revlo_dir.is_dir():
        return None

    # Find review files for this schematic
    pattern = f"{sch.stem}-review-*.json"
    files = sorted(revlo_dir.glob(pattern), reverse=True)  # newest first

    if not files:
        return None

    latest = files[0]
    data = json.loads(latest.read_text())

    meta = data.pop("_meta", {})
    report = ReviewReport.model_validate(data)
    return report, meta
