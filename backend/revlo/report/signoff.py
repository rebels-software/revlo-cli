"""Sign-off review packet generator.

Produces a structured markdown report suitable for stakeholder sign-off,
distinguishing unresolved issues from accepted risk (waivers).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from revlo import __version__
from revlo.review_state import (
    FindingWaivers,
    finding_fingerprint,
    load_waivers,
)
from revlo.reviewer.models import (
    Finding,
    FindingBaselineStatus,
    FindingSourceType,
    ReviewReport,
    Severity,
)

_SEVERITY_ORDER = [Severity.error, Severity.warning, Severity.suggestion]
_SEVERITY_LABEL = {
    Severity.error: "Error",
    Severity.warning: "Warning",
    Severity.suggestion: "Suggestion",
}


def _waiver_reason_map(waivers: FindingWaivers | None) -> dict[str, str]:
    """Build fingerprint -> reason lookup from waiver entries."""
    if waivers is None:
        return {}
    return {entry.fingerprint: entry.reason for entry in waivers.entries}


def _format_evidence_block(finding: Finding) -> list[str]:
    """Return markdown lines describing evidence for a finding."""
    lines: list[str] = []
    ev = finding.evidence
    if ev.refs:
        lines.append(f"  - Refs: {', '.join(ev.refs)}")
    if ev.nets:
        lines.append(f"  - Nets: {', '.join(ev.nets)}")
    if ev.sheet_paths:
        lines.append(f"  - Sheets: {', '.join(ev.sheet_paths)}")
    if ev.datasheets:
        for ds in ev.datasheets:
            label = ds.mpn or ds.manufacturer or "datasheet"
            if ds.relevant_pages:
                page_list = ", ".join(str(p) for p in ds.relevant_pages)
                lines.append(f"  - Datasheet: {label} (pages {page_list})")
            else:
                lines.append(f"  - Datasheet: {label}")
    return lines


def _format_finding_row(finding: Finding, *, index: int) -> list[str]:
    """Format a single finding as a numbered block."""
    lines = [
        f"### {index}. {finding.title}",
        "",
        f"- **Severity:** {_SEVERITY_LABEL.get(finding.severity, finding.severity.value)}",
        f"- **Component:** `{finding.component_ref}`",
        f"- **Category:** {finding.category.value}",
        f"- **Source:** {finding.source_type.value}",
        f"- **Confidence:** {finding.confidence:.0%}",
        "",
        finding.description,
        "",
        f"> **Recommendation:** {finding.recommendation}",
    ]
    evidence_lines = _format_evidence_block(finding)
    if evidence_lines:
        lines.append("")
        lines.append("**Evidence:**")
        lines.extend(evidence_lines)
    return lines


def generate_signoff_report(
    report: ReviewReport,
    schematic_path: str | Path,
    waivers: FindingWaivers | None = None,
) -> str:
    """Generate a sign-off review packet as markdown.

    Parameters
    ----------
    report:
        The completed review report.
    schematic_path:
        Path to the reviewed schematic file.
    waivers:
        Optional waiver data. If *None*, waivers are loaded from the
        sidecar file next to the schematic.

    Returns
    -------
    str
        A complete markdown sign-off packet.
    """
    sch_path = Path(schematic_path)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Load waivers if not provided
    if waivers is None:
        waivers = load_waivers(schematic_path)

    waiver_reasons = _waiver_reason_map(waivers)

    sections: list[str] = []

    # ── Header ──────────────────────────────────────────────────────
    sections.append("# Design Review Sign-Off Packet")
    sections.append("")
    sections.append(f"**Schematic:** {sch_path.name}  ")
    sections.append(f"**Review date:** {now_iso}")
    sections.append("")
    sections.append("---")

    # ── Review Context ──────────────────────────────────────────────
    sections.append("")
    sections.append("## Review Context")
    sections.append("")
    sections.append("| Parameter | Value |")
    sections.append("|-----------|-------|")
    sections.append(f"| Profile | {report.review_profile or 'default'} |")
    sections.append(f"| LLM Provider | {report.llm_provider or 'N/A'} |")
    sections.append(f"| LLM Model | {report.llm_model or 'N/A'} |")
    sections.append(f"| Datasheet Mode | {report.datasheet_mode or 'N/A'} |")
    sections.append(f"| Revlo Version | {__version__} |")

    # ── Findings Summary Table ──────────────────────────────────────
    sections.append("")
    sections.append("## Findings Summary")
    sections.append("")

    stats = report.stats
    det_count = sum(
        1 for f in report.findings if f.source_type == FindingSourceType.deterministic
    )
    llm_count = sum(
        1 for f in report.findings if f.source_type == FindingSourceType.llm
    )
    custom_count = sum(
        1 for f in report.findings if f.source_type == FindingSourceType.custom_rule
    )
    waived_count = sum(
        1 for f in report.findings if f.baseline_status == FindingBaselineStatus.waived
    )
    unresolved_count = stats.total - waived_count

    sections.append("| Metric | Count |")
    sections.append("|--------|-------|")
    sections.append(f"| Errors | {stats.error} |")
    sections.append(f"| Warnings | {stats.warning} |")
    sections.append(f"| Suggestions | {stats.suggestion} |")
    sections.append(f"| **Total** | **{stats.total}** |")
    sections.append(f"| Deterministic | {det_count} |")
    sections.append(f"| LLM | {llm_count} |")
    if custom_count:
        sections.append(f"| Custom Rule | {custom_count} |")
    sections.append(f"| Waived | {waived_count} |")
    sections.append(f"| **Unresolved** | **{unresolved_count}** |")

    # ── Unresolved Issues ───────────────────────────────────────────
    unresolved = [
        f for f in report.findings if f.baseline_status != FindingBaselineStatus.waived
    ]

    sections.append("")
    sections.append("## Unresolved Issues")
    sections.append("")

    if not unresolved:
        sections.append("No unresolved issues.")
    else:
        # Group by severity
        idx = 1
        for severity in _SEVERITY_ORDER:
            group = [f for f in unresolved if f.severity == severity]
            if not group:
                continue
            label = _SEVERITY_LABEL[severity]
            sections.append(f"**{label}s ({len(group)})**")
            sections.append("")
            for finding in group:
                sections.extend(_format_finding_row(finding, index=idx))
                sections.append("")
                idx += 1

    # ── Accepted Risk (Waivers) ─────────────────────────────────────
    waived = [
        f for f in report.findings if f.baseline_status == FindingBaselineStatus.waived
    ]

    sections.append("## Accepted Risk (Waivers)")
    sections.append("")

    if not waived:
        sections.append("No waived findings.")
    else:
        for i, finding in enumerate(waived, 1):
            fp = finding_fingerprint(finding)
            reason = waiver_reasons.get(fp, "No reason recorded")
            sections.append(f"### {i}. {finding.title}")
            sections.append("")
            sections.append(
                f"- **Severity:** {_SEVERITY_LABEL.get(finding.severity, finding.severity.value)}"
            )
            sections.append(f"- **Component:** `{finding.component_ref}`")
            sections.append(f"- **Waiver reason:** {reason}")
            evidence_lines = _format_evidence_block(finding)
            if evidence_lines:
                sections.extend(evidence_lines)
            sections.append("")

    # ── Evidence References ─────────────────────────────────────────
    sections.append("## Evidence References")
    sections.append("")

    has_evidence = any(
        f.evidence.refs or f.evidence.nets or f.evidence.sheet_paths or f.evidence.datasheets
        for f in report.findings
    )
    if not has_evidence:
        sections.append("No evidence references recorded.")
    else:
        sections.append("| Finding | Refs | Nets | Sheets | Datasheet Pages |")
        sections.append("|---------|------|------|--------|-----------------|")
        for finding in report.findings:
            ev = finding.evidence
            refs = ", ".join(ev.refs) if ev.refs else "-"
            nets = ", ".join(ev.nets) if ev.nets else "-"
            sheets = ", ".join(ev.sheet_paths) if ev.sheet_paths else "-"
            ds_pages: list[str] = []
            for ds in ev.datasheets:
                label = ds.mpn or ds.manufacturer or "datasheet"
                if ds.relevant_pages:
                    page_list = ", ".join(str(p) for p in ds.relevant_pages)
                    ds_pages.append(f"{label} p.{page_list}")
                else:
                    ds_pages.append(label)
            pages_str = "; ".join(ds_pages) if ds_pages else "-"
            title_short = finding.title[:50]
            sections.append(f"| {title_short} | {refs} | {nets} | {sheets} | {pages_str} |")

    # ── Reproducibility Metadata ────────────────────────────────────
    sections.append("")
    sections.append("## Reproducibility Metadata")
    sections.append("")
    sections.append("```yaml")
    sections.append(f"schematic: {sch_path}")
    sections.append(f"review_timestamp: {now_iso}")
    sections.append(f"revlo_version: {__version__}")
    sections.append(f"review_profile: {report.review_profile or 'default'}")
    sections.append(f"llm_provider: {report.llm_provider or 'N/A'}")
    sections.append(f"llm_model: {report.llm_model or 'N/A'}")
    sections.append(f"datasheet_mode: {report.datasheet_mode or 'N/A'}")
    sections.append("```")

    # ── Footer ──────────────────────────────────────────────────────
    sections.append("")
    sections.append("---")
    sections.append(f"*Generated by Revlo {__version__}*")

    return "\n".join(sections) + "\n"
