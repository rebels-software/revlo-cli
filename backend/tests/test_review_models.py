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
    """Test Severity StrEnum (US-007 AC2)."""

    def test_values(self):
        """Test that Severity has exactly error, warning, suggestion."""
        assert Severity.error == "error"
        assert Severity.warning == "warning"
        assert Severity.suggestion == "suggestion"

    def test_is_str(self):
        """Test that Severity members are strings (StrEnum)."""
        assert isinstance(Severity.error, str)
        assert isinstance(Severity.warning, str)
        assert isinstance(Severity.suggestion, str)

    def test_member_count(self):
        """Test that Severity has exactly 3 members."""
        assert len(Severity) == 3


class TestFindingCategoryEnum:
    """Test FindingCategory StrEnum (US-007 AC3)."""

    def test_required_values(self):
        """Test that FindingCategory has the required categories."""
        assert FindingCategory.decoupling == "decoupling"
        assert FindingCategory.pull_up == "pull_up"
        assert FindingCategory.power == "power"
        assert FindingCategory.signal_integrity == "signal_integrity"

    def test_is_str(self):
        """Test that FindingCategory members are strings (StrEnum)."""
        for member in FindingCategory:
            assert isinstance(member, str)

    def test_additional_categories_exist(self):
        """Test that additional ERC categories are defined beyond the required four."""
        assert len(FindingCategory) > 4


class TestFinding:
    """Test Finding model (US-007 AC4)."""

    def test_required_fields(self):
        """Test that Finding has all required fields."""
        finding = Finding(
            severity=Severity.error,
            category=FindingCategory.decoupling,
            component_ref="U1",
            title="Missing decoupling capacitor",
            description="U1 VCC pin has no decoupling capacitor nearby.",
            recommendation="Add a 100nF capacitor between VCC and GND.",
            confidence=0.9,
        )
        assert finding.severity == Severity.error
        assert finding.category == FindingCategory.decoupling
        assert finding.component_ref == "U1"
        assert finding.title == "Missing decoupling capacitor"
        assert finding.description == "U1 VCC pin has no decoupling capacitor nearby."
        assert finding.recommendation == "Add a 100nF capacitor between VCC and GND."
        assert finding.confidence == 0.9

    def test_confidence_bounds_valid(self):
        """Test that confidence accepts values in [0, 1]."""
        finding_low = Finding(
            severity=Severity.warning,
            category=FindingCategory.power,
            component_ref="U2",
            title="Test",
            description="Test",
            recommendation="Test",
            confidence=0.0,
        )
        assert finding_low.confidence == 0.0

        finding_high = Finding(
            severity=Severity.warning,
            category=FindingCategory.power,
            component_ref="U2",
            title="Test",
            description="Test",
            recommendation="Test",
            confidence=1.0,
        )
        assert finding_high.confidence == 1.0

    def test_confidence_below_zero_rejected(self):
        """Test that confidence < 0 raises ValidationError."""
        with pytest.raises(ValidationError):
            Finding(
                severity=Severity.error,
                category=FindingCategory.power,
                component_ref="U1",
                title="Test",
                description="Test",
                recommendation="Test",
                confidence=-0.1,
            )

    def test_confidence_above_one_rejected(self):
        """Test that confidence > 1 raises ValidationError."""
        with pytest.raises(ValidationError):
            Finding(
                severity=Severity.error,
                category=FindingCategory.power,
                component_ref="U1",
                title="Test",
                description="Test",
                recommendation="Test",
                confidence=1.1,
            )

    def test_model_dump(self):
        """Test .model_dump() returns dict for JSON serialization."""
        finding = Finding(
            severity=Severity.warning,
            category=FindingCategory.pull_up,
            component_ref="R1",
            title="Missing pull-up",
            description="I2C SDA line has no pull-up resistor.",
            recommendation="Add a 4.7k pull-up to VCC.",
            confidence=0.85,
        )
        data = finding.model_dump()
        assert isinstance(data, dict)
        assert data["severity"] == "warning"
        assert data["category"] == "pull_up"
        assert data["component_ref"] == "R1"
        assert data["title"] == "Missing pull-up"
        assert data["confidence"] == 0.85

    def test_severity_string_coercion(self):
        """Test that passing string values for severity works."""
        finding = Finding(
            severity="error",
            category="decoupling",
            component_ref="U1",
            title="Test",
            description="Test",
            recommendation="Test",
            confidence=0.5,
        )
        assert finding.severity == Severity.error
        assert finding.category == FindingCategory.decoupling


class TestSeverityStats:
    """Test SeverityStats model."""

    def test_default_values(self):
        """Test SeverityStats default values are zero."""
        stats = SeverityStats()
        assert stats.error == 0
        assert stats.warning == 0
        assert stats.suggestion == 0
        assert stats.total == 0

    def test_model_dump(self):
        """Test .model_dump() returns dict."""
        stats = SeverityStats(error=2, warning=3, suggestion=1, total=6)
        data = stats.model_dump()
        assert data == {"error": 2, "warning": 3, "suggestion": 1, "total": 6}


