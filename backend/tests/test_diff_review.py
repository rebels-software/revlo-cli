"""Tests for schematic diff foundations."""

from __future__ import annotations

from unittest.mock import patch

from revlo.diff_review import compare_schematic_paths, compare_schematics
from revlo.parser.models import (
    ParsedComponent,
    ParsedNet,
    ParsedSchematic,
    PinConnection,
    TitleBlockInfo,
)


def _make_component(
    reference: str,
    *,
    value: str = "",
    footprint: str = "",
    properties: dict[str, str] | None = None,
) -> ParsedComponent:
    return ParsedComponent(
        reference=reference,
        value=value,
        lib_id="Device:Part",
        footprint=footprint,
        properties=properties or {},
    )


def _make_net(
    name: str,
    *,
    pins: list[PinConnection] | None = None,
    labels: list[str] | None = None,
    is_power: bool = False,
) -> ParsedNet:
    return ParsedNet(
        name=name,
        pins=pins or [],
        labels=labels or [],
        is_power=is_power,
    )


def test_compare_schematics_tracks_added_removed_and_changed_components():
    before = ParsedSchematic(
        components=[
            _make_component("U1", value="STM32F103", footprint="LQFP-48"),
            _make_component("R1", value="10k"),
        ],
        title_block=TitleBlockInfo(title="Before"),
    )
    after = ParsedSchematic(
        components=[
            _make_component("U1", value="STM32F103C8T6", footprint="LQFP-48"),
            _make_component("C1", value="100nF"),
        ],
        title_block=TitleBlockInfo(title="After"),
    )

    diff = compare_schematics(before, after, before_name="before", after_name="after")

    assert diff.before_name == "before"
    assert diff.after_name == "after"
    assert diff.added_components == ["C1"]
    assert diff.removed_components == ["R1"]
    assert len(diff.changed_components) == 1
    assert diff.changed_components[0].reference == "U1"
    assert diff.changed_components[0].changed_fields == ["value"]


def test_compare_schematics_tracks_net_changes():
    before = ParsedSchematic(
        nets=[
            _make_net(
                "3V3",
                pins=[PinConnection(component_ref="U1", pin_number="1", pin_name="VDD")],
                labels=["3V3"],
                is_power=True,
            ),
            _make_net("NRST"),
        ]
    )
    after = ParsedSchematic(
        nets=[
            _make_net(
                "3V3",
                pins=[
                    PinConnection(component_ref="U1", pin_number="1", pin_name="VDD"),
                    PinConnection(component_ref="C1", pin_number="1", pin_name="1"),
                ],
                labels=["3V3", "+3V3"],
                is_power=True,
            ),
            _make_net("USB_D+"),
        ]
    )

    diff = compare_schematics(before, after)

    assert diff.added_nets == ["USB_D+"]
    assert diff.removed_nets == ["NRST"]
    assert len(diff.changed_nets) == 1
    net = diff.changed_nets[0]
    assert net.name == "3V3"
    assert net.added_pins == ["C1:1:1"]
    assert net.added_labels == ["+3V3"]


def test_compare_schematics_reports_no_changes_gracefully():
    schematic = ParsedSchematic(
        components=[_make_component("U1", value="STM32F103")],
        nets=[_make_net("3V3")],
    )

    diff = compare_schematics(schematic, schematic)

    assert diff.summary == (
        "0 added components, 0 removed components, 0 changed components, "
        "0 added nets, 0 removed nets, 0 changed nets"
    )
    assert diff.notes == ["No schematic changes detected."]


def test_compare_schematic_paths_parses_both_inputs():
    before = ParsedSchematic(title_block=TitleBlockInfo(title="Before"))
    after = ParsedSchematic(title_block=TitleBlockInfo(title="After"))

    with patch(
        "revlo.diff_review.parse_schematic",
        side_effect=[before, after],
    ) as mock_parse:
        diff = compare_schematic_paths("old.kicad_sch", "new.kicad_sch")

    assert mock_parse.call_count == 2
    assert diff.before_name == "old.kicad_sch"
    assert diff.after_name == "new.kicad_sch"
