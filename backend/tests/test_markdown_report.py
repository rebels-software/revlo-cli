"""Test suite for markdown report generation."""

from revlo.report import generate_markdown_report
from revlo.reviewer.models import (
    Finding,
    FindingCategory,
    ReviewReport,
    Severity,
)


class TestGenerateMarkdownReport:
    """Test generate_markdown_report() function."""

    def _make_finding(self, **overrides):
        """Factory for creating test findings."""
        defaults = dict(
            severity=Severity.error,
            category=FindingCategory.decoupling,
            component_ref="U1",
            title="Test Finding",
            description="Test description",
            recommendation="Test recommendation",
            confidence=0.8,
        )
        defaults.update(overrides)
        return Finding(**defaults)

    def test_empty_report_produces_valid_markdown(self):
        """Empty report should produce valid markdown with no findings message."""
        report = ReviewReport()
        markdown = generate_markdown_report(report)

        assert isinstance(markdown, str)
        assert markdown.endswith("\n")
        assert "# Schematic Review" in markdown
        assert "No findings reported." in markdown
        assert "| **Total** | **0** |" in markdown

    def test_empty_report_with_custom_title(self):
        """Empty report with custom title should use that title."""
        report = ReviewReport(schematic_title="STM32F103 Design")
        markdown = generate_markdown_report(report)

        assert "# STM32F103 Design" in markdown
        assert "# Schematic Review" not in markdown

    def test_findings_grouped_by_severity_in_correct_order(self):
        """Findings should be grouped errors first, then warnings, then suggestions."""
        findings = [
            self._make_finding(severity=Severity.suggestion, title="Suggestion 1"),
            self._make_finding(severity=Severity.error, title="Error 1"),
            self._make_finding(severity=Severity.warning, title="Warning 1"),
            self._make_finding(severity=Severity.error, title="Error 2"),
        ]
        report = ReviewReport(findings=findings)
        markdown = generate_markdown_report(report)

        # Check that sections appear in correct order
        error_idx = markdown.index("## Errors")
        warning_idx = markdown.index("## Warnings")
        suggestion_idx = markdown.index("## Suggestions")

        assert error_idx < warning_idx < suggestion_idx

        # Check that findings appear under correct sections
        error_1_idx = markdown.index("### Error 1")
        error_2_idx = markdown.index("### Error 2")
        warning_1_idx = markdown.index("### Warning 1")
        suggestion_1_idx = markdown.index("### Suggestion 1")

        assert error_1_idx > error_idx
        assert error_2_idx > error_idx
        assert warning_1_idx > warning_idx
        assert suggestion_1_idx > suggestion_idx
        assert error_2_idx < warning_idx

    def test_severity_summary_shows_correct_counts(self):
        """Severity summary table should show correct counts for each severity."""
        findings = [
            self._make_finding(severity=Severity.error),
            self._make_finding(severity=Severity.error),
            self._make_finding(severity=Severity.warning),
            self._make_finding(severity=Severity.suggestion),
            self._make_finding(severity=Severity.suggestion),
            self._make_finding(severity=Severity.suggestion),
        ]
        report = ReviewReport(findings=findings)
        markdown = generate_markdown_report(report)

        assert "| Error | 2 |" in markdown
        assert "| Warning | 1 |" in markdown
        assert "| Suggestion | 3 |" in markdown
        assert "| **Total** | **6** |" in markdown

    def test_finding_displays_all_required_fields(self):
        """Each finding should display title, component_ref, category, confidence, description, recommendation."""
        finding = self._make_finding(
            title="Missing decoupling capacitor",
            component_ref="U5",
            category=FindingCategory.decoupling,
            description="This IC requires a decoupling capacitor near VDD pin.",
            recommendation="Add a 100nF capacitor between VDD and GND, close to the IC.",
            confidence=0.95,
        )
        report = ReviewReport(findings=[finding])
        markdown = generate_markdown_report(report)

        assert "### Missing decoupling capacitor" in markdown
        assert "**Component:** `U5`" in markdown
        assert "**Category:** decoupling" in markdown
        assert "**Confidence:** 95%" in markdown
        assert "This IC requires a decoupling capacitor near VDD pin." in markdown
        assert "> **Recommendation:** Add a 100nF capacitor between VDD and GND, close to the IC." in markdown

    def test_schematic_title_and_review_date_appear_in_output(self):
        """Schematic title and review date should appear at the top of the report."""
        report = ReviewReport(
            schematic_title="Power Supply Board Rev 2",
            review_date="2024-01-15",
        )
        markdown = generate_markdown_report(report)

        assert "# Power Supply Board Rev 2" in markdown
        assert "**Review date:** 2024-01-15" in markdown

    def test_metadata_fields_do_not_change_markdown_output(self):
        """Persistence metadata should not leak into the human report."""
        report = ReviewReport(
            schematic_title="Metadata Test",
            review_date="2024-01-15",
            summary="Summary text",
            llm_provider="openai",
            llm_model="gpt-5.4",
            datasheet_mode="fast",
        )

        markdown = generate_markdown_report(report)

        assert "# Metadata Test" in markdown
        assert "Summary text" in markdown
        assert "openai" not in markdown
        assert "gpt-5.4" not in markdown
        assert "datasheet_mode" not in markdown

    def test_missing_schematic_title_defaults_to_schematic_review(self):
        """Missing schematic_title should default to 'Schematic Review'."""
        report = ReviewReport(schematic_title="")
        markdown = generate_markdown_report(report)

        assert "# Schematic Review" in markdown

    def test_missing_review_date_no_date_line(self):
        """Missing review_date should not render a date line."""
        report = ReviewReport(review_date="")
        markdown = generate_markdown_report(report)

        assert "**Review date:**" not in markdown

    def test_missing_summary_no_summary_paragraph(self):
        """Missing summary should not render a summary paragraph."""
        report = ReviewReport(summary="")
        markdown = generate_markdown_report(report)
        lines = markdown.split("\n")

        # Should go straight from title to Summary section
        summary_idx = next(i for i, line in enumerate(lines) if line == "## Summary")
        title_idx = next(i for i, line in enumerate(lines) if line.startswith("# "))

        # Only blank lines between title and summary section
        between = lines[title_idx + 1 : summary_idx]
        assert all(line == "" for line in between)

    def test_report_with_summary_includes_paragraph(self):
        """Report with summary should include the summary paragraph."""
        report = ReviewReport(
            summary="This design review identified 5 critical issues that need attention."
        )
        markdown = generate_markdown_report(report)

        assert "This design review identified 5 critical issues that need attention." in markdown

    def test_report_with_only_one_severity_level(self):
        """Report with only one severity level should only show that section."""
        findings = [
            self._make_finding(severity=Severity.error, title="Error 1"),
            self._make_finding(severity=Severity.error, title="Error 2"),
        ]
        report = ReviewReport(findings=findings)
        markdown = generate_markdown_report(report)

        assert "## Errors" in markdown
        assert "## Warnings" not in markdown
        assert "## Suggestions" not in markdown
        assert "### Error 1" in markdown
        assert "### Error 2" in markdown

    def test_many_findings_of_same_severity(self):
        """Many findings of the same severity should all appear under one heading."""
        findings = [
            self._make_finding(severity=Severity.warning, title=f"Warning {i}")
            for i in range(10)
        ]
        report = ReviewReport(findings=findings)
        markdown = generate_markdown_report(report)

        # Should only have one "## Warnings" heading
        assert markdown.count("## Warnings") == 1

        # All findings should be present
        for i in range(10):
            assert f"### Warning {i}" in markdown

    def test_confidence_edge_cases(self):
        """Confidence values 0.0 and 1.0 should render as 0% and 100%."""
        findings = [
            self._make_finding(confidence=0.0, title="Zero Confidence"),
            self._make_finding(confidence=1.0, title="Full Confidence"),
        ]
        report = ReviewReport(findings=findings)
        markdown = generate_markdown_report(report)

        # Find the confidence lines for each finding
        zero_idx = markdown.index("### Zero Confidence")
        full_idx = markdown.index("### Full Confidence")

        zero_section = markdown[zero_idx : zero_idx + 200]
        full_section = markdown[full_idx : full_idx + 200]

        assert "**Confidence:** 0%" in zero_section
        assert "**Confidence:** 100%" in full_section

    def test_special_markdown_characters_passed_through(self):
        """Special markdown characters in title/description should be passed through as-is."""
        finding = self._make_finding(
            title="Capacitor value *should* be `100nF`",
            description="The **recommended** value is 100nF, not 10nF. See [datasheet](http://example.com).",
        )
        report = ReviewReport(findings=[finding])
        markdown = generate_markdown_report(report)

        assert "### Capacitor value *should* be `100nF`" in markdown
        assert "The **recommended** value is 100nF, not 10nF. See [datasheet](http://example.com)." in markdown

    def test_return_type_is_string_ending_with_newline(self):
        """Return type should be str and end with newline."""
        report = ReviewReport()
        markdown = generate_markdown_report(report)

        assert isinstance(markdown, str)
        assert markdown.endswith("\n")
        assert len(markdown) > 0

    def test_generate_markdown_report_exported_from_revlo_report(self):
        """generate_markdown_report should be importable from revlo.report."""
        from revlo.report import generate_markdown_report as imported_func

        assert imported_func is generate_markdown_report

    def test_all_severity_levels_present_in_report(self):
        """Report with all severity levels should show all three sections."""
        findings = [
            self._make_finding(severity=Severity.error, title="Error Finding"),
            self._make_finding(severity=Severity.warning, title="Warning Finding"),
            self._make_finding(severity=Severity.suggestion, title="Suggestion Finding"),
        ]
        report = ReviewReport(
            findings=findings,
            schematic_title="Complete Review",
            review_date="2024-01-20",
            summary="This is a complete review with all severity levels.",
        )
        markdown = generate_markdown_report(report)

        # Check structure
        assert "# Complete Review" in markdown
        assert "**Review date:** 2024-01-20" in markdown
        assert "This is a complete review with all severity levels." in markdown
        assert "## Summary" in markdown
        assert "| Error | 1 |" in markdown
        assert "| Warning | 1 |" in markdown
        assert "| Suggestion | 1 |" in markdown
        assert "| **Total** | **3** |" in markdown
        assert "## Errors" in markdown
        assert "## Warnings" in markdown
        assert "## Suggestions" in markdown
        assert "### Error Finding" in markdown
        assert "### Warning Finding" in markdown
        assert "### Suggestion Finding" in markdown
        assert "No findings reported." not in markdown

    def test_category_value_displayed_correctly(self):
        """Different category values should be displayed correctly."""
        categories = [
            FindingCategory.decoupling,
            FindingCategory.power,
            FindingCategory.signal_integrity,
            FindingCategory.esd_protection,
        ]
        findings = [
            self._make_finding(category=cat, title=f"Finding {cat.value}")
            for cat in categories
        ]
        report = ReviewReport(findings=findings)
        markdown = generate_markdown_report(report)

        for cat in categories:
            assert f"**Category:** {cat.value}" in markdown

    def test_multiple_findings_same_component(self):
        """Multiple findings for the same component should all appear."""
        findings = [
            self._make_finding(
                component_ref="U1",
                title="Missing decoupling cap",
                severity=Severity.error,
            ),
            self._make_finding(
                component_ref="U1",
                title="Missing pull-up resistor",
                severity=Severity.warning,
            ),
        ]
        report = ReviewReport(findings=findings)
        markdown = generate_markdown_report(report)

        assert markdown.count("**Component:** `U1`") == 2
        assert "### Missing decoupling cap" in markdown
        assert "### Missing pull-up resistor" in markdown

    def test_empty_string_summary(self):
        """Empty string summary should not render a paragraph."""
        report = ReviewReport(summary="")
        markdown = generate_markdown_report(report)

        # The summary section (table) should still exist
        assert "## Summary" in markdown

        # But there should be no paragraph before it
        lines = markdown.split("\n")
        summary_idx = next(i for i, line in enumerate(lines) if line == "## Summary")

        # Line before "## Summary" should be blank (not a paragraph)
        assert lines[summary_idx - 1] == ""
