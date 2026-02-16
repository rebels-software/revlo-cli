"""Persistent review storage in .revlo/ directory alongside schematics."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from revlo.reviewer.models import ReviewReport


@dataclass
class HistoryEntry:
    """A single entry in the review/chat history."""

    path: Path
    entry_type: str  # "review" or "chat"
    meta: dict
    summary: str


def save_review(report: ReviewReport, schematic_path: str) -> Path:
    """Save review report as JSON in .revlo/ next to the schematic.

    Filename format: {stem}-review-{timestamp}.json
    Returns the path to the saved file.
    """
    sch = Path(schematic_path)
    revlo_dir = sch.parent / ".revlo"
    revlo_dir.mkdir(exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    filename = f"{sch.stem}-review-{timestamp}.json"
    out_path = revlo_dir / filename

    # Add metadata
    data = report.model_dump()
    data["_meta"] = {
        "schematic": sch.name,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "revlo_version": "0.1.0",
    }

    out_path.write_text(json.dumps(data, indent=2))
    return out_path


def save_chat(
    messages: list[dict],
    schematic_path: str,
) -> Path:
    """Save chat conversation as JSON in .revlo/ next to the schematic.

    Filename format: {stem}-chat-{timestamp}.json
    Returns the path to the saved file.

    ``messages`` should be a list of dicts with keys: role, content, timestamp.
    """
    sch = Path(schematic_path)
    revlo_dir = sch.parent / ".revlo"
    revlo_dir.mkdir(exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    filename = f"{sch.stem}-chat-{timestamp}.json"
    out_path = revlo_dir / filename

    data: dict = {
        "messages": messages,
        "_meta": {
            "schematic": sch.name,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "revlo_version": "0.1.0",
            "type": "chat",
        },
    }

    out_path.write_text(json.dumps(data, indent=2))
    return out_path


def load_latest_review(schematic_path: str) -> tuple[ReviewReport, dict] | None:
    """Load the most recent review for a schematic.

    Returns (report, metadata) or None if no reviews exist.
    """
    sch = Path(schematic_path)
    revlo_dir = sch.parent / ".revlo"

    if not revlo_dir.is_dir():
        return None

    # Find review files for this schematic
    pattern = f"{sch.stem}-review-*.json"
    files = sorted(revlo_dir.glob(pattern), reverse=True)  # newest first

    if not files:
        return None

    latest = files[0]
    data = json.loads(latest.read_text())

    meta = data.pop("_meta", {})
    report = ReviewReport.model_validate(data)
    return report, meta


def _build_review_summary(data: dict) -> str:
    """Build a human-readable summary from review JSON data.

    Counts findings by severity, e.g. "2 errors, 3 warnings, 1 suggestion".
    """
    findings = data.get("findings", [])
    counts: dict[str, int] = {"error": 0, "warning": 0, "suggestion": 0}
    for f in findings:
        sev = f.get("severity", "")
        if sev in counts:
            counts[sev] += 1

    parts: list[str] = []
    if counts["error"]:
        parts.append(f"{counts['error']} error{'s' if counts['error'] != 1 else ''}")
    if counts["warning"]:
        parts.append(
            f"{counts['warning']} warning{'s' if counts['warning'] != 1 else ''}"
        )
    if counts["suggestion"]:
        parts.append(
            f"{counts['suggestion']} suggestion{'s' if counts['suggestion'] != 1 else ''}"
        )
    if not parts:
        return "no findings"
    return ", ".join(parts)


def _build_chat_summary(data: dict) -> str:
    """Build a human-readable summary from chat JSON data.

    Counts messages, e.g. "12 messages".
    """
    messages = data.get("messages", [])
    n = len(messages)
    return f"{n} message{'s' if n != 1 else ''}"


def list_entries(schematic_path: str) -> list[HistoryEntry]:
    """List all saved reviews and chats for a schematic, newest first.

    Scans the .revlo/ directory for files matching:
      - {stem}-review-*.json  (reviews)
      - {stem}-chat-*.json    (chats)

    Returns a list of HistoryEntry sorted by timestamp (newest first).
    """
    sch = Path(schematic_path)
    revlo_dir = sch.parent / ".revlo"

    if not revlo_dir.is_dir():
        return []

    entries: list[HistoryEntry] = []

    for entry_type, pattern in [
        ("review", f"{sch.stem}-review-*.json"),
        ("chat", f"{sch.stem}-chat-*.json"),
    ]:
        for file_path in revlo_dir.glob(pattern):
            try:
                data = json.loads(file_path.read_text())
            except (json.JSONDecodeError, OSError):
                continue

            meta = data.get("_meta", {})

            if entry_type == "review":
                summary = _build_review_summary(data)
            else:
                summary = _build_chat_summary(data)

            entries.append(HistoryEntry(
                path=file_path,
                entry_type=entry_type,
                meta=meta,
                summary=summary,
            ))

    # Sort by saved_at timestamp (newest first), falling back to filename
    def _sort_key(e: HistoryEntry) -> str:
        return e.meta.get("saved_at", e.path.name)

    entries.sort(key=_sort_key, reverse=True)
    return entries


def load_entry(entry_path: Path) -> tuple[ReviewReport | dict, dict, str]:
    """Load a history entry by its file path.

    Returns (data, meta, entry_type) where:
      - data is a ReviewReport for reviews, or a raw dict for chats
      - meta is the _meta dict
      - entry_type is "review" or "chat"
    """
    raw = json.loads(entry_path.read_text())
    meta = raw.pop("_meta", {})

    # Determine type from filename
    if "-review-" in entry_path.name:
        report = ReviewReport.model_validate(raw)
        return report, meta, "review"
    else:
        return raw, meta, "chat"
