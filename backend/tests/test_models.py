"""Test suite for Pydantic models in revlo.parser.models."""

import pytest
from pydantic import ValidationError

from revlo.parser.models import (
    ParsedPin,
    ParsedComponent,
    ParsedNet,
    PinConnection,
    ParsedSheet,
    ParsedSchematic,
    TitleBlockInfo,
)


class TestParsedPin:
    """Test ParsedPin model (US-002 AC1)."""

    def test_required_fields(self):
        """Test that ParsedPin has required fields: number, name, position, electrical_type, connected_net."""
        pin = ParsedPin(number="1", name="VCC")
        assert pin.number == "1"
        assert pin.name == "VCC"
        assert pin.position == (0.0, 0.0)  # Default
        assert pin.electrical_type == "unspecified"  # Default
        assert pin.connected_net is None  # Default

    def test_all_fields_populated(self):
        """Test ParsedPin with all fields populated."""
        pin = ParsedPin(
            number="1",
            name="VCC",
            position=(10.5, 20.3),
            electrical_type="power_in",
            connected_net="VCC",
        )
        assert pin.number == "1"
        assert pin.name == "VCC"
        assert pin.position == (10.5, 20.3)
        assert pin.electrical_type == "power_in"
        assert pin.connected_net == "VCC"

    def test_model_dump(self):
        """Test .model_dump() returns dict for JSON serialization."""
        pin = ParsedPin(
            number="1",
            name="VCC",
            position=(10.0, 20.0),
            electrical_type="power_in",
            connected_net="VCC",
        )
        data = pin.model_dump()
        assert isinstance(data, dict)
        assert data["number"] == "1"
        assert data["name"] == "VCC"
        assert data["position"] == (10.0, 20.0)
        assert data["electrical_type"] == "power_in"
        assert data["connected_net"] == "VCC"


class TestPinConnection:
    """Test PinConnection model (US-002 AC4)."""

    def test_required_fields(self):
        """Test that PinConnection has required fields: component_ref, pin_number, pin_name."""
        conn = PinConnection(component_ref="U1", pin_number="1")
        assert conn.component_ref == "U1"
        assert conn.pin_number == "1"
        assert conn.pin_name == ""  # Default

    def test_all_fields_populated(self):
        """Test PinConnection with all fields populated."""
        conn = PinConnection(component_ref="U1", pin_number="1", pin_name="VCC")
        assert conn.component_ref == "U1"
        assert conn.pin_number == "1"
        assert conn.pin_name == "VCC"

    def test_model_dump(self):
        """Test .model_dump() returns dict for JSON serialization."""
        conn = PinConnection(component_ref="U1", pin_number="1", pin_name="VCC")
        data = conn.model_dump()
        assert isinstance(data, dict)
        assert data["component_ref"] == "U1"
        assert data["pin_number"] == "1"
        assert data["pin_name"] == "VCC"


class TestParsedComponent:
    """Test ParsedComponent model (US-002 AC2)."""

    def test_required_fields(self):
        """Test that ParsedComponent has required fields: reference, value, lib_id, footprint, position, rotation, pins, properties."""
        comp = ParsedComponent(reference="U1", value="STM32F103", lib_id="MCU_ST:STM32F103")
        assert comp.reference == "U1"
        assert comp.value == "STM32F103"
        assert comp.lib_id == "MCU_ST:STM32F103"
        assert comp.footprint == ""  # Default
        assert comp.position == (0.0, 0.0)  # Default
        assert comp.rotation == 0.0  # Default
        assert comp.pins == []  # Default
        assert comp.properties == {}  # Default

    def test_all_fields_populated(self):
        """Test ParsedComponent with all fields populated."""
        pin = ParsedPin(number="1", name="VCC")
        comp = ParsedComponent(
            reference="U1",
            value="STM32F103",
            lib_id="MCU_ST:STM32F103",
            footprint="LQFP-48",
            position=(100.0, 100.0),
            rotation=90.0,
            pins=[pin],
            properties={"Datasheet": "http://example.com"},
        )
        assert comp.reference == "U1"
        assert comp.value == "STM32F103"
        assert comp.lib_id == "MCU_ST:STM32F103"
        assert comp.footprint == "LQFP-48"
        assert comp.position == (100.0, 100.0)
        assert comp.rotation == 90.0
        assert len(comp.pins) == 1
        assert comp.pins[0].number == "1"
        assert comp.properties["Datasheet"] == "http://example.com"

    def test_pins_list_type(self):
        """Test that pins is a list[ParsedPin]."""
        pin1 = ParsedPin(number="1", name="VCC")
        pin2 = ParsedPin(number="2", name="GND")
        comp = ParsedComponent(
            reference="U1",
            value="STM32F103",
            lib_id="MCU_ST:STM32F103",
            pins=[pin1, pin2],
        )
        assert len(comp.pins) == 2
        assert all(isinstance(p, ParsedPin) for p in comp.pins)

    def test_model_dump(self):
        """Test .model_dump() returns dict for JSON serialization."""
        pin = ParsedPin(number="1", name="VCC")
        comp = ParsedComponent(
            reference="U1",
            value="STM32F103",
            lib_id="MCU_ST:STM32F103",
            pins=[pin],
            properties={"Datasheet": "http://example.com"},
        )
        data = comp.model_dump()
        assert isinstance(data, dict)
        assert data["reference"] == "U1"
        assert isinstance(data["pins"], list)
        assert len(data["pins"]) == 1
        assert isinstance(data["properties"], dict)


