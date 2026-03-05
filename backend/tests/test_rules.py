"""Tests for deterministic rule-engine scaffolding."""

from __future__ import annotations

from dataclasses import dataclass

from revlo.parser.models import ParsedSchematic, TitleBlockInfo
from revlo.reviewer.models import Finding
from revlo.reviewer.rules import (
    DeterministicRuleEngine,
    resolve_deterministic_checks_enabled,
    run_deterministic_checks,
)


@dataclass(slots=True)
class _StubRule:
    name: str = "stub"

    def evaluate(self, schematic: ParsedSchematic) -> list[Finding]:
        assert schematic.title_block.title == "Rule Test"
        return []


def test_resolve_deterministic_checks_enabled_override():
    assert resolve_deterministic_checks_enabled(True) is True
    assert resolve_deterministic_checks_enabled(False) is False


def test_rule_engine_evaluates_registered_rules():
    schematic = ParsedSchematic(title_block=TitleBlockInfo(title="Rule Test"))
    engine = DeterministicRuleEngine(rules=(_StubRule(),))

    findings = engine.evaluate(schematic)

    assert findings == []


def test_run_deterministic_checks_returns_empty_when_disabled():
    schematic = ParsedSchematic(title_block=TitleBlockInfo(title="Rule Test"))
    engine = DeterministicRuleEngine(rules=(_StubRule(),))

    findings = run_deterministic_checks(schematic, enabled=False, engine=engine)

    assert findings == []
