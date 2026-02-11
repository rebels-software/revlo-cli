"""Test suite for Pydantic models in revlo.parser.models."""

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
    def test_defaults_and_required(self):
        pin = ParsedPin(number="1", name="VCC")
        assert pin.number == "1"
        assert pin.name == "VCC"
        assert pin.position == (0.0, 0.0)
        assert pin.electrical_type == "unspecified"
        assert pin.connected_net is None

    def test_all_fields(self):
        pin = ParsedPin(
            number="1", name="VCC", position=(10.5, 20.3),
            electrical_type="power_in", connected_net="VCC",
        )
        assert pin.position == (10.5, 20.3)
        assert pin.electrical_type == "power_in"
        assert pin.connected_net == "VCC"


class TestPinConnection:
    def test_defaults_and_required(self):
        conn = PinConnection(component_ref="U1", pin_number="1")
        assert conn.component_ref == "U1"
        assert conn.pin_number == "1"
        assert conn.pin_name == ""


class TestParsedComponent:
    def test_defaults_and_required(self):
        comp = ParsedComponent(reference="U1", value="STM32", lib_id="MCU:STM32")
        assert comp.reference == "U1"
        assert comp.footprint == ""
        assert comp.position == (0.0, 0.0)
        assert comp.rotation == 0.0
        assert comp.pins == []
        assert comp.properties == {}

    def test_with_pins_and_properties(self):
        pin = ParsedPin(number="1", name="VCC")
        comp = ParsedComponent(
            reference="U1", value="STM32", lib_id="MCU:STM32",
            footprint="LQFP-48", position=(100.0, 100.0), rotation=90.0,
            pins=[pin], properties={"Datasheet": "http://example.com"},
        )
        assert len(comp.pins) == 1
        assert all(isinstance(p, ParsedPin) for p in comp.pins)
        assert comp.properties["Datasheet"] == "http://example.com"


class TestParsedNet:
    def test_defaults_and_required(self):
        net = ParsedNet(name="VCC")
        assert net.name == "VCC"
        assert net.pins == []
        assert net.labels == []
        assert net.is_power is False

    def test_with_pins_and_labels(self):
        conn = PinConnection(component_ref="U1", pin_number="1")
        net = ParsedNet(name="VCC", pins=[conn], labels=["VCC", "+3V3"], is_power=True)
        assert len(net.pins) == 1
        assert all(isinstance(p, PinConnection) for p in net.pins)
        assert net.is_power is True


class TestParsedSheet:
    def test_defaults_and_required(self):
        sheet = ParsedSheet(name="Power", filename="power.kicad_sch")
        assert sheet.name == "Power"
        assert sheet.filename == "power.kicad_sch"
        assert sheet.pins == []

    def test_with_pins(self):
        sheet = ParsedSheet(
            name="Power", filename="power.kicad_sch",
            pins=[{"name": "VCC", "type": "input"}],
        )
        assert len(sheet.pins) == 1
        assert sheet.pins[0]["name"] == "VCC"


class TestTitleBlockInfo:
    def test_defaults(self):
        title = TitleBlockInfo()
        assert title.title == ""
        assert title.date == ""
        assert title.revision == ""
        assert title.company == ""


class TestParsedSchematic:
    def test_defaults(self):
        s = ParsedSchematic()
        assert s.components == []
        assert s.nets == []
        assert s.power_symbols == []
        assert s.sheets == []
        assert s.unconnected_pins == []
        assert isinstance(s.title_block, TitleBlockInfo)

    def test_fully_populated(self):
        pin = ParsedPin(number="1", name="VCC")
        comp = ParsedComponent(reference="U1", value="STM32", lib_id="MCU", pins=[pin])
        pwr = ParsedComponent(reference="#PWR01", value="GND", lib_id="power")
        conn = PinConnection(component_ref="U1", pin_number="1", pin_name="VCC")
        net = ParsedNet(name="VCC", pins=[conn])
        sheet = ParsedSheet(name="Power", filename="power.kicad_sch")
        unconnected = PinConnection(component_ref="U2", pin_number="5", pin_name="NC")
        title = TitleBlockInfo(title="Test Project")

        s = ParsedSchematic(
            components=[comp], nets=[net], power_symbols=[pwr],
            sheets=[sheet], unconnected_pins=[unconnected], title_block=title,
        )
        assert len(s.components) == 1
        assert len(s.power_symbols) == 1
        assert s.title_block.title == "Test Project"


class TestModelDumpAndSerialization:
    """All models serialise via .model_dump() and nested structures round-trip."""

    def test_all_models_have_model_dump(self):
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
            data = model.model_dump()
            assert isinstance(data, dict)

    def test_nested_serialization(self):
        pin = ParsedPin(number="1", name="VCC", connected_net="VCC")
        comp = ParsedComponent(reference="U1", value="STM32", lib_id="MCU", pins=[pin])
        s = ParsedSchematic(components=[comp])
        data = s.model_dump()
        assert data["components"][0]["pins"][0]["connected_net"] == "VCC"
