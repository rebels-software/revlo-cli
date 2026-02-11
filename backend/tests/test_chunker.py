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
    """Test ReviewChunk Pydantic model (US-008 AC2)."""

    def test_required_fields(self):
        """Test that ReviewChunk has all required fields."""
        chunk = ReviewChunk(chunk_type="ic_context", label="U1 - STM32")
        assert chunk.chunk_type == "ic_context"
        assert chunk.label == "U1 - STM32"
        assert chunk.components == []  # Default
        assert chunk.nets == []  # Default
        assert chunk.unconnected_pins == []  # Default

    def test_all_fields_populated(self):
        """Test ReviewChunk with all fields populated."""
        comp = ParsedComponent(reference="U1", value="STM32", lib_id="MCU:STM32")
        net = ParsedNet(name="VCC", is_power=True)
        uc_pin = PinConnection(component_ref="U1", pin_number="1", pin_name="VCC")

        chunk = ReviewChunk(
            chunk_type="ic_context",
            label="U1 - STM32",
            components=[comp],
            nets=[net],
            unconnected_pins=[uc_pin],
        )

        assert chunk.chunk_type == "ic_context"
        assert chunk.label == "U1 - STM32"
        assert len(chunk.components) == 1
        assert chunk.components[0].reference == "U1"
        assert len(chunk.nets) == 1
        assert chunk.nets[0].name == "VCC"
        assert len(chunk.unconnected_pins) == 1
        assert chunk.unconnected_pins[0].component_ref == "U1"

    def test_model_dump(self):
        """Test .model_dump() returns dict for JSON serialization."""
        comp = ParsedComponent(reference="U1", value="STM32", lib_id="MCU:STM32")
        chunk = ReviewChunk(
            chunk_type="power_rail",
            label="Power Rail: VCC",
            components=[comp],
        )
        data = chunk.model_dump()
        assert isinstance(data, dict)
        assert data["chunk_type"] == "power_rail"
        assert data["label"] == "Power Rail: VCC"
        assert len(data["components"]) == 1
        assert data["components"][0]["reference"] == "U1"


class TestChunkSchematicEmpty:
    """Test chunk_schematic with empty/minimal schematics."""

    def test_empty_schematic(self):
        """Test that an empty schematic produces an empty list of chunks."""
        schematic = ParsedSchematic()
        chunks = chunk_schematic(schematic)
        assert chunks == []

    def test_no_ics_no_power_nets(self):
        """Test schematic with only passives and no power nets produces no chunks."""
        schematic = ParsedSchematic(
            components=[
                ParsedComponent(reference="R1", value="10k", lib_id="Device:R"),
                ParsedComponent(reference="C1", value="100n", lib_id="Device:C"),
            ],
            nets=[
                ParsedNet(name="Net1", is_power=False),
            ],
        )
        chunks = chunk_schematic(schematic)
        assert chunks == []

    def test_no_ics_with_power_net(self):
        """Test schematic with no ICs but power nets produces only power_rail chunks."""
        schematic = ParsedSchematic(
            components=[
                ParsedComponent(reference="C1", value="100n", lib_id="Device:C"),
            ],
            nets=[
                ParsedNet(
                    name="VCC",
                    is_power=True,
                    pins=[PinConnection(component_ref="C1", pin_number="1")],
                ),
            ],
        )
        chunks = chunk_schematic(schematic)
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "power_rail"
        assert chunks[0].label == "Power Rail: VCC"


