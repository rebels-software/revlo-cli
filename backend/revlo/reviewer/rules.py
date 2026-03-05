"""Deterministic schematic rule-engine scaffold."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Protocol

from revlo.bom import BomDocument
from revlo.constraints import ConstraintItem, ProjectConstraints
from revlo.parser.models import ParsedComponent, ParsedNet, ParsedPin, ParsedSchematic
from revlo.reviewer.models import (
    Finding,
    FindingCategory,
    FindingEvidence,
    FindingSourceType,
    Severity,
)
from revlo.rule_packs import CustomRuleDefinition, CustomRulePack, RulePackMatchCondition

logger = logging.getLogger(__name__)

_RULES_ENV_VAR = "REVLO_ENABLE_RULES"


class DeterministicRule(Protocol):
    """Protocol for future deterministic schematic checks."""

    name: str

    def evaluate(
        self,
        schematic: ParsedSchematic,
        *,
        bom: BomDocument | None = None,
        project_constraints: ProjectConstraints | None = None,
    ) -> list[Finding]:
        """Evaluate the rule against a parsed schematic."""


def _build_net_lookup(schematic: ParsedSchematic) -> dict[str, ParsedNet]:
    return {net.name.upper(): net for net in schematic.nets}


def _build_unconnected_set(schematic: ParsedSchematic) -> set[tuple[str, str]]:
    return {
        (pin.component_ref.upper(), pin.pin_number)
        for pin in schematic.unconnected_pins
    }


def _is_ground_net(net_name: str) -> bool:
    normalized = net_name.strip().upper()
    return any(token in normalized for token in ("GND", "VSS", "PGND", "AGND", "DGND"))


def _is_power_pin(pin: ParsedPin) -> bool:
    pin_name = pin.name.upper()
    if "power" in pin.electrical_type.lower():
        return True
    return any(
        token in pin_name
        for token in ("VDD", "VCC", "VIN", "VBAT", "AVDD", "DVDD", "VREF", "VIO")
    )


def _is_active_component(component: ParsedComponent) -> bool:
    ref = component.reference.upper()
    return not ref.startswith(("C", "R", "L", "FB", "TP", "MH", "JP"))


def _power_nets_for_component(
    component: ParsedComponent,
    net_lookup: dict[str, ParsedNet],
) -> list[str]:
    nets: list[str] = []
    for pin in component.pins:
        if not pin.connected_net or not _is_power_pin(pin):
            continue
        net = net_lookup.get(pin.connected_net.upper())
        if net is None or not net.is_power or _is_ground_net(net.name):
            continue
        nets.append(net.name)
    return sorted(set(nets))


def _has_decoupling_cap(
    net_name: str,
    schematic: ParsedSchematic,
) -> bool:
    for component in schematic.components:
        ref = component.reference.upper()
        lib_id = component.lib_id.upper()
        if not (ref.startswith("C") or lib_id.startswith("DEVICE:C")):
            continue
        connected_nets = {pin.connected_net for pin in component.pins if pin.connected_net}
        if net_name in connected_nets and any(
            candidate and _is_ground_net(candidate)
            for candidate in connected_nets
        ):
            return True
    return False


def _has_i2c_pullup(net: ParsedNet, schematic: ParsedSchematic) -> bool:
    component_lookup = {component.reference.upper(): component for component in schematic.components}
    for pin in net.pins:
        component = component_lookup.get(pin.component_ref.upper())
        if component is None:
            continue
        ref = component.reference.upper()
        lib_id = component.lib_id.upper()
        if not (ref.startswith("R") or lib_id.startswith("DEVICE:R")):
            continue
        other_nets = {
            candidate.connected_net
            for candidate in component.pins
            if candidate.connected_net and candidate.connected_net.upper() != net.name.upper()
        }
        if any(other and _build_net_lookup(schematic).get(other.upper(), ParsedNet(name="")).is_power for other in other_nets):
            return True
    return False


def _format_constraint(constraint: ConstraintItem) -> str:
    summary = f"{constraint.kind}: {constraint.name}"
    if constraint.target:
        summary += f" [target={constraint.target}]"
    if constraint.value:
        summary += f" -> {constraint.value}"
        if constraint.unit:
            summary += f" {constraint.unit}"
    return summary


def _constraint_notes(
    *,
    refs: list[str],
    nets: list[str],
    project_constraints: ProjectConstraints | None,
    status: str,
) -> list[str]:
    if project_constraints is None:
        return []

    ref_set = {ref.upper() for ref in refs}
    net_set = {net.upper() for net in nets}
    notes: list[str] = []
    for constraint in project_constraints.constraints:
        target = constraint.target.strip().upper()
        if not target:
            continue
        if target in ref_set or target in net_set:
            notes.append(f"Constraint {status}: {_format_constraint(constraint)}")
    return notes


@dataclass(slots=True)
class PowerConnectivityRule:
    name: str = "power_connectivity"

    def evaluate(
        self,
        schematic: ParsedSchematic,
        *,
        bom: BomDocument | None = None,
        project_constraints: ProjectConstraints | None = None,
    ) -> list[Finding]:
        findings: list[Finding] = []
        unconnected = _build_unconnected_set(schematic)
        for component in schematic.components:
            for pin in component.pins:
                if not _is_power_pin(pin):
                    continue
                if (component.reference.upper(), pin.number) not in unconnected:
                    continue
                findings.append(
                    Finding(
                        severity=Severity.error,
                        category=FindingCategory.power,
                        component_ref=component.reference,
                        title="Unconnected power pin",
                        description=(
                            f"Power pin {pin.number} ({pin.name}) on {component.reference} "
                            "is unconnected."
                        ),
                        recommendation="Connect the pin to the intended rail or mark it intentionally unused.",
                        confidence=0.99,
                        source_type=FindingSourceType.deterministic,
                        evidence=FindingEvidence(
                            refs=[component.reference],
                            sheet_paths=[component.source_sheet] if component.source_sheet else [],
                            notes=[
                                f"Power pin electrical type: {pin.electrical_type}",
                                *_constraint_notes(
                                    refs=[component.reference],
                                    nets=[pin.connected_net] if pin.connected_net else [],
                                    project_constraints=project_constraints,
                                    status="violated",
                                ),
                            ],
                        ),
                    )
                )
        return findings


@dataclass(slots=True)
class DecouplingPresenceRule:
    name: str = "decoupling_presence"

    def evaluate(
        self,
        schematic: ParsedSchematic,
        *,
        bom: BomDocument | None = None,
        project_constraints: ProjectConstraints | None = None,
    ) -> list[Finding]:
        findings: list[Finding] = []
        net_lookup = _build_net_lookup(schematic)
        for component in schematic.components:
            if not _is_active_component(component):
                continue
            for net_name in _power_nets_for_component(component, net_lookup):
                if _has_decoupling_cap(net_name, schematic):
                    continue
                findings.append(
                    Finding(
                        severity=Severity.warning,
                        category=FindingCategory.decoupling,
                        component_ref=component.reference,
                        title="No obvious decoupling capacitor on supply rail",
                        description=(
                            f"No capacitor tied between {net_name} and ground was found for "
                            f"{component.reference}."
                        ),
                        recommendation=(
                            f"Add a local bypass capacitor between {net_name} and ground near "
                            f"{component.reference}."
                        ),
                        confidence=0.86,
                        source_type=FindingSourceType.deterministic,
                        evidence=FindingEvidence(
                            refs=[component.reference],
                            nets=[net_name],
                            sheet_paths=[component.source_sheet] if component.source_sheet else [],
                            notes=_constraint_notes(
                                refs=[component.reference],
                                nets=[net_name],
                                project_constraints=project_constraints,
                                status="unverified",
                            ),
                        ),
                    )
                )
        return findings


@dataclass(slots=True)
class I2CBusPullupRule:
    name: str = "i2c_pullups"

    def evaluate(
        self,
        schematic: ParsedSchematic,
        *,
        bom: BomDocument | None = None,
        project_constraints: ProjectConstraints | None = None,
    ) -> list[Finding]:
        findings: list[Finding] = []
        for net in schematic.nets:
            name = net.name.upper()
            if "SDA" not in name and "SCL" not in name:
                continue
            if _has_i2c_pullup(net, schematic):
                continue
            refs = sorted({pin.component_ref for pin in net.pins})
            component_ref = refs[0] if refs else "I2C"
            findings.append(
                Finding(
                    severity=Severity.warning,
                    category=FindingCategory.pull_up,
                    component_ref=component_ref,
                    title="No obvious I2C pull-up resistor",
                    description=(
                        f"Net {net.name} looks like an I2C signal but no resistor pull-up "
                        "to a power rail was found."
                    ),
                    recommendation=(
                        f"Verify that {net.name} has an appropriate pull-up resistor to the "
                        "correct bus voltage."
                    ),
                    confidence=0.9,
                    source_type=FindingSourceType.deterministic,
                    evidence=FindingEvidence(
                        refs=refs,
                        nets=[net.name],
                        notes=_constraint_notes(
                            refs=refs,
                            nets=[net.name],
                            project_constraints=project_constraints,
                            status="unverified",
                        ),
                    ),
                )
            )
        return findings


@dataclass(slots=True)
class LibraryHygieneRule:
    name: str = "library_hygiene"

    def evaluate(
        self,
        schematic: ParsedSchematic,
        *,
        bom: BomDocument | None = None,
        project_constraints: ProjectConstraints | None = None,
    ) -> list[Finding]:
        findings: list[Finding] = []
        ref_counts: dict[str, int] = {}
        for component in schematic.components:
            ref_counts[component.reference.upper()] = ref_counts.get(component.reference.upper(), 0) + 1

        for component in schematic.components:
            evidence = FindingEvidence(
                refs=[component.reference],
                sheet_paths=[component.source_sheet] if component.source_sheet else [],
            )
            ref_upper = component.reference.upper()
            if ref_counts[ref_upper] > 1:
                findings.append(
                    Finding(
                        severity=Severity.error,
                        category=FindingCategory.library_hygiene,
                        component_ref=component.reference,
                        title="Duplicate reference designator",
                        description=(
                            f"Reference {component.reference} appears multiple times in the schematic."
                        ),
                        recommendation="Assign unique reference designators before review or manufacturing export.",
                        confidence=0.99,
                        source_type=FindingSourceType.deterministic,
                        evidence=evidence,
                    )
                )
            if not component.value.strip():
                findings.append(
                    Finding(
                        severity=Severity.warning,
                        category=FindingCategory.library_hygiene,
                        component_ref=component.reference,
                        title="Missing component value",
                        description=(
                            f"Component {component.reference} has no value field."
                        ),
                        recommendation="Populate the value field so reviews, BOMs, and assembly outputs stay traceable.",
                        confidence=0.95,
                        source_type=FindingSourceType.deterministic,
                        evidence=evidence,
                    )
                )
            if _is_active_component(component) and not component.footprint.strip():
                findings.append(
                    Finding(
                        severity=Severity.warning,
                        category=FindingCategory.library_hygiene,
                        component_ref=component.reference,
                        title="Missing footprint",
                        description=(
                            f"Active component {component.reference} has no footprint assigned."
                        ),
                        recommendation="Assign the intended PCB footprint before layout handoff.",
                        confidence=0.97,
                        source_type=FindingSourceType.deterministic,
                        evidence=evidence,
                    )
                )
        return findings


@dataclass(slots=True)
class BOMCoverageRule:
    name: str = "bom_coverage"

    def evaluate(
        self,
        schematic: ParsedSchematic,
        *,
        bom: BomDocument | None = None,
        project_constraints: ProjectConstraints | None = None,
    ) -> list[Finding]:
        if bom is None:
            return []

        findings: list[Finding] = []
        bom_refs = {
            ref.upper()
            for item in bom.items
            for ref in item.refs
        }
        for component in schematic.components:
            if not _is_active_component(component):
                continue
            if component.reference.upper() in bom_refs:
                continue
            findings.append(
                Finding(
                    severity=Severity.warning,
                    category=FindingCategory.bom,
                    component_ref=component.reference,
                    title="Component missing from BOM",
                    description=(
                        f"Active schematic component {component.reference} is not present in the loaded BOM."
                    ),
                    recommendation="Add the component to the BOM or explicitly exclude it from assembly output.",
                    confidence=0.97,
                    source_type=FindingSourceType.deterministic,
                    evidence=FindingEvidence(
                        refs=[component.reference],
                        sheet_paths=[component.source_sheet] if component.source_sheet else [],
                        notes=[f"BOM source: {bom.source_path}"],
                    ),
                )
            )
        return findings


@dataclass(slots=True)
class BOMSourcingRule:
    name: str = "bom_sourcing"

    def evaluate(
        self,
        schematic: ParsedSchematic,
        *,
        bom: BomDocument | None = None,
        project_constraints: ProjectConstraints | None = None,
    ) -> list[Finding]:
        if bom is None:
            return []

        findings: list[Finding] = []
        component_lookup = {
            component.reference.upper(): component
            for component in schematic.components
        }
        for item in bom.items:
            active_refs = [
                ref
                for ref in item.refs
                if ref.upper() in component_lookup
                and _is_active_component(component_lookup[ref.upper()])
            ]
            if not active_refs:
                continue
            evidence = FindingEvidence(
                refs=active_refs,
                notes=[f"BOM source: {bom.source_path}"],
            )
            if not item.mpn:
                findings.append(
                    Finding(
                        severity=Severity.warning,
                        category=FindingCategory.bom,
                        component_ref=active_refs[0],
                        title="BOM item missing manufacturer part number",
                        description=(
                            f"BOM row for {', '.join(active_refs)} has no manufacturer part number."
                        ),
                        recommendation="Populate the MPN so sourcing and lifecycle checks can run reliably.",
                        confidence=0.96,
                        source_type=FindingSourceType.deterministic,
                        evidence=evidence,
                    )
                )
            if item.footprint:
                mismatched = [
                    ref for ref in active_refs
                    if component_lookup[ref.upper()].footprint
                    and component_lookup[ref.upper()].footprint != item.footprint
                ]
                if mismatched:
                    findings.append(
                        Finding(
                            severity=Severity.warning,
                            category=FindingCategory.bom,
                            component_ref=mismatched[0],
                            title="BOM footprint mismatch",
                            description=(
                                f"BOM footprint '{item.footprint}' does not match schematic footprint "
                                f"for {', '.join(mismatched)}."
                            ),
                            recommendation="Align BOM package metadata with the schematic footprint before release.",
                            confidence=0.9,
                            source_type=FindingSourceType.deterministic,
                            evidence=FindingEvidence(
                                refs=mismatched,
                                notes=[f"BOM source: {bom.source_path}"],
                            ),
                        )
                    )
        return findings


def _evaluate_condition(
    condition: RulePackMatchCondition,
    component: ParsedComponent,
    connected_nets: list[str],
) -> bool:
    """Evaluate a single match condition against a component."""
    field_val = condition.field
    op = condition.operator
    target = condition.value

    if field_val == "ref_prefix":
        subject = component.reference
    elif field_val == "value_contains":
        subject = component.value
    elif field_val == "net_contains":
        # Any connected net matching is sufficient.
        return any(
            _apply_operator(op, net_name, target)
            for net_name in connected_nets
        )
    elif field_val == "lib_id_contains":
        subject = component.lib_id
    else:
        return False

    return _apply_operator(op, subject, target)


def _apply_operator(op: str, subject: str, target: str) -> bool:
    """Apply a string operator (case-insensitive)."""
    s = subject.lower()
    t = target.lower()
    if op == "equals":
        return s == t
    if op == "contains":
        return t in s
    if op == "not_contains":
        return t not in s
    if op == "starts_with":
        return s.startswith(t)
    return False


def _connected_nets_for_component(component: ParsedComponent) -> list[str]:
    """Return the list of net names connected to a component's pins."""
    return [
        pin.connected_net
        for pin in component.pins
        if pin.connected_net
    ]


