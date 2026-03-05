"""Deterministic schematic rule-engine scaffold."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from revlo.parser.models import ParsedSchematic
from revlo.reviewer.models import Finding

_RULES_ENV_VAR = "REVLO_ENABLE_RULES"


class DeterministicRule(Protocol):
    """Protocol for future deterministic schematic checks."""

    name: str

    def evaluate(self, schematic: ParsedSchematic) -> list[Finding]:
        """Evaluate the rule against a parsed schematic."""


@dataclass(slots=True)
class DeterministicRuleEngine:
    """Small coordinator for deterministic review rules."""

    rules: tuple[DeterministicRule, ...] = ()

    def evaluate(self, schematic: ParsedSchematic) -> list[Finding]:
        findings: list[Finding] = []
        for rule in self.rules:
            findings.extend(rule.evaluate(schematic))
        return findings


def resolve_deterministic_checks_enabled(
    override: bool | None = None,
) -> bool:
    """Resolve whether deterministic checks should run."""
    if override is not None:
        return override

    raw = os.environ.get(_RULES_ENV_VAR, "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def run_deterministic_checks(
    schematic: ParsedSchematic,
    enabled: bool | None = None,
    engine: DeterministicRuleEngine | None = None,
) -> list[Finding]:
    """Run deterministic schematic checks without provider access."""
    if not resolve_deterministic_checks_enabled(enabled):
        return []

    resolved_engine = engine or DeterministicRuleEngine()
    return resolved_engine.evaluate(schematic)
