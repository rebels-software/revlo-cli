"""Test suite for schematic chunker (US-008)."""

from revlo.parser.models import (
    ParsedComponent,
    ParsedNet,
    ParsedPin,
    ParsedSchematic,
    PinConnection,
)
from revlo.reviewer.chunker import ReviewChunk, chunk_schematic


class TestReviewChunkModel:
    def test_defaults_and_required(self):
        chunk = ReviewChunk(chunk_type="ic_context", label="U1 - STM32")
        assert chunk.chunk_type == "ic_context"
        assert chunk.label == "U1 - STM32"
        assert chunk.components == []
        assert chunk.nets == []
        assert chunk.unconnected_pins == []

    def test_model_dump(self):
        comp = ParsedComponent(reference="U1", value="STM32", lib_id="MCU:STM32")
        chunk = ReviewChunk(chunk_type="power_rail", label="Power Rail: VCC",
                            components=[comp])
        data = chunk.model_dump()
        assert data["chunk_type"] == "power_rail"
        assert len(data["components"]) == 1


class TestChunkSchematicEmpty:
    def test_empty_schematic(self):
        assert chunk_schematic(ParsedSchematic()) == []

    def test_passives_only_no_power(self):
        s = ParsedSchematic(
            components=[ParsedComponent(reference="R1", value="10k", lib_id="Device:R")],
            nets=[ParsedNet(name="Net1", is_power=False)],
        )
        assert chunk_schematic(s) == []


class TestICContextChunks:
    def test_single_ic_with_passive(self):
        ic = ParsedComponent(reference="U1", value="STM32", lib_id="MCU:STM32",
                             pins=[ParsedPin(number="1", name="VCC", connected_net="Net1")])
        cap = ParsedComponent(reference="C1", value="100n", lib_id="Device:C",
                              pins=[ParsedPin(number="1", name="1", connected_net="Net1")])
        net = ParsedNet(name="Net1", pins=[
            PinConnection(component_ref="U1", pin_number="1"),
            PinConnection(component_ref="C1", pin_number="1"),
        ])
        chunks = chunk_schematic(ParsedSchematic(components=[ic, cap], nets=[net]))
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "ic_context"
        assert chunks[0].label == "U1 - STM32"
        refs = [c.reference for c in chunks[0].components]
        assert "U1" in refs and "C1" in refs

    def test_excludes_power_symbols_and_other_ics(self):
        ic1 = ParsedComponent(reference="U1", value="STM32", lib_id="MCU:STM32",
                              pins=[ParsedPin(number="1", name="VCC", connected_net="VCC")])
        ic2 = ParsedComponent(reference="U2", value="FT232", lib_id="Interface:FT232",
                              pins=[ParsedPin(number="1", name="RX", connected_net="VCC")])
        pwr = ParsedComponent(reference="#PWR01", value="VCC", lib_id="power:VCC",
                              pins=[ParsedPin(number="1", name="1", connected_net="VCC")])
        net = ParsedNet(name="VCC", is_power=True, pins=[
            PinConnection(component_ref="U1", pin_number="1"),
            PinConnection(component_ref="U2", pin_number="1"),
            PinConnection(component_ref="#PWR01", pin_number="1"),
        ])
        s = ParsedSchematic(components=[ic1, ic2], power_symbols=[pwr], nets=[net])
        chunks = chunk_schematic(s)
        ic_chunks = [c for c in chunks if c.chunk_type == "ic_context"]
        assert len(ic_chunks) == 2
        for ch in ic_chunks:
            refs = {c.reference for c in ch.components}
            assert "#PWR01" not in refs
            # Each IC chunk should contain only its own IC, not the other
            assert len([r for r in refs if r.startswith("U")]) == 1

    def test_unconnected_pins_included(self):
        ic = ParsedComponent(reference="U1", value="STM32", lib_id="MCU:STM32",
                             pins=[ParsedPin(number="1", name="VCC", connected_net="Net1"),
                                   ParsedPin(number="2", name="NC", connected_net=None)])
        net = ParsedNet(name="Net1", pins=[PinConnection(component_ref="U1", pin_number="1")])
        uc = [PinConnection(component_ref="U1", pin_number="2", pin_name="NC")]
        chunks = chunk_schematic(ParsedSchematic(components=[ic], nets=[net], unconnected_pins=uc))
        assert len(chunks[0].unconnected_pins) == 1


