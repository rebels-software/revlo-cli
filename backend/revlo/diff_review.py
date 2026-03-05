"""Foundation-level schematic diff helpers for Revlo."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, computed_field

from revlo.parser import parse_schematic
from revlo.parser.models import ParsedComponent, ParsedNet, ParsedSchematic
from revlo.reviewer.models import FindingChangeStatus, ReviewReport


class ChangedComponent(BaseModel):
    """One component that changed between two schematic states."""

    reference: str
    changed_fields: list[str] = Field(default_factory=list)
    before_value: str = ""
    after_value: str = ""
    before_footprint: str = ""
    after_footprint: str = ""
    before_properties: dict[str, str] = Field(default_factory=dict)
    after_properties: dict[str, str] = Field(default_factory=dict)


class ChangedNet(BaseModel):
    """One net that changed between two schematic states."""

    name: str
    added_pins: list[str] = Field(default_factory=list)
    removed_pins: list[str] = Field(default_factory=list)
    added_labels: list[str] = Field(default_factory=list)
    removed_labels: list[str] = Field(default_factory=list)
    power_changed: bool = False


class SchematicDiffSummary(BaseModel):
    """Structured, graceful summary of schematic changes."""

    before_name: str = ""
    after_name: str = ""
    added_components: list[str] = Field(default_factory=list)
    removed_components: list[str] = Field(default_factory=list)
    changed_components: list[ChangedComponent] = Field(default_factory=list)
    added_nets: list[str] = Field(default_factory=list)
    removed_nets: list[str] = Field(default_factory=list)
    changed_nets: list[ChangedNet] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def summary(self) -> str:
        parts = [
            f"{len(self.added_components)} added components",
            f"{len(self.removed_components)} removed components",
            f"{len(self.changed_components)} changed components",
            f"{len(self.added_nets)} added nets",
            f"{len(self.removed_nets)} removed nets",
            f"{len(self.changed_nets)} changed nets",
        ]
        return ", ".join(parts)


def compare_schematic_paths(
    before_path: str | Path,
    after_path: str | Path,
) -> SchematicDiffSummary:
    """Parse two schematic files and compare them."""
    before = parse_schematic(str(before_path))
    after = parse_schematic(str(after_path))
    return compare_schematics(
        before,
        after,
        before_name=Path(before_path).name,
        after_name=Path(after_path).name,
    )


def compare_schematics(
    before: ParsedSchematic,
    after: ParsedSchematic,
    *,
    before_name: str = "",
    after_name: str = "",
) -> SchematicDiffSummary:
    """Compare two parsed schematics and summarize the changes."""
    before_components = {component.reference: component for component in before.components}
    after_components = {component.reference: component for component in after.components}
    before_nets = {net.name: net for net in before.nets}
    after_nets = {net.name: net for net in after.nets}

    added_components = sorted(set(after_components) - set(before_components))
    removed_components = sorted(set(before_components) - set(after_components))
    added_nets = sorted(set(after_nets) - set(before_nets))
    removed_nets = sorted(set(before_nets) - set(after_nets))

    changed_components: list[ChangedComponent] = []
    for ref in sorted(set(before_components) & set(after_components)):
        component_change = _compare_component(before_components[ref], after_components[ref])
        if component_change is not None:
            changed_components.append(component_change)

    changed_nets: list[ChangedNet] = []
    for name in sorted(set(before_nets) & set(after_nets)):
        net_change = _compare_net(before_nets[name], after_nets[name])
        if net_change is not None:
            changed_nets.append(net_change)

    notes: list[str] = []
    if not any([
        added_components,
        removed_components,
        changed_components,
        added_nets,
        removed_nets,
        changed_nets,
    ]):
        notes.append("No schematic changes detected.")

    return SchematicDiffSummary(
        before_name=before_name,
        after_name=after_name,
        added_components=added_components,
        removed_components=removed_components,
        changed_components=changed_components,
        added_nets=added_nets,
        removed_nets=removed_nets,
        changed_nets=changed_nets,
        notes=notes,
    )


def _compare_component(
    before: ParsedComponent,
    after: ParsedComponent,
) -> ChangedComponent | None:
    changed_fields: list[str] = []
    if before.value != after.value:
        changed_fields.append("value")
    if before.footprint != after.footprint:
        changed_fields.append("footprint")
    if before.lib_id != after.lib_id:
        changed_fields.append("lib_id")
    if before.source_sheet != after.source_sheet:
        changed_fields.append("source_sheet")
    if before.properties != after.properties:
        changed_fields.append("properties")

    if not changed_fields:
        return None

    return ChangedComponent(
        reference=before.reference,
        changed_fields=changed_fields,
        before_value=before.value,
        after_value=after.value,
        before_footprint=before.footprint,
        after_footprint=after.footprint,
        before_properties=dict(before.properties),
        after_properties=dict(after.properties),
    )


def _compare_net(before: ParsedNet, after: ParsedNet) -> ChangedNet | None:
    before_pins = _pin_set(before)
    after_pins = _pin_set(after)
    before_labels = set(before.labels)
    after_labels = set(after.labels)

    added_pins = sorted(after_pins - before_pins)
    removed_pins = sorted(before_pins - after_pins)
    added_labels = sorted(after_labels - before_labels)
    removed_labels = sorted(before_labels - after_labels)
    power_changed = before.is_power != after.is_power

    if not any([added_pins, removed_pins, added_labels, removed_labels, power_changed]):
        return None

    return ChangedNet(
        name=before.name,
        added_pins=added_pins,
        removed_pins=removed_pins,
        added_labels=added_labels,
        removed_labels=removed_labels,
        power_changed=power_changed,
    )


def _pin_set(net: ParsedNet) -> set[str]:
    return {
        f"{pin.component_ref}:{pin.pin_number}:{pin.pin_name}"
        for pin in net.pins
    }


def tag_change_driven_findings(
    report: ReviewReport,
    diff: SchematicDiffSummary,
) -> ReviewReport:
    """Tag findings whose refs or nets intersect with schematic changes."""
    changed_refs = set(diff.added_components)
    changed_refs.update(diff.removed_components)
    changed_refs.update(change.reference for change in diff.changed_components)

    changed_nets = set(diff.added_nets)
    changed_nets.update(diff.removed_nets)
    changed_nets.update(change.name for change in diff.changed_nets)

    for finding in report.findings:
        refs = {finding.component_ref, *finding.evidence.refs}
        nets = set(finding.evidence.nets)
        if refs & changed_refs or nets & changed_nets:
            finding.change_status = FindingChangeStatus.change_driven
        else:
            finding.change_status = FindingChangeStatus.unchanged_context
    return report
