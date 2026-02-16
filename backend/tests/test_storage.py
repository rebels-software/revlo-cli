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
from revlo.storage import (
    HistoryEntry,
    list_entries,
    load_entry,
    load_latest_review,
    save_review,
)


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
    from revlo import __version__
    assert meta["revlo_version"] == __version__

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

    report, meta, review_file = result
    assert report.schematic_title == "Test Schematic"
    assert len(report.findings) == 1
    assert report.findings[0].component_ref == "U1"
    assert meta["schematic"] == "board.kicad_sch"
    assert review_file.exists()
    assert review_file.name.startswith("board-review-")


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
    report, meta, review_file = result
    assert report.summary == "newer review"
    assert "20260212T120000" in review_file.name


# ---------------------------------------------------------------------------
# list_entries tests
# ---------------------------------------------------------------------------
def test_list_entries_empty_when_no_dir(fake_schematic: Path) -> None:
    """list_entries() returns [] when .revlo/ doesn't exist."""
    entries = list_entries(str(fake_schematic))
    assert entries == []


def test_list_entries_empty_when_dir_empty(fake_schematic: Path) -> None:
    """list_entries() returns [] when .revlo/ exists but has no matching files."""
    (fake_schematic.parent / ".revlo").mkdir()
    entries = list_entries(str(fake_schematic))
    assert entries == []


def test_list_entries_finds_reviews(
    sample_report: ReviewReport, fake_schematic: Path
) -> None:
    """list_entries() discovers saved review files."""
    save_review(sample_report, str(fake_schematic))
    entries = list_entries(str(fake_schematic))
    assert len(entries) == 1
    assert entries[0].entry_type == "review"
    assert "1 error" in entries[0].summary


def test_list_entries_sorted_newest_first(
    sample_report: ReviewReport, fake_schematic: Path
) -> None:
    """list_entries() returns newest entries first."""
    revlo_dir = fake_schematic.parent / ".revlo"
    revlo_dir.mkdir(exist_ok=True)

    # Older review
    older_data = sample_report.model_dump()
    older_data["_meta"] = {
        "schematic": "board.kicad_sch",
        "saved_at": "2026-01-01T00:00:00+00:00",
        "revlo_version": "0.1.0",
    }
    older_data["summary"] = "older"
    (revlo_dir / "board-review-20260101T000000.json").write_text(
        json.dumps(older_data, indent=2)
    )

    # Newer review
    newer_data = sample_report.model_dump()
    newer_data["_meta"] = {
        "schematic": "board.kicad_sch",
        "saved_at": "2026-02-12T12:00:00+00:00",
        "revlo_version": "0.1.0",
    }
    newer_data["summary"] = "newer"
    (revlo_dir / "board-review-20260212T120000.json").write_text(
        json.dumps(newer_data, indent=2)
    )

    entries = list_entries(str(fake_schematic))
    assert len(entries) == 2
    # First entry should be the newer one
    assert entries[0].meta.get("saved_at", "").startswith("2026-02-12")
    assert entries[1].meta.get("saved_at", "").startswith("2026-01-01")


def test_list_entries_mixed_review_and_chat(
    sample_report: ReviewReport, fake_schematic: Path
) -> None:
    """list_entries() discovers both review and chat files."""
    revlo_dir = fake_schematic.parent / ".revlo"
    revlo_dir.mkdir(exist_ok=True)

    # A review file
    review_data = sample_report.model_dump()
    review_data["_meta"] = {
        "schematic": "board.kicad_sch",
        "saved_at": "2026-01-15T10:00:00+00:00",
        "revlo_version": "0.1.0",
    }
    (revlo_dir / "board-review-20260115T100000.json").write_text(
        json.dumps(review_data, indent=2)
    )

    # A chat file
    chat_data = {
        "_meta": {
            "schematic": "board.kicad_sch",
            "saved_at": "2026-02-01T14:00:00+00:00",
            "revlo_version": "0.1.0",
        },
        "messages": [
            {"role": "user", "content": "What about C1?"},
            {"role": "assistant", "content": "C1 looks fine."},
            {"role": "user", "content": "Thanks"},
        ],
    }
    (revlo_dir / "board-chat-20260201T140000.json").write_text(
        json.dumps(chat_data, indent=2)
    )

    entries = list_entries(str(fake_schematic))
    assert len(entries) == 2

    # Newest first: chat (Feb) before review (Jan)
    assert entries[0].entry_type == "chat"
    assert entries[0].summary == "3 messages"
    assert entries[1].entry_type == "review"
    assert "1 error" in entries[1].summary