class TestICContextChunks:
    """Test IC-context chunk generation (US-008 AC4)."""

    def test_single_ic_no_passives(self):
        """Test single IC with no connected passives produces one ic_context chunk."""
        ic = ParsedComponent(
            reference="U1",
            value="STM32",
            lib_id="MCU:STM32",
            pins=[
                ParsedPin(number="1", name="VCC", connected_net=None),
            ],
        )
        schematic = ParsedSchematic(components=[ic])
        chunks = chunk_schematic(schematic)

        assert len(chunks) == 1
        assert chunks[0].chunk_type == "ic_context"
        assert chunks[0].label == "U1 - STM32"
        assert len(chunks[0].components) == 1
        assert chunks[0].components[0].reference == "U1"

    def test_ic_with_single_passive(self):
        """Test IC connected to a passive via a net includes both in chunk."""
        ic = ParsedComponent(
            reference="U1",
            value="STM32",
            lib_id="MCU:STM32",
            pins=[
                ParsedPin(number="1", name="VCC", connected_net="Net1"),
            ],
        )
        cap = ParsedComponent(
            reference="C1",
            value="100n",
            lib_id="Device:C",
            pins=[
                ParsedPin(number="1", name="1", connected_net="Net1"),
            ],
        )
        net = ParsedNet(
            name="Net1",
            pins=[
                PinConnection(component_ref="U1", pin_number="1"),
                PinConnection(component_ref="C1", pin_number="1"),
            ],
        )
        schematic = ParsedSchematic(components=[ic, cap], nets=[net])
        chunks = chunk_schematic(schematic)

        assert len(chunks) == 1
        chunk = chunks[0]
        assert chunk.chunk_type == "ic_context"
        assert chunk.label == "U1 - STM32"
        assert len(chunk.components) == 2
        # IC comes first
        assert chunk.components[0].reference == "U1"
        assert chunk.components[1].reference == "C1"
        assert len(chunk.nets) == 1
        assert chunk.nets[0].name == "Net1"

    def test_ic_with_multiple_passives(self):
        """Test IC connected to several passives via different nets."""
        ic = ParsedComponent(
            reference="U1",
            value="STM32",
            lib_id="MCU:STM32",
            pins=[
                ParsedPin(number="1", name="VCC", connected_net="Net1"),
                ParsedPin(number="2", name="GND", connected_net="Net2"),
            ],
        )
        cap1 = ParsedComponent(
            reference="C1",
            value="100n",
            lib_id="Device:C",
            pins=[ParsedPin(number="1", name="1", connected_net="Net1")],
        )
        cap2 = ParsedComponent(
            reference="C2",
            value="1u",
            lib_id="Device:C",
            pins=[ParsedPin(number="1", name="1", connected_net="Net1")],
        )
        res = ParsedComponent(
            reference="R1",
            value="10k",
            lib_id="Device:R",
            pins=[ParsedPin(number="1", name="1", connected_net="Net2")],
        )
        net1 = ParsedNet(
            name="Net1",
            pins=[
                PinConnection(component_ref="U1", pin_number="1"),
                PinConnection(component_ref="C1", pin_number="1"),
                PinConnection(component_ref="C2", pin_number="1"),
            ],
        )
        net2 = ParsedNet(
            name="Net2",
            pins=[
                PinConnection(component_ref="U1", pin_number="2"),
                PinConnection(component_ref="R1", pin_number="1"),
            ],
        )
        schematic = ParsedSchematic(
            components=[ic, cap1, cap2, res], nets=[net1, net2]
        )
        chunks = chunk_schematic(schematic)

        assert len(chunks) == 1
        chunk = chunks[0]
        assert chunk.chunk_type == "ic_context"
        assert chunk.label == "U1 - STM32"
        assert len(chunk.components) == 4
        # IC first, then passives alphabetically
        assert chunk.components[0].reference == "U1"
        assert chunk.components[1].reference == "C1"
        assert chunk.components[2].reference == "C2"
        assert chunk.components[3].reference == "R1"
        # Nets sorted by name
        assert len(chunk.nets) == 2
        assert chunk.nets[0].name == "Net1"
        assert chunk.nets[1].name == "Net2"

    def test_ic_excludes_power_symbols(self):
        """Test that power symbols are excluded from IC passive collection."""
        ic = ParsedComponent(
            reference="U1",
            value="STM32",
            lib_id="MCU:STM32",
            pins=[
                ParsedPin(number="1", name="VCC", connected_net="VCC"),
            ],
        )
        cap = ParsedComponent(
            reference="C1",
            value="100n",
            lib_id="Device:C",
            pins=[ParsedPin(number="1", name="1", connected_net="VCC")],
        )
        power_sym = ParsedComponent(
            reference="#PWR01",
            value="VCC",
            lib_id="power:VCC",
            pins=[ParsedPin(number="1", name="1", connected_net="VCC")],
        )
        net = ParsedNet(
            name="VCC",
            is_power=True,
            pins=[
                PinConnection(component_ref="U1", pin_number="1"),
                PinConnection(component_ref="C1", pin_number="1"),
                PinConnection(component_ref="#PWR01", pin_number="1"),
            ],
        )
        schematic = ParsedSchematic(
            components=[ic, cap],
            power_symbols=[power_sym],
            nets=[net],
        )
        chunks = chunk_schematic(schematic)

        # Should have 1 IC chunk and 1 power rail chunk
        ic_chunks = [c for c in chunks if c.chunk_type == "ic_context"]
        assert len(ic_chunks) == 1
        chunk = ic_chunks[0]
        # Should contain U1 and C1, but NOT #PWR01
        assert len(chunk.components) == 2
        assert chunk.components[0].reference == "U1"
        assert chunk.components[1].reference == "C1"

    def test_ic_excludes_other_ics(self):
        """Test that two ICs sharing a net don't pull each other in as passives."""
        ic1 = ParsedComponent(
            reference="U1",
            value="STM32",
            lib_id="MCU:STM32",
            pins=[ParsedPin(number="1", name="TX", connected_net="UART_TX")],
        )
        ic2 = ParsedComponent(
            reference="U2",
            value="FT232",
            lib_id="Interface:FT232",
            pins=[ParsedPin(number="1", name="RX", connected_net="UART_TX")],
        )
        net = ParsedNet(
            name="UART_TX",
            pins=[
                PinConnection(component_ref="U1", pin_number="1"),
                PinConnection(component_ref="U2", pin_number="1"),
            ],
        )
        schematic = ParsedSchematic(components=[ic1, ic2], nets=[net])
        chunks = chunk_schematic(schematic)

        # Should have 2 IC chunks (one for U1, one for U2)
        assert len(chunks) == 2
        u1_chunk = next(c for c in chunks if c.label.startswith("U1"))
        u2_chunk = next(c for c in chunks if c.label.startswith("U2"))

        # U1 chunk should only contain U1
        assert len(u1_chunk.components) == 1
        assert u1_chunk.components[0].reference == "U1"

        # U2 chunk should only contain U2
        assert len(u2_chunk.components) == 1
        assert u2_chunk.components[0].reference == "U2"

        # Both should have the shared net
        assert u1_chunk.nets[0].name == "UART_TX"
        assert u2_chunk.nets[0].name == "UART_TX"

    def test_ic_with_unconnected_pins(self):
        """Test that unconnected pins for IC and its passives are included."""
        ic = ParsedComponent(
            reference="U1",
            value="STM32",
            lib_id="MCU:STM32",
            pins=[
                ParsedPin(number="1", name="VCC", connected_net="Net1"),
                ParsedPin(number="2", name="NC", connected_net=None),
            ],
        )
        cap = ParsedComponent(
            reference="C1",
            value="100n",
            lib_id="Device:C",
            pins=[
                ParsedPin(number="1", name="1", connected_net="Net1"),
                ParsedPin(number="2", name="2", connected_net=None),
            ],
        )
        net = ParsedNet(
            name="Net1",
            pins=[
                PinConnection(component_ref="U1", pin_number="1"),
                PinConnection(component_ref="C1", pin_number="1"),
            ],
        )
        uc_pins = [
            PinConnection(component_ref="U1", pin_number="2", pin_name="NC"),
            PinConnection(component_ref="C1", pin_number="2", pin_name="2"),
        ]
        schematic = ParsedSchematic(
            components=[ic, cap], nets=[net], unconnected_pins=uc_pins
        )
        chunks = chunk_schematic(schematic)

        assert len(chunks) == 1
        chunk = chunks[0]
        assert len(chunk.unconnected_pins) == 2
        assert chunk.unconnected_pins[0].component_ref == "U1"
        assert chunk.unconnected_pins[1].component_ref == "C1"