class TestPowerRailChunks:
    def test_single_power_net(self):
        cap = ParsedComponent(reference="C1", value="100n", lib_id="Device:C",
                              pins=[ParsedPin(number="1", name="1", connected_net="VCC")])
        net = ParsedNet(name="VCC", is_power=True,
                        pins=[PinConnection(component_ref="C1", pin_number="1")])
        chunks = chunk_schematic(ParsedSchematic(components=[cap], nets=[net]))
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "power_rail"
        assert chunks[0].label == "Power Rail: VCC"

    def test_multiple_power_nets_sorted(self):
        cap1 = ParsedComponent(reference="C1", value="100n", lib_id="Device:C",
                               pins=[ParsedPin(number="1", name="1", connected_net="VCC")])
        cap2 = ParsedComponent(reference="C2", value="100n", lib_id="Device:C",
                               pins=[ParsedPin(number="1", name="1", connected_net="GND")])
        vcc = ParsedNet(name="VCC", is_power=True,
                        pins=[PinConnection(component_ref="C1", pin_number="1")])
        gnd = ParsedNet(name="GND", is_power=True,
                        pins=[PinConnection(component_ref="C2", pin_number="1")])
        chunks = chunk_schematic(ParsedSchematic(components=[cap1, cap2], nets=[vcc, gnd]))
        power_chunks = [c for c in chunks if c.chunk_type == "power_rail"]
        assert len(power_chunks) == 2
        assert power_chunks[0].label == "Power Rail: GND"
        assert power_chunks[1].label == "Power Rail: VCC"


class TestChunkOrdering:
    def test_ic_chunks_before_power_chunks(self):
        ic = ParsedComponent(reference="U1", value="STM32", lib_id="MCU:STM32",
                             pins=[ParsedPin(number="1", name="VCC", connected_net="VCC")])
        cap = ParsedComponent(reference="C1", value="100n", lib_id="Device:C",
                              pins=[ParsedPin(number="1", name="1", connected_net="VCC")])
        net = ParsedNet(name="VCC", is_power=True, pins=[
            PinConnection(component_ref="U1", pin_number="1"),
            PinConnection(component_ref="C1", pin_number="1"),
        ])
        chunks = chunk_schematic(ParsedSchematic(components=[ic, cap], nets=[net]))
        assert len(chunks) == 2
        assert chunks[0].chunk_type == "ic_context"
        assert chunks[1].chunk_type == "power_rail"


class TestChunkOverlap:
    def test_passive_in_both_ic_and_power(self):
        ic = ParsedComponent(reference="U1", value="STM32", lib_id="MCU:STM32",
                             pins=[ParsedPin(number="1", name="VCC", connected_net="VCC")])
        cap = ParsedComponent(reference="C1", value="100n", lib_id="Device:C",
                              pins=[ParsedPin(number="1", name="1", connected_net="VCC")])
        net = ParsedNet(name="VCC", is_power=True, pins=[
            PinConnection(component_ref="U1", pin_number="1"),
            PinConnection(component_ref="C1", pin_number="1"),
        ])
        chunks = chunk_schematic(ParsedSchematic(components=[ic, cap], nets=[net]))
        ic_refs = {c.reference for c in chunks[0].components}
        power_refs = {c.reference for c in chunks[1].components}
        assert "C1" in ic_refs and "C1" in power_refs


class TestImportFromReviewer:
    def test_imports(self):
        from revlo.reviewer import ReviewChunk as RC, chunk_schematic as cs
        assert callable(cs)
        assert RC(chunk_type="ic_context", label="test").chunk_type == "ic_context"