def test_list_entries_ignores_other_schematics(
    sample_report: ReviewReport, fake_schematic: Path
) -> None:
    """list_entries() only returns files matching the given schematic stem."""
    save_review(sample_report, str(fake_schematic))

    # Create a file for a different schematic
    revlo_dir = fake_schematic.parent / ".revlo"
    other_data = sample_report.model_dump()
    other_data["_meta"] = {
        "schematic": "other.kicad_sch",
        "saved_at": "2026-03-01T00:00:00+00:00",
        "revlo_version": "0.1.0",
    }
    (revlo_dir / "other-review-20260301T000000.json").write_text(
        json.dumps(other_data, indent=2)
    )

    entries = list_entries(str(fake_schematic))
    assert len(entries) == 1
    assert entries[0].entry_type == "review"


def test_list_entries_summary_multiple_severities(
    fake_schematic: Path,
) -> None:
    """list_entries() builds correct summary with multiple severity counts."""
    revlo_dir = fake_schematic.parent / ".revlo"
    revlo_dir.mkdir(exist_ok=True)

    data = {
        "findings": [
            {
                "severity": "error",
                "category": "decoupling",
                "component_ref": "U1",
                "title": "t",
                "description": "d",
                "recommendation": "r",
                "confidence": 0.9,
            },
            {
                "severity": "error",
                "category": "power",
                "component_ref": "U2",
                "title": "t",
                "description": "d",
                "recommendation": "r",
                "confidence": 0.8,
            },
            {
                "severity": "warning",
                "category": "grounding",
                "component_ref": "R1",
                "title": "t",
                "description": "d",
                "recommendation": "r",
                "confidence": 0.7,
            },
        ],
        "summary": "test",
        "schematic_title": "Test",
        "review_date": "2026-02-12",
        "_meta": {
            "schematic": "board.kicad_sch",
            "saved_at": "2026-02-12T00:00:00+00:00",
            "revlo_version": "0.1.0",
        },
    }
    (revlo_dir / "board-review-20260212T000000.json").write_text(
        json.dumps(data, indent=2)
    )

    entries = list_entries(str(fake_schematic))
    assert len(entries) == 1
    assert entries[0].summary == "2 errors, 1 warning"


def test_list_entries_summary_no_findings(fake_schematic: Path) -> None:
    """list_entries() returns 'no findings' for a review with empty findings."""
    revlo_dir = fake_schematic.parent / ".revlo"
    revlo_dir.mkdir(exist_ok=True)

    data = {
        "findings": [],
        "summary": "clean",
        "schematic_title": "Test",
        "review_date": "2026-02-12",
        "_meta": {
            "schematic": "board.kicad_sch",
            "saved_at": "2026-02-12T00:00:00+00:00",
            "revlo_version": "0.1.0",
        },
    }
    (revlo_dir / "board-review-20260212T000000.json").write_text(
        json.dumps(data, indent=2)
    )

    entries = list_entries(str(fake_schematic))
    assert len(entries) == 1
    assert entries[0].summary == "no findings"


# ---------------------------------------------------------------------------
# load_entry tests
# ---------------------------------------------------------------------------
def test_load_entry_review(
    sample_report: ReviewReport, fake_schematic: Path
) -> None:
    """load_entry() returns ReviewReport for review files."""
    saved = save_review(sample_report, str(fake_schematic))
    data, meta, entry_type = load_entry(saved)

    assert entry_type == "review"
    assert isinstance(data, ReviewReport)
    assert len(data.findings) == 1
    assert data.findings[0].component_ref == "U1"
    assert meta["schematic"] == "board.kicad_sch"


def test_load_entry_chat(fake_schematic: Path) -> None:
    """load_entry() returns raw dict for chat files."""
    revlo_dir = fake_schematic.parent / ".revlo"
    revlo_dir.mkdir(exist_ok=True)

    chat_data = {
        "_meta": {
            "schematic": "board.kicad_sch",
            "saved_at": "2026-02-01T14:00:00+00:00",
            "revlo_version": "0.1.0",
        },
        "messages": [
            {"role": "user", "content": "Hello"},
        ],
    }
    chat_path = revlo_dir / "board-chat-20260201T140000.json"
    chat_path.write_text(json.dumps(chat_data, indent=2))

    data, meta, entry_type = load_entry(chat_path)

    assert entry_type == "chat"
    assert isinstance(data, dict)
    assert len(data["messages"]) == 1
    assert meta["schematic"] == "board.kicad_sch"


def test_list_entries_skips_corrupt_json(fake_schematic: Path) -> None:
    """list_entries() gracefully skips files with invalid JSON."""
    revlo_dir = fake_schematic.parent / ".revlo"
    revlo_dir.mkdir(exist_ok=True)

    # Corrupt JSON file
    (revlo_dir / "board-review-20260101T000000.json").write_text("not json{{{")

    entries = list_entries(str(fake_schematic))
    assert entries == []