class TestPowerRailChunks:
    """Test power rail chunk generation (US-008 AC5)."""

    def test_single_power_net(self):
        """Test single power net produces one power_rail chunk."""
        cap = ParsedComponent(
            reference="C1",
            value="100n",
            lib_id="Device:C",
            pins=[ParsedPin(number="1", name="1", connected_net="VCC")],
        )
        net = ParsedNet(
            name="VCC",
            is_power=True,
            pins=[PinConnection(component_ref="C1", pin_number="1")],
        )
        schematic = ParsedSchematic(components=[cap], nets=[net])
        chunks = chunk_schematic(schematic)

        assert len(chunks) == 1
        chunk = chunks[0]
        assert chunk.chunk_type == "power_rail"
        assert chunk.label == "Power Rail: VCC"
        assert len(chunk.components) == 1
        assert chunk.components[0].reference == "C1"
        assert len(chunk.nets) == 1
        assert chunk.nets[0].name == "VCC"

    def test_multiple_power_nets(self):
        """Test multiple power nets produce multiple power_rail chunks."""
        cap1 = ParsedComponent(
            reference="C1",
            value="100n",
            lib_id="Device:C",
            pins=[ParsedPin(number="1", name="1", connected_net="VCC")],
        )
        cap2 = ParsedComponent(
            reference="C2",
            value="100n",
            lib_id="Device:C",
            pins=[ParsedPin(number="1", name="1", connected_net="GND")],
        )
        vcc_net = ParsedNet(
            name="VCC",
            is_power=True,
            pins=[PinConnection(component_ref="C1", pin_number="1")],
        )
        gnd_net = ParsedNet(
            name="GND",
            is_power=True,
            pins=[PinConnection(component_ref="C2", pin_number="1")],
        )
        schematic = ParsedSchematic(
            components=[cap1, cap2], nets=[vcc_net, gnd_net]
        )
        chunks = chunk_schematic(schematic)

        # Should have 2 power rail chunks
        power_chunks = [c for c in chunks if c.chunk_type == "power_rail"]
        assert len(power_chunks) == 2

        # Chunks are sorted by net name
        assert power_chunks[0].label == "Power Rail: GND"
        assert power_chunks[1].label == "Power Rail: VCC"

    def test_power_rail_with_ic(self):
        """Test power rail chunk includes IC connected to power net."""
        ic = ParsedComponent(
            reference="U1",
            value="STM32",
            lib_id="MCU:STM32",
            pins=[ParsedPin(number="1", name="VCC", connected_net="VCC")],
        )
        cap = ParsedComponent(
            reference="C1",
            value="100n",
            lib_id="Device:C",
            pins=[ParsedPin(number="1", name="1", connected_net="VCC")],
        )
        net = ParsedNet(
            name="VCC",
            is_power=True,
            pins=[
                PinConnection(component_ref="U1", pin_number="1"),
                PinConnection(component_ref="C1", pin_number="1"),
            ],
        )
        schematic = ParsedSchematic(components=[ic, cap], nets=[net])
        chunks = chunk_schematic(schematic)

        # Should have 1 IC chunk and 1 power rail chunk
        power_chunks = [c for c in chunks if c.chunk_type == "power_rail"]
        assert len(power_chunks) == 1
        chunk = power_chunks[0]

        # Should include both IC and capacitor
        assert len(chunk.components) == 2
        # Components sorted alphabetically
        assert chunk.components[0].reference == "C1"
        assert chunk.components[1].reference == "U1"

    def test_power_rail_with_unconnected_pins(self):
        """Test power rail chunk includes unconnected pins from connected components."""
        cap = ParsedComponent(
            reference="C1",
            value="100n",
            lib_id="Device:C",
            pins=[
                ParsedPin(number="1", name="1", connected_net="VCC"),
                ParsedPin(number="2", name="2", connected_net=None),
            ],
        )
        net = ParsedNet(
            name="VCC",
            is_power=True,
            pins=[PinConnection(component_ref="C1", pin_number="1")],
        )
        uc_pins = [PinConnection(component_ref="C1", pin_number="2", pin_name="2")]
        schematic = ParsedSchematic(
            components=[cap], nets=[net], unconnected_pins=uc_pins
        )
        chunks = chunk_schematic(schematic)

        assert len(chunks) == 1
        chunk = chunks[0]
        assert len(chunk.unconnected_pins) == 1
        assert chunk.unconnected_pins[0].component_ref == "C1"