class TestReviewReport:
    """Test ReviewReport model (US-007 AC5)."""

    def _make_finding(self, severity: Severity, category: FindingCategory) -> Finding:
        """Helper to create a Finding with minimal fields."""
        return Finding(
            severity=severity,
            category=category,
            component_ref="U1",
            title="Test finding",
            description="Test description",
            recommendation="Test recommendation",
            confidence=0.8,
        )

    def test_default_fields(self):
        """Test ReviewReport with default empty fields."""
        report = ReviewReport()
        assert report.findings == []
        assert report.summary == ""
        assert report.schematic_title == ""
        assert report.review_date == ""

    def test_all_fields_populated(self):
        """Test ReviewReport with all fields populated."""
        finding = self._make_finding(Severity.error, FindingCategory.decoupling)
        report = ReviewReport(
            findings=[finding],
            summary="One issue found.",
            schematic_title="STM32 Dev Board",
            review_date="2026-02-11",
        )
        assert len(report.findings) == 1
        assert report.summary == "One issue found."
        assert report.schematic_title == "STM32 Dev Board"
        assert report.review_date == "2026-02-11"

    def test_stats_computed_empty(self):
        """Test that stats is computed correctly for empty findings."""
        report = ReviewReport()
        assert report.stats.error == 0
        assert report.stats.warning == 0
        assert report.stats.suggestion == 0
        assert report.stats.total == 0

    def test_stats_computed_mixed(self):
        """Test that stats counts findings by severity correctly."""
        findings = [
            self._make_finding(Severity.error, FindingCategory.decoupling),
            self._make_finding(Severity.error, FindingCategory.power),
            self._make_finding(Severity.warning, FindingCategory.pull_up),
            self._make_finding(Severity.warning, FindingCategory.signal_integrity),
            self._make_finding(Severity.warning, FindingCategory.grounding),
            self._make_finding(Severity.suggestion, FindingCategory.component_value),
        ]
        report = ReviewReport(findings=findings, summary="Mixed findings.")
        assert report.stats.error == 2
        assert report.stats.warning == 3
        assert report.stats.suggestion == 1
        assert report.stats.total == 6

    def test_stats_updates_with_findings(self):
        """Test that stats recomputes when findings change."""
        report = ReviewReport()
        assert report.stats.total == 0

        # Create a new report with findings (Pydantic models are immutable by default)
        finding = self._make_finding(Severity.error, FindingCategory.decoupling)
        report2 = ReviewReport(findings=[finding])
        assert report2.stats.error == 1
        assert report2.stats.total == 1

    def test_model_dump_includes_stats(self):
        """Test .model_dump() includes computed stats field."""
        finding = self._make_finding(Severity.error, FindingCategory.decoupling)
        report = ReviewReport(
            findings=[finding],
            summary="One error.",
            schematic_title="Test",
            review_date="2026-02-11",
        )
        data = report.model_dump()
        assert isinstance(data, dict)
        assert "stats" in data
        assert data["stats"]["error"] == 1
        assert data["stats"]["warning"] == 0
        assert data["stats"]["suggestion"] == 0
        assert data["stats"]["total"] == 1

    def test_model_dump_full_roundtrip(self):
        """Test that model_dump produces data that can reconstruct the model."""
        findings = [
            self._make_finding(Severity.error, FindingCategory.decoupling),
            self._make_finding(Severity.warning, FindingCategory.pull_up),
        ]
        report = ReviewReport(
            findings=findings,
            summary="Test summary.",
            schematic_title="Test Board",
            review_date="2026-02-11",
        )
        data = report.model_dump()

        # Remove computed field for reconstruction
        data.pop("stats")
        reconstructed = ReviewReport(**data)
        assert reconstructed.stats.error == 1
        assert reconstructed.stats.warning == 1
        assert reconstructed.stats.total == 2


class TestReExports:
    """Test that __init__.py re-exports all public models."""

    def test_import_from_package(self):
        """Test importing models from revlo.reviewer package."""
        from revlo.reviewer import (
            Finding,
            FindingCategory,
            ReviewReport,
            Severity,
            SeverityStats,
        )

        assert Finding is not None
        assert FindingCategory is not None
        assert ReviewReport is not None
        assert Severity is not None
        assert SeverityStats is not None


class TestPydanticV2Features:
    """Test Pydantic v2 BaseModel features (US-007 AC6)."""

    def test_all_models_have_model_dump(self):
        """Verify all models have .model_dump() method (Pydantic v2)."""
        models = [
            Finding(
                severity=Severity.error,
                category=FindingCategory.power,
                component_ref="U1",
                title="Test",
                description="Test",
                recommendation="Test",
                confidence=0.5,
            ),
            SeverityStats(),
            ReviewReport(),
        ]
        for model in models:
            assert hasattr(model, "model_dump")
            data = model.model_dump()
            assert isinstance(data, dict)

    def test_nested_model_dump(self):
        """Test that nested models serialize correctly."""
        finding = Finding(
            severity=Severity.error,
            category=FindingCategory.decoupling,
            component_ref="C1",
            title="Test",
            description="Test",
            recommendation="Test",
            confidence=0.7,
        )
        report = ReviewReport(findings=[finding])
        data = report.model_dump()
        assert data["findings"][0]["severity"] == "error"
        assert data["findings"][0]["category"] == "decoupling"
        assert data["findings"][0]["component_ref"] == "C1"
        assert data["findings"][0]["confidence"] == 0.7