def _severity_from_string(raw: str) -> Severity:
    """Convert a raw severity string to the enum, defaulting to warning."""
    try:
        return Severity(raw.lower())
    except ValueError:
        return Severity.warning


def _category_from_string(raw: str) -> FindingCategory:
    """Convert a raw category string to the enum, defaulting to connectivity."""
    try:
        return FindingCategory(raw.lower())
    except ValueError:
        return FindingCategory.connectivity


@dataclass(slots=True)
class CustomRulePackEvaluator:
    """Evaluates all rules in a single CustomRulePack against the schematic.

    Implements the DeterministicRule protocol so it can slot into the engine.
    """

    pack: CustomRulePack
    name: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            self.name = f"custom_pack:{self.pack.name}"

    def evaluate(
        self,
        schematic: ParsedSchematic,
        *,
        bom: BomDocument | None = None,
        project_constraints: ProjectConstraints | None = None,
    ) -> list[Finding]:
        findings: list[Finding] = []
        for rule_def in self.pack.rules:
            findings.extend(self._evaluate_rule(rule_def, schematic))
        return findings

    def _evaluate_rule(
        self,
        rule_def: CustomRuleDefinition,
        schematic: ParsedSchematic,
    ) -> list[Finding]:
        findings: list[Finding] = []
        for component in schematic.components:
            if self._matches(rule_def, component):
                findings.append(self._build_finding(rule_def, component))
        return findings

    def _matches(
        self,
        rule_def: CustomRuleDefinition,
        component: ParsedComponent,
    ) -> bool:
        """All conditions must match for the rule to fire (AND logic)."""
        if not rule_def.conditions:
            return False
        nets = _connected_nets_for_component(component)
        return all(
            _evaluate_condition(cond, component, nets)
            for cond in rule_def.conditions
        )

    def _build_finding(
        self,
        rule_def: CustomRuleDefinition,
        component: ParsedComponent,
    ) -> Finding:
        notes = [
            f"Rule pack: {self.pack.name}",
            f"Rule ID: {rule_def.id}",
        ]
        if rule_def.notes:
            notes.append(rule_def.notes)

        return Finding(
            severity=_severity_from_string(rule_def.severity),
            category=_category_from_string(rule_def.category),
            component_ref=component.reference,
            title=rule_def.title,
            description=(
                f"Custom rule '{rule_def.id}' matched component {component.reference}."
            ),
            recommendation=rule_def.remediation,
            confidence=1.0,
            source_type=FindingSourceType.custom_rule,
            evidence=FindingEvidence(
                refs=[component.reference],
                sheet_paths=[component.source_sheet] if component.source_sheet else [],
                notes=notes,
            ),
        )