class TestChunkOverlap:
    """Test that chunks intentionally overlap."""

    def test_passive_in_both_ic_and_power_chunks(self):
        """Test that a capacitor connected to both IC and power net appears in both chunks."""
        ic = ParsedComponent(
            reference="U1",
            value="STM32",
            lib_id="MCU:STM32",
            pins=[ParsedPin(number="1", name="VCC", connected_net="VCC")],
        )
        cap = ParsedComponent(
            reference="C1",
            value="100n",
            lib_id="Device:C",
            pins=[ParsedPin(number="1", name="1", connected_net="VCC")],
        )
        net = ParsedNet(
            name="VCC",
            is_power=True,
            pins=[
                PinConnection(component_ref="U1", pin_number="1"),
                PinConnection(component_ref="C1", pin_number="1"),
            ],
        )
        schematic = ParsedSchematic(components=[ic, cap], nets=[net])
        chunks = chunk_schematic(schematic)

        # Should have 1 IC chunk and 1 power rail chunk
        assert len(chunks) == 2
        ic_chunk = next(c for c in chunks if c.chunk_type == "ic_context")
        power_chunk = next(c for c in chunks if c.chunk_type == "power_rail")

        # Both chunks should contain C1
        ic_refs = {c.reference for c in ic_chunk.components}
        power_refs = {c.reference for c in power_chunk.components}
        assert "C1" in ic_refs
        assert "C1" in power_refs