class TestParsedNet:
    """Test ParsedNet model (US-002 AC3)."""

    def test_required_fields(self):
        """Test that ParsedNet has required fields: name, pins, labels, is_power."""
        net = ParsedNet(name="VCC")
        assert net.name == "VCC"
        assert net.pins == []  # Default
        assert net.labels == []  # Default
        assert net.is_power is False  # Default

    def test_all_fields_populated(self):
        """Test ParsedNet with all fields populated."""
        conn = PinConnection(component_ref="U1", pin_number="1", pin_name="VCC")
        net = ParsedNet(name="VCC", pins=[conn], labels=["VCC", "+3V3"], is_power=True)
        assert net.name == "VCC"
        assert len(net.pins) == 1
        assert net.pins[0].component_ref == "U1"
        assert net.labels == ["VCC", "+3V3"]
        assert net.is_power is True

    def test_pins_list_type(self):
        """Test that pins is a list[PinConnection]."""
        conn1 = PinConnection(component_ref="U1", pin_number="1")
        conn2 = PinConnection(component_ref="U2", pin_number="2")
        net = ParsedNet(name="VCC", pins=[conn1, conn2])
        assert len(net.pins) == 2
        assert all(isinstance(p, PinConnection) for p in net.pins)

    def test_model_dump(self):
        """Test .model_dump() returns dict for JSON serialization."""
        conn = PinConnection(component_ref="U1", pin_number="1", pin_name="VCC")
        net = ParsedNet(name="VCC", pins=[conn], labels=["VCC"], is_power=True)
        data = net.model_dump()
        assert isinstance(data, dict)
        assert data["name"] == "VCC"
        assert isinstance(data["pins"], list)
        assert isinstance(data["labels"], list)
        assert data["is_power"] is True


class TestParsedSheet:
    """Test ParsedSheet model (US-002 AC5)."""

    def test_required_fields(self):
        """Test that ParsedSheet has required fields: name, filename, pins."""
        sheet = ParsedSheet(name="Power", filename="power.kicad_sch")
        assert sheet.name == "Power"
        assert sheet.filename == "power.kicad_sch"
        assert sheet.pins == []  # Default

    def test_hierarchical_pins(self):
        """Test ParsedSheet with hierarchical pins."""
        sheet = ParsedSheet(
            name="Power",
            filename="power.kicad_sch",
            pins=[
                {"name": "VCC", "type": "input"},
                {"name": "GND", "type": "input"},
            ],
        )
        assert sheet.name == "Power"
        assert sheet.filename == "power.kicad_sch"
        assert len(sheet.pins) == 2
        assert sheet.pins[0]["name"] == "VCC"

    def test_model_dump(self):
        """Test .model_dump() returns dict for JSON serialization."""
        sheet = ParsedSheet(
            name="Power",
            filename="power.kicad_sch",
            pins=[{"name": "VCC", "type": "input"}],
        )
        data = sheet.model_dump()
        assert isinstance(data, dict)
        assert data["name"] == "Power"
        assert data["filename"] == "power.kicad_sch"
        assert isinstance(data["pins"], list)


