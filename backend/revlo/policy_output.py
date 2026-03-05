"""Build a versioned JSON policy output from a ReviewReport."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from revlo import __version__
from revlo.review_state import finding_fingerprint
from revlo.reviewer.models import ReviewReport

POLICY_SCHEMA_VERSION = 1


def build_policy_output(
    report: ReviewReport,
    schematic_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return a versioned policy-output dict suitable for JSON serialisation.

    Parameters
    ----------
    report:
        The completed review report.
    schematic_path:
        Optional path to the reviewed schematic (included in metadata).
    """
    findings_out: list[dict[str, Any]] = []
    for finding in report.findings:
        findings_out.append({
            "id": finding_fingerprint(finding),
            "severity": finding.severity.value,
            "category": finding.category.value,
            "component_ref": finding.component_ref,
            "title": finding.title,
            "description": finding.description,
            "recommendation": finding.recommendation,
            "confidence": finding.confidence,
            "source_type": finding.source_type.value,
            "baseline_status": finding.baseline_status.value,
            "change_status": finding.change_status.value,
            "evidence": finding.evidence.model_dump(),
        })

    stats = report.stats

    output: dict[str, Any] = {
        "schema_version": POLICY_SCHEMA_VERSION,
        "revlo_version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profile": report.review_profile,
        "datasheet_mode": report.datasheet_mode,
        "llm_provider": report.llm_provider,
        "llm_model": report.llm_model,
        "stats": {
            "error": stats.error,
            "warning": stats.warning,
            "suggestion": stats.suggestion,
            "total": stats.total,
        },
        "findings": findings_out,
    }

    if schematic_path is not None:
        output["schematic"] = str(Path(schematic_path).name)

    return output


def build_policy_json(
    report: ReviewReport,
    schematic_path: str | Path | None = None,
    *,
    indent: int = 2,
) -> str:
    """Return the versioned policy output as a JSON string."""
    return json.dumps(
        build_policy_output(report, schematic_path),
        indent=indent,
    )
