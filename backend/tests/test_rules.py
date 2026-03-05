"""Tests for deterministic rule-engine scaffolding."""

from __future__ import annotations

from dataclasses import dataclass

from revlo.parser.models import (
    ParsedComponent,
    ParsedNet,
    ParsedPin,
    ParsedSchematic,
    PinConnection,
    TitleBlockInfo,
)
from revlo.reviewer.models import Finding
from revlo.reviewer.rules import (
    DecouplingPresenceRule,
    DeterministicRuleEngine,
    I2CBusPullupRule,
    LibraryHygieneRule,
    PowerConnectivityRule,
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


def _make_rule_test_schematic() -> ParsedSchematic:
    return ParsedSchematic(
        components=[
            ParsedComponent(
                reference="U1",
                value="MCU",
                lib_id="MCU:TEST",
                source_sheet="/MCU",
                pins=[
                    ParsedPin(number="1", name="VDD", electrical_type="power_in", connected_net="+3V3"),
                    ParsedPin(number="2", name="SCL", electrical_type="bidirectional", connected_net="I2C_SCL"),
                    ParsedPin(number="3", name="SDA", electrical_type="bidirectional", connected_net="I2C_SDA"),
                ],
            ),
            ParsedComponent(
                reference="U2",
                value="Sensor",
                lib_id="Sensor:TEST",
                source_sheet="/Sensors",
                pins=[
                    ParsedPin(number="1", name="VIN", electrical_type="power_in"),
                ],
            ),
        ],
        nets=[
            ParsedNet(
                name="+3V3",
                is_power=True,
                pins=[
                    PinConnection(component_ref="U1", pin_number="1", pin_name="VDD"),
                ],
            ),
            ParsedNet(
                name="I2C_SCL",
                pins=[
                    PinConnection(component_ref="U1", pin_number="2", pin_name="SCL"),
                ],
            ),
            ParsedNet(
                name="I2C_SDA",
                pins=[
                    PinConnection(component_ref="U1", pin_number="3", pin_name="SDA"),
                ],
            ),
        ],
        unconnected_pins=[
            PinConnection(component_ref="U2", pin_number="1", pin_name="VIN"),
        ],
        title_block=TitleBlockInfo(title="Rule Test"),
    )


def test_power_connectivity_rule_reports_unconnected_power_pins():
    findings = PowerConnectivityRule().evaluate(_make_rule_test_schematic())

    assert len(findings) == 1
    assert findings[0].category.value == "power"
    assert findings[0].component_ref == "U2"
    assert findings[0].evidence.refs == ["U2"]


def test_decoupling_rule_reports_missing_capacitor_on_power_rail():
    findings = DecouplingPresenceRule().evaluate(_make_rule_test_schematic())

    assert len(findings) == 1
    assert findings[0].category.value == "decoupling"
    assert findings[0].component_ref == "U1"
    assert findings[0].evidence.nets == ["+3V3"]


def test_i2c_pullup_rule_reports_missing_pullups():
    findings = I2CBusPullupRule().evaluate(_make_rule_test_schematic())

    assert len(findings) == 2
    assert {finding.evidence.nets[0] for finding in findings} == {"I2C_SCL", "I2C_SDA"}


def test_run_deterministic_checks_includes_builtin_findings():
    findings = run_deterministic_checks(_make_rule_test_schematic(), enabled=True)

    categories = {finding.category.value for finding in findings}
    assert "power" in categories
    assert "decoupling" in categories
    assert "pull_up" in categories


def test_library_hygiene_rule_reports_duplicate_refs_and_missing_fields():
    schematic = ParsedSchematic(
        components=[
            ParsedComponent(reference="U1", value="", lib_id="MCU:TEST", footprint=""),
            ParsedComponent(reference="U1", value="Regulator", lib_id="Reg:TEST", footprint="SOT-223"),
        ],
        title_block=TitleBlockInfo(title="Rule Test"),
    )

    findings = LibraryHygieneRule().evaluate(schematic)

    titles = {finding.title for finding in findings}
    categories = {finding.category.value for finding in findings}
    assert "library_hygiene" in categories
    assert "Duplicate reference designator" in titles
    assert "Missing component value" in titles
    assert "Missing footprint" in titles
