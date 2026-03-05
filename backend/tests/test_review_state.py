"""Tests for project-local baseline and waiver persistence."""

from __future__ import annotations

from pathlib import Path

from revlo.review_state import (
    FindingWaivers,
    WaiverEntry,
    baseline_path_for_schematic,
    finding_fingerprint,
    load_baseline,
    load_waivers,
    save_baseline,
    save_waivers,
    snapshot_finding,
    waivers_path_for_schematic,
)
from revlo.reviewer.models import (
    DatasheetEvidence,
    Finding,
    FindingCategory,
    FindingEvidence,
    FindingSourceType,
    ReviewReport,
    Severity,
)


def _make_finding(**overrides) -> Finding:
    defaults = dict(
        severity=Severity.warning,
        category=FindingCategory.power,
        component_ref="U1",
        title="Missing decoupling capacitor",
        description="No decoupling capacitor found near the MCU supply pins.",
        recommendation="Add a 100nF capacitor close to U1.",
        confidence=0.91,
        source_type=FindingSourceType.deterministic,
        evidence=FindingEvidence(
            refs=["U1", "C1"],
            nets=["3V3"],
            sheet_paths=["/Power"],
            datasheets=[
                DatasheetEvidence(
                    mpn="STM32F103C8T6",
                    relevant_pages=[47],
                )
            ],
        ),
    )
    defaults.update(overrides)
    return Finding(**defaults)


def test_sidecar_paths_live_next_to_schematic(tmp_path: Path) -> None:
    schematic = tmp_path / "board.kicad_sch"

    assert baseline_path_for_schematic(schematic) == tmp_path / "board.revlo-baseline.json"
    assert waivers_path_for_schematic(schematic) == tmp_path / "board.revlo-waivers.json"


def test_finding_fingerprint_is_stable_for_normalized_text_and_order() -> None:
    finding_a = _make_finding(
        title="Missing  decoupling capacitor",
        evidence=FindingEvidence(
            refs=["C1", "U1"],
            nets=["3V3"],
            sheet_paths=["/Power"],
        ),
    )
    finding_b = _make_finding(
        title="missing decoupling capacitor",
        evidence=FindingEvidence(
            refs=["U1", "C1"],
            nets=["3V3"],
            sheet_paths=["/Power"],
        ),
    )

    assert finding_fingerprint(finding_a) == finding_fingerprint(finding_b)


def test_snapshot_finding_preserves_structured_evidence() -> None:
    finding = _make_finding()

    snapshot = snapshot_finding(finding)

    assert snapshot.fingerprint.startswith("sha256:")
    assert snapshot.source_type == FindingSourceType.deterministic
    assert snapshot.evidence.refs == ["U1", "C1"]
    assert snapshot.evidence.datasheets[0].mpn == "STM32F103C8T6"


def test_save_and_load_baseline_round_trip(tmp_path: Path) -> None:
    schematic = tmp_path / "board.kicad_sch"
    schematic.write_text("(kicad_sch ...)")
    report = ReviewReport(
        findings=[_make_finding()],
        llm_provider="openai",
        llm_model="gpt-5.4",
        datasheet_mode="fast",
        review_profile="generic",
    )

    saved = save_baseline(
        report,
        schematic,
        source_review=".revlo/board-review-20260305T120000.json",
    )
    loaded = load_baseline(schematic)

    assert saved == tmp_path / "board.revlo-baseline.json"
    assert loaded is not None
    assert loaded.schematic == "board.kicad_sch"
    assert loaded.source_review == ".revlo/board-review-20260305T120000.json"
    assert loaded.llm_provider == "openai"
    assert loaded.review_profile == "generic"
    assert loaded.findings[0].component_ref == "U1"
    assert loaded.findings[0].fingerprint.startswith("sha256:")


def test_load_baseline_returns_none_when_missing(tmp_path: Path) -> None:
    schematic = tmp_path / "board.kicad_sch"
    schematic.write_text("(kicad_sch ...)")

    assert load_baseline(schematic) is None


def test_save_and_load_waivers_round_trip(tmp_path: Path) -> None:
    schematic = tmp_path / "board.kicad_sch"
    schematic.write_text("(kicad_sch ...)")
    entries = [
        WaiverEntry(
            fingerprint="sha256:abc123",
            reason="Intentional prototype exception",
            created_at="2026-03-05T12:05:00+00:00",
            created_by="",
            expires_at=None,
        )
    ]

    saved = save_waivers(schematic, entries)
    loaded = load_waivers(schematic)

    assert saved == tmp_path / "board.revlo-waivers.json"
    assert loaded is not None
    assert isinstance(loaded, FindingWaivers)
    assert loaded.schematic == "board.kicad_sch"
    assert loaded.entries[0].reason == "Intentional prototype exception"
    assert loaded.entries[0].fingerprint == "sha256:abc123"


def test_load_waivers_returns_none_when_missing(tmp_path: Path) -> None:
    schematic = tmp_path / "board.kicad_sch"
    schematic.write_text("(kicad_sch ...)")

    assert load_waivers(schematic) is None
