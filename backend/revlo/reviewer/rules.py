"""Deterministic schematic rule-engine scaffold."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from revlo.parser.models import ParsedComponent, ParsedNet, ParsedPin, ParsedSchematic
from revlo.reviewer.models import (
    Finding,
    FindingCategory,
    FindingEvidence,
    FindingSourceType,
    Severity,
)

_RULES_ENV_VAR = "REVLO_ENABLE_RULES"


class DeterministicRule(Protocol):
    """Protocol for future deterministic schematic checks."""

    name: str

    def evaluate(self, schematic: ParsedSchematic) -> list[Finding]:
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


@dataclass(slots=True)
class PowerConnectivityRule:
    name: str = "power_connectivity"

    def evaluate(self, schematic: ParsedSchematic) -> list[Finding]:
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
                            notes=[f"Power pin electrical type: {pin.electrical_type}"],
                        ),
                    )
                )
        return findings


@dataclass(slots=True)
class DecouplingPresenceRule:
    name: str = "decoupling_presence"

    def evaluate(self, schematic: ParsedSchematic) -> list[Finding]:
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
                        ),
                    )
                )
        return findings


@dataclass(slots=True)
class I2CBusPullupRule:
    name: str = "i2c_pullups"

    def evaluate(self, schematic: ParsedSchematic) -> list[Finding]:
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
                    ),
                )
            )
        return findings


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

    resolved_engine = engine or DeterministicRuleEngine(
        rules=(
            PowerConnectivityRule(),
            DecouplingPresenceRule(),
            I2CBusPullupRule(),
        )
    )
    return resolved_engine.evaluate(schematic)
