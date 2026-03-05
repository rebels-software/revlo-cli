"""Project-local baseline and waiver persistence helpers."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from revlo import __version__
from revlo.reviewer.models import (
    Finding,
    FindingBaselineStatus,
    FindingEvidence,
    FindingSourceType,
    FindingCategory,
    ReviewReport,
    Severity,
)

SCHEMA_VERSION = 1


class BaselineFinding(BaseModel):
    """Persisted snapshot of one finding in a saved baseline."""

    fingerprint: str
    severity: Severity
    category: FindingCategory
    component_ref: str
    title: str
    source_type: FindingSourceType
    evidence: FindingEvidence = Field(default_factory=FindingEvidence)


class ReviewBaseline(BaseModel):
    """Persisted baseline file for one schematic."""

    schema_version: int = SCHEMA_VERSION
    schematic: str
    created_at: str
    revlo_version: str
    source_review: str = ""
    llm_provider: str = ""
    llm_model: str = ""
    datasheet_mode: str = ""
    review_profile: str = ""
    findings: list[BaselineFinding] = Field(default_factory=list)


class WaiverEntry(BaseModel):
    """One waived finding entry."""

    fingerprint: str
    reason: str
    created_at: str
    created_by: str = ""
    expires_at: str | None = None


class FindingWaivers(BaseModel):
    """Persisted waiver file for one schematic."""

    schema_version: int = SCHEMA_VERSION
    schematic: str
    updated_at: str
    entries: list[WaiverEntry] = Field(default_factory=list)


def baseline_path_for_schematic(schematic_path: str | Path) -> Path:
    """Return the baseline sidecar path for a schematic."""
    sch = Path(schematic_path)
    return sch.with_name(f"{sch.stem}.revlo-baseline.json")


def waivers_path_for_schematic(schematic_path: str | Path) -> Path:
    """Return the waiver sidecar path for a schematic."""
    sch = Path(schematic_path)
    return sch.with_name(f"{sch.stem}.revlo-waivers.json")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value: str) -> str:
    collapsed = re.sub(r"\s+", " ", value.strip().lower())
    return collapsed


def finding_fingerprint(finding: Finding) -> str:
    """Compute a stable fingerprint from structured finding fields."""
    payload = {
        "category": finding.category.value,
        "component_ref": finding.component_ref.strip().upper(),
        "title": _normalize_text(finding.title),
        "source_type": finding.source_type.value,
        "refs": sorted({ref.strip().upper() for ref in finding.evidence.refs if ref.strip()}),
        "nets": sorted({net.strip() for net in finding.evidence.nets if net.strip()}),
        "sheet_paths": sorted(
            {path.strip() for path in finding.evidence.sheet_paths if path.strip()}
        ),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def snapshot_finding(finding: Finding) -> BaselineFinding:
    """Convert a live finding into a persisted baseline snapshot."""
    return BaselineFinding(
        fingerprint=finding_fingerprint(finding),
        severity=finding.severity,
        category=finding.category,
        component_ref=finding.component_ref,
        title=finding.title,
        source_type=finding.source_type,
        evidence=FindingEvidence.model_validate(finding.evidence.model_dump()),
    )


def save_baseline(
    report: ReviewReport,
    schematic_path: str | Path,
    *,
    source_review: str | Path | None = None,
) -> Path:
    """Persist a baseline sidecar file next to the schematic."""
    sch = Path(schematic_path)
    baseline = ReviewBaseline(
        schematic=sch.name,
        created_at=_utc_now_iso(),
        revlo_version=__version__,
        source_review=str(source_review) if source_review is not None else "",
        llm_provider=report.llm_provider,
        llm_model=report.llm_model,
        datasheet_mode=report.datasheet_mode,
        review_profile=report.review_profile,
        findings=[snapshot_finding(finding) for finding in report.findings],
    )
    path = baseline_path_for_schematic(sch)
    path.write_text(json.dumps(baseline.model_dump(), indent=2))
    return path


def load_baseline(schematic_path: str | Path) -> ReviewBaseline | None:
    """Load a saved baseline sidecar file if it exists."""
    path = baseline_path_for_schematic(schematic_path)
    if not path.exists():
        return None
    return ReviewBaseline.model_validate(json.loads(path.read_text()))


def save_waivers(
    schematic_path: str | Path,
    entries: list[WaiverEntry],
) -> Path:
    """Persist a waiver sidecar file next to the schematic."""
    sch = Path(schematic_path)
    waivers = FindingWaivers(
        schematic=sch.name,
        updated_at=_utc_now_iso(),
        entries=entries,
    )
    path = waivers_path_for_schematic(sch)
    path.write_text(json.dumps(waivers.model_dump(), indent=2))
    return path


def load_waivers(schematic_path: str | Path) -> FindingWaivers | None:
    """Load a saved waiver sidecar file if it exists."""
    path = waivers_path_for_schematic(schematic_path)
    if not path.exists():
        return None
    return FindingWaivers.model_validate(json.loads(path.read_text()))


def _waiver_is_active(entry: WaiverEntry) -> bool:
    """Return whether a waiver entry is still active."""
    if not entry.expires_at:
        return True
    try:
        expires_at = datetime.fromisoformat(entry.expires_at)
    except ValueError:
        return True
    return expires_at >= datetime.now(timezone.utc)


def classify_findings(
    report: ReviewReport,
    schematic_path: str | Path,
    *,
    baseline: ReviewBaseline | None = None,
    waivers: FindingWaivers | None = None,
) -> ReviewReport:
    """Classify findings as new, existing, or waived."""
    baseline = baseline if baseline is not None else load_baseline(schematic_path)
    waivers = waivers if waivers is not None else load_waivers(schematic_path)

    baseline_fingerprints = {
        finding.fingerprint for finding in baseline.findings
    } if baseline is not None else set()
    waived_fingerprints = {
        entry.fingerprint
        for entry in waivers.entries
        if _waiver_is_active(entry)
    } if waivers is not None else set()

    for finding in report.findings:
        fingerprint = finding_fingerprint(finding)
        if fingerprint in waived_fingerprints:
            finding.baseline_status = FindingBaselineStatus.waived
        elif fingerprint in baseline_fingerprints:
            finding.baseline_status = FindingBaselineStatus.existing
        else:
            finding.baseline_status = FindingBaselineStatus.new
    return report
