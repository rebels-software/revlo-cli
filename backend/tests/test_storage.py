"""Test suite for review storage (revlo/storage.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from revlo.reviewer.models import (
    Finding,
    FindingCategory,
    ReviewReport,
    Severity,
)
from revlo.storage import load_latest_review, save_review


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def sample_report() -> ReviewReport:
    """Return a minimal ReviewReport for testing."""
    return ReviewReport(
        findings=[
            Finding(
                severity=Severity.error,
                category=FindingCategory.decoupling,
                component_ref="U1",
                title="Missing decoupling capacitor",
                description="No decoupling capacitor found near U1.",
                recommendation="Add a 100nF capacitor close to the power pins.",
                confidence=0.95,
            )
        ],
        summary="Found 1 issues (1 errors, 0 warnings, 0 suggestions)",
        schematic_title="Test Schematic",
        review_date="2026-02-12",
    )


@pytest.fixture
def fake_schematic(tmp_path: Path) -> Path:
    """Create a fake .kicad_sch file and return its path."""
    sch = tmp_path / "board.kicad_sch"
    sch.write_text("(kicad_sch ...)")
    return sch


# ---------------------------------------------------------------------------
# save_review tests
# ---------------------------------------------------------------------------
def test_save_review_creates_revlo_dir(
    sample_report: ReviewReport, fake_schematic: Path
) -> None:
    """save_review() creates .revlo/ directory next to the schematic."""
    saved = save_review(sample_report, str(fake_schematic))

    revlo_dir = fake_schematic.parent / ".revlo"
    assert revlo_dir.is_dir()
    assert saved.parent == revlo_dir
    assert saved.exists()


def test_save_review_filename_format(
    sample_report: ReviewReport, fake_schematic: Path
) -> None:
    """Saved file follows {stem}-review-{timestamp}.json pattern."""
    saved = save_review(sample_report, str(fake_schematic))
    assert saved.name.startswith("board-review-")
    assert saved.suffix == ".json"


def test_save_review_contains_valid_report_and_meta(
    sample_report: ReviewReport, fake_schematic: Path
) -> None:
    """Saved JSON contains both the ReviewReport data and _meta."""
    saved = save_review(sample_report, str(fake_schematic))
    data = json.loads(saved.read_text())

    # _meta present
    assert "_meta" in data
    meta = data["_meta"]
    assert meta["schematic"] == "board.kicad_sch"
    assert "saved_at" in meta
    assert meta["revlo_version"] == "0.1.0"

    # Report data is round-trippable
    meta_copy = data.pop("_meta")  # noqa: F841
    report = ReviewReport.model_validate(data)
    assert len(report.findings) == 1
    assert report.findings[0].title == "Missing decoupling capacitor"


def test_save_review_idempotent_dir(
    sample_report: ReviewReport, fake_schematic: Path
) -> None:
    """Calling save_review twice does not fail (exist_ok)."""
    save_review(sample_report, str(fake_schematic))
    saved2 = save_review(sample_report, str(fake_schematic))
    assert saved2.exists()


# ---------------------------------------------------------------------------
# load_latest_review tests
# ---------------------------------------------------------------------------
def test_load_latest_review_returns_none_when_no_dir(
    fake_schematic: Path,
) -> None:
    """load_latest_review() returns None when .revlo/ doesn't exist."""
    result = load_latest_review(str(fake_schematic))
    assert result is None


def test_load_latest_review_returns_none_when_empty_dir(
    fake_schematic: Path,
) -> None:
    """load_latest_review() returns None when .revlo/ is empty."""
    (fake_schematic.parent / ".revlo").mkdir()
    result = load_latest_review(str(fake_schematic))
    assert result is None


def test_load_latest_review_returns_none_for_different_schematic(
    sample_report: ReviewReport, fake_schematic: Path
) -> None:
    """load_latest_review() returns None for a schematic with no matching files."""
    save_review(sample_report, str(fake_schematic))
    other = fake_schematic.parent / "other.kicad_sch"
    other.write_text("(kicad_sch ...)")
    result = load_latest_review(str(other))
    assert result is None


def test_load_latest_review_round_trip(
    sample_report: ReviewReport, fake_schematic: Path
) -> None:
    """save then load returns the same report data."""
    save_review(sample_report, str(fake_schematic))
    result = load_latest_review(str(fake_schematic))
    assert result is not None

    report, meta = result
    assert report.schematic_title == "Test Schematic"
    assert len(report.findings) == 1
    assert report.findings[0].component_ref == "U1"
    assert meta["schematic"] == "board.kicad_sch"


def test_load_latest_review_picks_newest(
    sample_report: ReviewReport, fake_schematic: Path
) -> None:
    """When multiple reviews exist, load_latest_review returns the newest."""
    # Save two reviews with different timestamps by manipulating filenames
    revlo_dir = fake_schematic.parent / ".revlo"
    revlo_dir.mkdir(exist_ok=True)

    # Older review
    older_data = sample_report.model_dump()
    older_data["_meta"] = {
        "schematic": "board.kicad_sch",
        "saved_at": "2026-01-01T00:00:00+00:00",
        "revlo_version": "0.1.0",
    }
    older_data["summary"] = "older review"
    (revlo_dir / "board-review-20260101T000000.json").write_text(
        json.dumps(older_data, indent=2)
    )

    # Newer review
    newer_data = sample_report.model_dump()
    newer_data["_meta"] = {
        "schematic": "board.kicad_sch",
        "saved_at": "2026-02-12T120000+00:00",
        "revlo_version": "0.1.0",
    }
    newer_data["summary"] = "newer review"
    (revlo_dir / "board-review-20260212T120000.json").write_text(
        json.dumps(newer_data, indent=2)
    )

    result = load_latest_review(str(fake_schematic))
    assert result is not None
    report, meta = result
    assert report.summary == "newer review"
