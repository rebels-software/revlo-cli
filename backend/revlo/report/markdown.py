"""Markdown report generator for ReviewReport."""

from __future__ import annotations

from revlo.reviewer.models import Finding, ReviewReport, Severity

# Severity display order and labels
_SEVERITY_ORDER = [Severity.error, Severity.warning, Severity.suggestion]
_SEVERITY_EMOJI = {
    Severity.error: "Error",
    Severity.warning: "Warning",
    Severity.suggestion: "Suggestion",
}


def _severity_heading(severity: Severity) -> str:
    """Return a markdown heading for a severity group."""
    return f"## {_SEVERITY_EMOJI[severity]}s"


def _format_finding(finding: Finding) -> str:
    """Format a single finding as a markdown block."""
    lines = [
        f"### {finding.title}",
        "",
        f"**Component:** `{finding.component_ref}`  ",
        f"**Category:** {finding.category.value}  ",
        f"**Confidence:** {finding.confidence:.0%}",
        "",
        finding.description,
        "",
        f"> **Recommendation:** {finding.recommendation}",
    ]
    return "\n".join(lines)


def generate_markdown_report(report: ReviewReport) -> str:
    """Convert a ReviewReport into a readable markdown string.

    Parameters
    ----------
    report:
        The review report to render.

    Returns
    -------
    str
        A complete markdown document.
    """
    sections: list[str] = []

    # Title
    title = report.schematic_title or "Schematic Review"
    sections.append(f"# {title}")
    if report.review_date:
        sections.append(f"**Review date:** {report.review_date}")

    # Summary
    if report.summary:
        sections.append(f"\n{report.summary}")

    # Severity summary table
    stats = report.stats
    sections.append("")
    sections.append("## Summary")
    sections.append("")
    sections.append("| Severity | Count |")
    sections.append("|----------|-------|")
    sections.append(f"| Error | {stats.error} |")
    sections.append(f"| Warning | {stats.warning} |")
    sections.append(f"| Suggestion | {stats.suggestion} |")
    sections.append(f"| **Total** | **{stats.total}** |")

    # Group findings by severity
    grouped: dict[Severity, list[Finding]] = {s: [] for s in _SEVERITY_ORDER}
    for finding in report.findings:
        grouped[finding.severity].append(finding)

    # Render each non-empty group
    for severity in _SEVERITY_ORDER:
        findings = grouped[severity]
        if not findings:
            continue
        sections.append("")
        sections.append(_severity_heading(severity))
        for finding in findings:
            sections.append("")
            sections.append(_format_finding(finding))

    # Handle empty reports
    if not report.findings:
        sections.append("")
        sections.append("No findings reported.")

    # Trailing newline
    return "\n".join(sections) + "\n"
