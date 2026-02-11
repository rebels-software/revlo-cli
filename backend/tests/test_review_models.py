"""Test suite for Pydantic models in revlo.reviewer.models."""

import pytest
from pydantic import ValidationError

from revlo.reviewer.models import (
    Finding,
    FindingCategory,
    ReviewReport,
    Severity,
    SeverityStats,
)


class TestSeverityEnum:
    def test_values_and_type(self):
        assert Severity.error == "error"
        assert Severity.warning == "warning"
        assert Severity.suggestion == "suggestion"
        assert len(Severity) == 3
        assert all(isinstance(s, str) for s in Severity)


class TestFindingCategoryEnum:
    def test_required_categories_and_extensibility(self):
        for name in ("decoupling", "pull_up", "power", "signal_integrity"):
            assert name in [m.value for m in FindingCategory]
        assert len(FindingCategory) > 4
        assert all(isinstance(c, str) for c in FindingCategory)


class TestFinding:
    def _make(self, **overrides):
        defaults = dict(
            severity=Severity.error, category=FindingCategory.decoupling,
            component_ref="U1", title="Test", description="Desc",
            recommendation="Fix it", confidence=0.8,
        )
        defaults.update(overrides)
        return Finding(**defaults)

    def test_required_fields(self):
        f = self._make()
        assert f.severity == Severity.error
        assert f.category == FindingCategory.decoupling
        assert f.component_ref == "U1"
        assert f.confidence == 0.8

    def test_confidence_bounds(self):
        assert self._make(confidence=0.0).confidence == 0.0
        assert self._make(confidence=1.0).confidence == 1.0

    def test_confidence_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            self._make(confidence=-0.1)
        with pytest.raises(ValidationError):
            self._make(confidence=1.1)

    def test_string_coercion_for_enums(self):
        f = self._make(severity="warning", category="power")
        assert f.severity == Severity.warning
        assert f.category == FindingCategory.power

    def test_model_dump(self):
        data = self._make(severity=Severity.warning, category=FindingCategory.pull_up).model_dump()
        assert data["severity"] == "warning"
        assert data["category"] == "pull_up"


class TestSeverityStats:
    def test_defaults(self):
        s = SeverityStats()
        assert s.error == 0 and s.warning == 0 and s.suggestion == 0 and s.total == 0

    def test_model_dump(self):
        data = SeverityStats(error=2, warning=3, suggestion=1, total=6).model_dump()
        assert data == {"error": 2, "warning": 3, "suggestion": 1, "total": 6}


class TestReviewReport:
    def _make_finding(self, severity=Severity.error, category=FindingCategory.decoupling):
        return Finding(
            severity=severity, category=category, component_ref="U1",
            title="Test", description="Desc", recommendation="Fix", confidence=0.8,
        )

    def test_defaults(self):
        r = ReviewReport()
        assert r.findings == []
        assert r.summary == ""
        assert r.stats.total == 0

    def test_stats_computed(self):
        findings = [
            self._make_finding(Severity.error, FindingCategory.decoupling),
            self._make_finding(Severity.error, FindingCategory.power),
            self._make_finding(Severity.warning, FindingCategory.pull_up),
            self._make_finding(Severity.suggestion, FindingCategory.component_value),
        ]
        r = ReviewReport(findings=findings)
        assert r.stats.error == 2
        assert r.stats.warning == 1
        assert r.stats.suggestion == 1
        assert r.stats.total == 4

    def test_model_dump_includes_stats(self):
        r = ReviewReport(findings=[self._make_finding()])
        data = r.model_dump()
        assert "stats" in data
        assert data["stats"]["total"] == 1

    def test_roundtrip(self):
        r = ReviewReport(findings=[
            self._make_finding(Severity.error),
            self._make_finding(Severity.warning, FindingCategory.pull_up),
        ], summary="Test")
        data = r.model_dump()
        data.pop("stats")
        r2 = ReviewReport(**data)
        assert r2.stats.total == 2


class TestReExports:
    def test_import_from_package(self):
        from revlo.reviewer import Finding, FindingCategory, ReviewReport, Severity, SeverityStats
        for cls in (Finding, FindingCategory, ReviewReport, Severity, SeverityStats):
            assert cls is not None