@dataclass(slots=True)
class DeterministicRuleEngine:
    """Small coordinator for deterministic review rules."""

    rules: tuple[DeterministicRule, ...] = ()

    def evaluate(
        self,
        schematic: ParsedSchematic,
        *,
        bom: BomDocument | None = None,
        project_constraints: ProjectConstraints | None = None,
    ) -> list[Finding]:
        findings: list[Finding] = []
        for rule in self.rules:
            findings.extend(
                rule.evaluate(
                    schematic,
                    bom=bom,
                    project_constraints=project_constraints,
                )
            )
        return findings


def resolve_deterministic_checks_enabled(
    override: bool | None = None,
) -> bool:
    """Resolve whether deterministic checks should run."""
    if override is not None:
        return override

    raw = os.environ.get(_RULES_ENV_VAR, "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


_BUILTIN_RULES: tuple[DeterministicRule, ...] = (
    PowerConnectivityRule(),
    DecouplingPresenceRule(),
    I2CBusPullupRule(),
    LibraryHygieneRule(),
    BOMCoverageRule(),
    BOMSourcingRule(),
)


def _build_rules_with_custom_packs(
    custom_rule_packs: list[CustomRulePack] | None,
) -> tuple[DeterministicRule, ...]:
    """Merge built-in rules with custom rule packs.

    * additive=True packs append custom evaluators after built-ins.
    * additive=False packs replace built-ins entirely.
    """
    if not custom_rule_packs:
        return _BUILTIN_RULES

    # Check if any pack requests override (additive=False).
    has_override = any(not pack.additive for pack in custom_rule_packs)
    custom_evaluators: tuple[DeterministicRule, ...] = tuple(
        CustomRulePackEvaluator(pack=pack) for pack in custom_rule_packs
    )

    if has_override:
        logger.info(
            "Custom rule packs with additive=False detected; built-in rules replaced"
        )
        return custom_evaluators

    return _BUILTIN_RULES + custom_evaluators


def run_deterministic_checks(
    schematic: ParsedSchematic,
    enabled: bool | None = None,
    engine: DeterministicRuleEngine | None = None,
    bom: BomDocument | None = None,
    project_constraints: ProjectConstraints | None = None,
    custom_rule_packs: list[CustomRulePack] | None = None,
) -> list[Finding]:
    """Run deterministic schematic checks without provider access."""
    if not resolve_deterministic_checks_enabled(enabled):
        return []

    resolved_engine = engine or DeterministicRuleEngine(
        rules=_build_rules_with_custom_packs(custom_rule_packs),
    )
    return resolved_engine.evaluate(
        schematic,
        bom=bom,
        project_constraints=project_constraints,
    )
