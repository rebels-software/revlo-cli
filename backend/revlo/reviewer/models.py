"""Pydantic v2 models for review findings and reports."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, computed_field

from revlo.datasheet.models import DatasheetSpec


class Severity(StrEnum):
    error = "error"
    warning = "warning"
    suggestion = "suggestion"


class FindingCategory(StrEnum):
    decoupling = "decoupling"
    pull_up = "pull_up"
    power = "power"
    signal_integrity = "signal_integrity"
    grounding = "grounding"
    esd_protection = "esd_protection"
    clock = "clock"
    reset = "reset"
    unused_pin = "unused_pin"
    component_value = "component_value"
    connectivity = "connectivity"
    thermal = "thermal"


class Finding(BaseModel):
    severity: Severity
    category: FindingCategory
    component_ref: str
    title: str
    description: str
    recommendation: str
    confidence: float = Field(ge=0.0, le=1.0)
    suggested_fix: str = ""


class SeverityStats(BaseModel):
    error: int = 0
    warning: int = 0
    suggestion: int = 0
    total: int = 0


class ReviewReport(BaseModel):
    findings: list[Finding] = Field(default_factory=list)
    summary: str = ""
    schematic_title: str = ""
    review_date: str = ""
    datasheet_specs: dict[str, DatasheetSpec] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def stats(self) -> SeverityStats:
        counts = SeverityStats(
            error=sum(1 for f in self.findings if f.severity == Severity.error),
            warning=sum(1 for f in self.findings if f.severity == Severity.warning),
            suggestion=sum(
                1 for f in self.findings if f.severity == Severity.suggestion
            ),
            total=len(self.findings),
        )
        return counts