class TestTitleBlockInfo:
    """Test TitleBlockInfo model."""

    def test_default_fields(self):
        """Test TitleBlockInfo with default empty fields."""
        title = TitleBlockInfo()
        assert title.title == ""
        assert title.date == ""
        assert title.revision == ""
        assert title.company == ""

    def test_all_fields_populated(self):
        """Test TitleBlockInfo with all fields populated."""
        title = TitleBlockInfo(
            title="Test Project",
            date="2024-01-01",
            revision="A",
            company="Test Co",
        )
        assert title.title == "Test Project"
        assert title.date == "2024-01-01"
        assert title.revision == "A"
        assert title.company == "Test Co"

    def test_model_dump(self):
        """Test .model_dump() returns dict for JSON serialization."""
        title = TitleBlockInfo(
            title="Test Project",
            date="2024-01-01",
            revision="A",
            company="Test Co",
        )
        data = title.model_dump()
        assert isinstance(data, dict)
        assert data["title"] == "Test Project"


class TestParsedSchematic:
    """Test ParsedSchematic model (US-002 AC6)."""

    def test_required_fields(self):
        """Test that ParsedSchematic has required fields: components, nets, power_symbols, sheets, unconnected_pins, title_block."""
        schematic = ParsedSchematic()
        assert schematic.components == []  # Default
        assert schematic.nets == []  # Default
        assert schematic.power_symbols == []  # Default
        assert schematic.sheets == []  # Default
        assert schematic.unconnected_pins == []  # Default
        assert isinstance(schematic.title_block, TitleBlockInfo)

    def test_all_fields_populated(self):
        """Test ParsedSchematic with all fields populated."""
        pin = ParsedPin(number="1", name="VCC")
        comp = ParsedComponent(reference="U1", value="STM32", lib_id="MCU", pins=[pin])
        pwr = ParsedComponent(reference="#PWR01", value="GND", lib_id="power")
        conn = PinConnection(component_ref="U1", pin_number="1", pin_name="VCC")
        net = ParsedNet(name="VCC", pins=[conn])
        sheet = ParsedSheet(name="Power", filename="power.kicad_sch")
        unconnected = PinConnection(component_ref="U2", pin_number="5", pin_name="NC")
        title = TitleBlockInfo(title="Test Project")

        schematic = ParsedSchematic(
            components=[comp],
            nets=[net],
            power_symbols=[pwr],
            sheets=[sheet],
            unconnected_pins=[unconnected],
            title_block=title,
        )

        assert len(schematic.components) == 1
        assert schematic.components[0].reference == "U1"
        assert len(schematic.nets) == 1
        assert schematic.nets[0].name == "VCC"
        assert len(schematic.power_symbols) == 1
        assert schematic.power_symbols[0].reference == "#PWR01"
        assert len(schematic.sheets) == 1
        assert schematic.sheets[0].name == "Power"
        assert len(schematic.unconnected_pins) == 1
        assert schematic.unconnected_pins[0].component_ref == "U2"
        assert schematic.title_block.title == "Test Project"

    def test_model_dump(self):
        """Test .model_dump() returns dict for JSON serialization."""
        comp = ParsedComponent(reference="U1", value="STM32", lib_id="MCU")
        title = TitleBlockInfo(title="Test Project")
        schematic = ParsedSchematic(components=[comp], title_block=title)

        data = schematic.model_dump()
        assert isinstance(data, dict)
        assert isinstance(data["components"], list)
        assert isinstance(data["nets"], list)
        assert isinstance(data["power_symbols"], list)
        assert isinstance(data["sheets"], list)
        assert isinstance(data["unconnected_pins"], list)
        assert isinstance(data["title_block"], dict)
        assert data["title_block"]["title"] == "Test Project"


class TestPydanticV2Features:
    """Test Pydantic v2 BaseModel features (US-002 AC7)."""

    def test_all_models_have_model_dump(self):
        """Verify all models have .model_dump() method (Pydantic v2)."""
        models = [
            ParsedPin(number="1", name="VCC"),
            PinConnection(component_ref="U1", pin_number="1"),
            ParsedComponent(reference="U1", value="STM32", lib_id="MCU"),
            ParsedNet(name="VCC"),
            ParsedSheet(name="Power", filename="power.kicad_sch"),
            TitleBlockInfo(),
            ParsedSchematic(),
        ]

        for model in models:
            assert hasattr(model, "model_dump")
            data = model.model_dump()
            assert isinstance(data, dict)

    def test_nested_model_dump(self):
        """Test that nested models serialize correctly."""
        pin = ParsedPin(number="1", name="VCC", connected_net="VCC")
        comp = ParsedComponent(
            reference="U1",
            value="STM32",
            lib_id="MCU",
            pins=[pin],
        )
        schematic = ParsedSchematic(components=[comp])

        data = schematic.model_dump()
        assert data["components"][0]["pins"][0]["number"] == "1"
        assert data["components"][0]["pins"][0]["connected_net"] == "VCC"
