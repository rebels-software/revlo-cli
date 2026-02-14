"""Tests for EE specialist agent skill files (US-029)."""

import json
import re

import pytest

from revlo.reviewer.models import Finding, FindingCategory, Severity
from revlo.skills import load_skill

# All skill file names (without .md extension)
SPECIALIST_SKILLS = [
    "power_supply_review",
    "signal_integrity_review",
    "interface_grounding_review",
    "ic_pin_config_review",
    "bom_lifecycle_review",
    "pcb_layout_review",
]

ALL_SKILLS = ["base_ee_knowledge", "orchestrator", *SPECIALIST_SKILLS]


def test_load_skill_returns_content():
    """load_skill() returns non-empty content for all 8 skill files."""
    for skill_name in ALL_SKILLS:
        content = load_skill(skill_name)
        assert isinstance(content, str)
        assert len(content) > 100  # Reasonable minimum for a skill file


def test_load_skill_nonexistent_raises():
    """load_skill() raises FileNotFoundError for nonexistent skill."""
    with pytest.raises(FileNotFoundError):
        load_skill("nonexistent_skill")


def test_specialist_files_have_required_sections():
    """Each specialist file contains required sections: Review Checklist, Output Format, Example Findings."""
    for skill_name in SPECIALIST_SKILLS:
        content = load_skill(skill_name)

        assert "Review Checklist" in content, f"{skill_name} missing 'Review Checklist' section"
        assert "Output Format" in content, f"{skill_name} missing 'Output Format' section"
        assert "Example Findings" in content, f"{skill_name} missing 'Example Findings' section"


def test_specialist_files_have_valid_json_examples():
    """Example findings in each specialist file are valid JSON with required Finding schema."""
    for skill_name in SPECIALIST_SKILLS:
        content = load_skill(skill_name)

        match = re.search(
            r"## Example Findings\s+```json\s+(.*?)\s+```",
            content,
            re.DOTALL,
        )
        assert match, f"{skill_name} has no JSON code block in Example Findings section"

        json_text = match.group(1)

        try:
            findings_data = json.loads(json_text)
        except json.JSONDecodeError as e:
            pytest.fail(f"{skill_name} has invalid JSON in Example Findings: {e}")

        assert isinstance(findings_data, list), f"{skill_name} examples should be a JSON array"
        assert len(findings_data) > 0, f"{skill_name} has no example findings"

        for i, finding_dict in enumerate(findings_data):
            try:
                finding = Finding(**finding_dict)
            except Exception as e:
                pytest.fail(
                    f"{skill_name} example finding #{i+1} failed validation: {e}\n"
                    f"Finding data: {finding_dict}"
                )

            assert finding.severity in {
                Severity.error,
                Severity.warning,
                Severity.suggestion,
            }, f"{skill_name} example #{i+1} has invalid severity: {finding.severity}"

            assert finding.category in set(
                FindingCategory
            ), f"{skill_name} example #{i+1} has invalid category: {finding.category}"

            assert (
                0.0 <= finding.confidence <= 1.0
            ), f"{skill_name} example #{i+1} has confidence {finding.confidence} outside [0.0, 1.0]"

            assert (
                finding.component_ref.strip()
            ), f"{skill_name} example #{i+1} has empty component_ref"
            assert finding.title.strip(), f"{skill_name} example #{i+1} has empty title"
            assert (
                finding.description.strip()
            ), f"{skill_name} example #{i+1} has empty description"
            assert (
                finding.recommendation.strip()
            ), f"{skill_name} example #{i+1} has empty recommendation"