class TestLabelFormat:
    """Test chunk label formatting (US-008 AC4, AC5)."""

    def test_ic_label_format(self):
        """Test IC chunk labels follow format 'reference - value'."""
        ic = ParsedComponent(
            reference="U1", value="STM32F103", lib_id="MCU:STM32"
        )
        schematic = ParsedSchematic(components=[ic])
        chunks = chunk_schematic(schematic)

        assert len(chunks) == 1
        assert chunks[0].label == "U1 - STM32F103"

    def test_power_rail_label_format(self):
        """Test power rail chunk labels follow format 'Power Rail: net_name'."""
        cap = ParsedComponent(
            reference="C1",
            value="100n",
            lib_id="Device:C",
            pins=[ParsedPin(number="1", name="1", connected_net="3V3")],
        )
        net = ParsedNet(
            name="3V3",
            is_power=True,
            pins=[PinConnection(component_ref="C1", pin_number="1")],
        )
        schematic = ParsedSchematic(components=[cap], nets=[net])
        chunks = chunk_schematic(schematic)

        power_chunks = [c for c in chunks if c.chunk_type == "power_rail"]
        assert len(power_chunks) == 1
        assert power_chunks[0].label == "Power Rail: 3V3"


class TestChunkOrdering:
    """Test chunk ordering (IC chunks first, then power_rail)."""

    def test_ic_chunks_before_power_chunks(self):
        """Test that IC chunks come before power rail chunks in output."""
        ic = ParsedComponent(
            reference="U1",
            value="STM32",
            lib_id="MCU:STM32",
            pins=[ParsedPin(number="1", name="VCC", connected_net="VCC")],
        )
        cap = ParsedComponent(
            reference="C1",
            value="100n",
            lib_id="Device:C",
            pins=[ParsedPin(number="1", name="1", connected_net="VCC")],
        )
        net = ParsedNet(
            name="VCC",
            is_power=True,
            pins=[
                PinConnection(component_ref="U1", pin_number="1"),
                PinConnection(component_ref="C1", pin_number="1"),
            ],
        )
        schematic = ParsedSchematic(components=[ic, cap], nets=[net])
        chunks = chunk_schematic(schematic)

        assert len(chunks) == 2
        # First chunk should be IC context
        assert chunks[0].chunk_type == "ic_context"
        # Second chunk should be power rail
        assert chunks[1].chunk_type == "power_rail"

    def test_multiple_ics_multiple_power_rails(self):
        """Test ordering with multiple ICs and power rails."""
        ic1 = ParsedComponent(reference="U1", value="IC1", lib_id="MCU:IC1")
        ic2 = ParsedComponent(reference="U2", value="IC2", lib_id="MCU:IC2")
        cap1 = ParsedComponent(
            reference="C1",
            value="100n",
            lib_id="Device:C",
            pins=[ParsedPin(number="1", name="1", connected_net="VCC")],
        )
        cap2 = ParsedComponent(
            reference="C2",
            value="100n",
            lib_id="Device:C",
            pins=[ParsedPin(number="1", name="1", connected_net="GND")],
        )
        vcc = ParsedNet(
            name="VCC",
            is_power=True,
            pins=[PinConnection(component_ref="C1", pin_number="1")],
        )
        gnd = ParsedNet(
            name="GND",
            is_power=True,
            pins=[PinConnection(component_ref="C2", pin_number="1")],
        )
        schematic = ParsedSchematic(
            components=[ic1, ic2, cap1, cap2], nets=[vcc, gnd]
        )
        chunks = chunk_schematic(schematic)

        # Should have 2 IC chunks + 2 power rail chunks = 4 total
        assert len(chunks) == 4
        # First two should be IC chunks
        assert chunks[0].chunk_type == "ic_context"
        assert chunks[1].chunk_type == "ic_context"
        # Last two should be power rail chunks
        assert chunks[2].chunk_type == "power_rail"
        assert chunks[3].chunk_type == "power_rail"


class TestImportFromReviewer:
    """Test that chunker exports are available from revlo.reviewer (US-008 AC6)."""

    def test_import_review_chunk(self):
        """Test that ReviewChunk can be imported from revlo.reviewer."""
        from revlo.reviewer import ReviewChunk as ImportedReviewChunk

        chunk = ImportedReviewChunk(chunk_type="ic_context", label="U1 - STM32")
        assert chunk.chunk_type == "ic_context"
        assert chunk.label == "U1 - STM32"

    def test_import_chunk_schematic(self):
        """Test that chunk_schematic can be imported from revlo.reviewer."""
        from revlo.reviewer import chunk_schematic as imported_chunk_schematic

        schematic = ParsedSchematic()
        chunks = imported_chunk_schematic(schematic)
        assert chunks == []
