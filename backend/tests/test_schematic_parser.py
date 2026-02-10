"""Test suite for schematic parser in revlo.parser.schematic."""

from unittest.mock import MagicMock, patch
import pytest

from revlo.parser import parse_schematic
from revlo.parser.models import (
    ParsedComponent,
    ParsedNet,
    ParsedPin,
    ParsedSchematic,
    ParsedSheet,
    PinConnection,
    TitleBlockInfo,
)


class TestParseSchematicImport:
    """Test that parse_schematic is importable from revlo.parser (US-003 AC8)."""

    def test_import_from_parser_package(self):
        """Test that parse_schematic is re-exported from revlo.parser."""
        from revlo.parser import parse_schematic as imported_func
        assert callable(imported_func)


class TestParseSchematicFunction:
    """Test parse_schematic() function signature and basic behavior (US-003 AC1)."""

    def test_function_signature(self):
        """Test that parse_schematic(path: str) -> ParsedSchematic exists."""
        # Function should accept a single string argument
        assert callable(parse_schematic)

        # Verify it raises FileNotFoundError for missing file
        with pytest.raises(FileNotFoundError):
            parse_schematic("/nonexistent/path/to/file.kicad_sch")

    def test_file_not_found_error(self):
        """Test that parse_schematic raises FileNotFoundError for nonexistent path."""
        with pytest.raises(FileNotFoundError, match="Schematic file not found"):
            parse_schematic("/tmp/does_not_exist_12345.kicad_sch")

    def test_returns_parsed_schematic(self):
        """Test that parse_schematic returns a ParsedSchematic instance."""
        # Mock both Path.exists() and kicad-sch-api Schematic.load()
        with patch("revlo.parser.schematic.Path.exists") as mock_exists, \
             patch("revlo.parser.schematic.ksa.Schematic.load") as mock_load:
            mock_exists.return_value = True

            # Create a minimal mock schematic
            mock_sch = MagicMock()
            mock_sch.components = []
            mock_sch.labels = []
            mock_sch.title_block = {}
            mock_sch._data = {"sheets": []}
            mock_load.return_value = mock_sch

            result = parse_schematic("/fake/path.kicad_sch")

            assert isinstance(result, ParsedSchematic)
            assert result.components == []
            assert result.nets == []
            assert result.power_symbols == []
            assert result.sheets == []
            assert result.unconnected_pins == []
            assert isinstance(result.title_block, TitleBlockInfo)


class TestComponentExtraction:
    """Test component extraction with required fields (US-003 AC2)."""

    def test_extracts_component_fields(self):
        """Test that components are extracted with reference, value, lib_id, footprint, and pins."""
        with patch("revlo.parser.schematic.Path.exists") as mock_exists, \
             patch("revlo.parser.schematic.ksa.Schematic.load") as mock_load:
            mock_exists.return_value = True

            # Create a mock component
            mock_comp = MagicMock()
            mock_comp.reference = "U1"
            mock_comp.value = "STM32F103"
            mock_comp.lib_id = "MCU_ST:STM32F103"
            mock_comp.footprint = "LQFP-48"
            mock_comp.position = MagicMock(x=100.0, y=150.0)
            mock_comp.rotation = 90.0
            mock_comp.properties = {"Datasheet": "http://example.com"}

            # Add a mock pin
            mock_pin = MagicMock()
            mock_pin.number = "1"
            mock_pin.name = "VCC"
            mock_pin.pin_type = MagicMock(value="power_in")
            mock_comp.pins = [mock_pin]
            mock_comp.get_pin_position = MagicMock(return_value=MagicMock(x=105.0, y=155.0))

            # Create mock schematic
            mock_sch = MagicMock()
            mock_sch.components = [mock_comp]
            mock_sch.labels = []
            mock_sch.title_block = {}
            mock_sch._data = {"sheets": []}
            mock_sch.get_net_for_pin = MagicMock(return_value=None)
            mock_load.return_value = mock_sch

            result = parse_schematic("/fake/path.kicad_sch")

            assert len(result.components) == 1
            comp = result.components[0]
            assert comp.reference == "U1"
            assert comp.value == "STM32F103"
            assert comp.lib_id == "MCU_ST:STM32F103"
            assert comp.footprint == "LQFP-48"
            assert comp.position == (100.0, 150.0)
            assert comp.rotation == 90.0
            assert len(comp.pins) == 1
            assert comp.pins[0].number == "1"
            assert comp.pins[0].name == "VCC"
            assert comp.properties["Datasheet"] == "http://example.com"


class TestNetExtraction:
    """Test net extraction via get_net_for_pin() (US-003 AC3)."""

    def test_get_net_for_pin_called(self):
        """Test that get_net_for_pin() is called for each component pin."""
        with patch("revlo.parser.schematic.Path.exists") as mock_exists, \
             patch("revlo.parser.schematic.ksa.Schematic.load") as mock_load:
            mock_exists.return_value = True

            # Create a mock component with pins
            mock_comp = MagicMock()
            mock_comp.reference = "U1"
            mock_comp.value = "Resistor"
            mock_comp.lib_id = "Device:R"
            mock_comp.footprint = "0805"
            mock_comp.position = MagicMock(x=0.0, y=0.0)
            mock_comp.rotation = 0.0
            mock_comp.properties = {}

            mock_pin1 = MagicMock()
            mock_pin1.number = "1"
            mock_pin1.name = "~"
            mock_pin1.pin_type = MagicMock(value="passive")

            mock_pin2 = MagicMock()
            mock_pin2.number = "2"
            mock_pin2.name = "~"
            mock_pin2.pin_type = MagicMock(value="passive")

            mock_comp.pins = [mock_pin1, mock_pin2]
            mock_comp.get_pin_position = MagicMock(return_value=MagicMock(x=0.0, y=0.0))

            # Create a mock net
            mock_net = MagicMock()
            mock_net.name = "VCC"
            mock_net.labels = []
            mock_net.pins = [MagicMock(reference="U1")]

            # Create mock schematic
            mock_sch = MagicMock()
            mock_sch.components = [mock_comp]
            mock_sch.labels = []
            mock_sch.title_block = {}
            mock_sch._data = {"sheets": []}
            mock_sch.get_net_for_pin = MagicMock(return_value=mock_net)
            mock_load.return_value = mock_sch

            result = parse_schematic("/fake/path.kicad_sch")

            # Verify get_net_for_pin was called for each pin
            assert mock_sch.get_net_for_pin.call_count == 4  # 2 pins * 2 calls (once in _extract_pins, once in _extract_nets)

            # Verify pins have connected_net populated
            assert result.components[0].pins[0].connected_net == "VCC"
            assert result.components[0].pins[1].connected_net == "VCC"


class TestPowerSymbols:
    """Test power symbol identification (US-003 AC4)."""

    def test_identifies_power_symbols(self):
        """Test that power symbols (reference starts with #PWR) are identified."""
        with patch("revlo.parser.schematic.Path.exists") as mock_exists, \
             patch("revlo.parser.schematic.ksa.Schematic.load") as mock_load:
            mock_exists.return_value = True

            # Create a regular component
            mock_comp = MagicMock()
            mock_comp.reference = "U1"
            mock_comp.value = "STM32"
            mock_comp.lib_id = "MCU"
            mock_comp.footprint = ""
            mock_comp.position = MagicMock(x=0.0, y=0.0)
            mock_comp.rotation = 0.0
            mock_comp.properties = {}
            mock_comp.pins = []
            mock_comp.get_pin_position = MagicMock(return_value=MagicMock(x=0.0, y=0.0))

            # Create a power symbol
            mock_pwr = MagicMock()
            mock_pwr.reference = "#PWR001"
            mock_pwr.value = "GND"
            mock_pwr.lib_id = "power:GND"
            mock_pwr.footprint = ""
            mock_pwr.position = MagicMock(x=50.0, y=50.0)
            mock_pwr.rotation = 0.0
            mock_pwr.properties = {}
            mock_pwr.pins = []
            mock_pwr.get_pin_position = MagicMock(return_value=MagicMock(x=50.0, y=50.0))

            # Create mock schematic
            mock_sch = MagicMock()
            mock_sch.components = [mock_comp, mock_pwr]
            mock_sch.labels = []
            mock_sch.title_block = {}
            mock_sch._data = {"sheets": []}
            mock_sch.get_net_for_pin = MagicMock(return_value=None)
            mock_load.return_value = mock_sch

            result = parse_schematic("/fake/path.kicad_sch")

            # Regular component should be in components list
            assert len(result.components) == 1
            assert result.components[0].reference == "U1"

            # Power symbol should be in power_symbols list
            assert len(result.power_symbols) == 1
            assert result.power_symbols[0].reference == "#PWR001"
            assert result.power_symbols[0].value == "GND"


class TestUnconnectedPins:
    """Test unconnected pin detection (US-003 AC5)."""

    def test_finds_unconnected_pins(self):
        """Test that pins not in any net are identified as unconnected."""
        with patch("revlo.parser.schematic.Path.exists") as mock_exists, \
             patch("revlo.parser.schematic.ksa.Schematic.load") as mock_load:
            mock_exists.return_value = True

            # Create a component with both connected and unconnected pins
            mock_comp = MagicMock()
            mock_comp.reference = "U1"
            mock_comp.value = "IC"
            mock_comp.lib_id = "Device:IC"
            mock_comp.footprint = ""
            mock_comp.position = MagicMock(x=0.0, y=0.0)
            mock_comp.rotation = 0.0
            mock_comp.properties = {}

            mock_pin1 = MagicMock()
            mock_pin1.number = "1"
            mock_pin1.name = "VCC"
            mock_pin1.pin_type = MagicMock(value="power_in")

            mock_pin2 = MagicMock()
            mock_pin2.number = "2"
            mock_pin2.name = "NC"
            mock_pin2.pin_type = MagicMock(value="no_connect")

            mock_comp.pins = [mock_pin1, mock_pin2]
            mock_comp.get_pin_position = MagicMock(return_value=MagicMock(x=0.0, y=0.0))

            # Create a mock net for pin 1 only
            mock_net = MagicMock()
            mock_net.name = "VCC"
            mock_net.labels = []
            mock_net.pins = [MagicMock(reference="U1")]

            # Create mock schematic
            mock_sch = MagicMock()
            mock_sch.components = [mock_comp]
            mock_sch.labels = []
            mock_sch.title_block = {}
            mock_sch._data = {"sheets": []}

            # Pin 1 is connected, pin 2 is not
            def get_net_side_effect(ref, pin_num):
                if pin_num == "1":
                    return mock_net
                return None

            mock_sch.get_net_for_pin = MagicMock(side_effect=get_net_side_effect)
            mock_load.return_value = mock_sch

            result = parse_schematic("/fake/path.kicad_sch")

            # Verify unconnected pin is identified
            assert len(result.unconnected_pins) == 1
            assert result.unconnected_pins[0].component_ref == "U1"
            assert result.unconnected_pins[0].pin_number == "2"
            assert result.unconnected_pins[0].pin_name == "NC"


class TestHierarchicalSheets:
    """Test hierarchical sheet extraction (US-003 AC6)."""

    def test_extracts_hierarchical_sheets(self):
        """Test that hierarchical sheets are extracted from schematic._data['sheets']."""
        with patch("revlo.parser.schematic.Path.exists") as mock_exists, \
             patch("revlo.parser.schematic.ksa.Schematic.load") as mock_load:
            mock_exists.return_value = True

            # Create mock schematic with hierarchical sheets
            mock_sch = MagicMock()
            mock_sch.components = []
            mock_sch.labels = []
            mock_sch.title_block = {}
            mock_sch._data = {
                "sheets": [
                    {
                        "name": "Power Supply",
                        "filename": "power.kicad_sch",
                        "pins": [
                            {"name": "VCC", "type": "output"},
                            {"name": "GND", "type": "output"},
                        ],
                    },
                    {
                        "name": "USB Interface",
                        "filename": "usb.kicad_sch",
                        "pins": [
                            {"name": "D+", "type": "bidirectional"},
                            {"name": "D-", "type": "bidirectional"},
                        ],
                    },
                ]
            }
            mock_sch.get_net_for_pin = MagicMock(return_value=None)
            mock_load.return_value = mock_sch

            result = parse_schematic("/fake/path.kicad_sch")

            # Verify sheets are extracted
            assert len(result.sheets) == 2

            sheet1 = result.sheets[0]
            assert sheet1.name == "Power Supply"
            assert sheet1.filename == "power.kicad_sch"
            assert len(sheet1.pins) == 2
            assert sheet1.pins[0]["name"] == "VCC"
            assert sheet1.pins[0]["type"] == "output"

            sheet2 = result.sheets[1]
            assert sheet2.name == "USB Interface"
            assert sheet2.filename == "usb.kicad_sch"
            assert len(sheet2.pins) == 2


class TestTitleBlockExtraction:
    """Test title block metadata extraction."""

    def test_extracts_title_block(self):
        """Test that title block metadata is extracted."""
        with patch("revlo.parser.schematic.Path.exists") as mock_exists, \
             patch("revlo.parser.schematic.ksa.Schematic.load") as mock_load:
            mock_exists.return_value = True

            # Create mock schematic with title block
            mock_sch = MagicMock()
            mock_sch.components = []
            mock_sch.labels = []
            mock_sch.title_block = {
                "title": "Test Project",
                "date": "2024-01-15",
                "rev": "A",
                "company": "Test Company",
            }
            mock_sch._data = {"sheets": []}
            mock_sch.get_net_for_pin = MagicMock(return_value=None)
            mock_load.return_value = mock_sch

            result = parse_schematic("/fake/path.kicad_sch")

            # Verify title block is extracted
            assert isinstance(result.title_block, TitleBlockInfo)
            assert result.title_block.title == "Test Project"
            assert result.title_block.date == "2024-01-15"
            assert result.title_block.revision == "A"
            assert result.title_block.company == "Test Company"


class TestFullSchematicParsing:
    """Test complete schematic parsing with all features (US-003 AC7)."""

    def test_returns_fully_populated_parsed_schematic(self):
        """Test that parse_schematic returns a fully populated ParsedSchematic model."""
        with patch("revlo.parser.schematic.Path.exists") as mock_exists, \
             patch("revlo.parser.schematic.ksa.Schematic.load") as mock_load:
            mock_exists.return_value = True

            # Create a comprehensive mock schematic

            # Regular component
            mock_comp = MagicMock()
            mock_comp.reference = "R1"
            mock_comp.value = "10k"
            mock_comp.lib_id = "Device:R"
            mock_comp.footprint = "0805"
            mock_comp.position = MagicMock(x=100.0, y=100.0)
            mock_comp.rotation = 0.0
            mock_comp.properties = {}
            mock_pin = MagicMock()
            mock_pin.number = "1"
            mock_pin.name = "~"
            mock_pin.pin_type = MagicMock(value="passive")
            mock_comp.pins = [mock_pin]
            mock_comp.get_pin_position = MagicMock(return_value=MagicMock(x=100.0, y=100.0))

            # Power symbol
            mock_pwr = MagicMock()
            mock_pwr.reference = "#PWR001"
            mock_pwr.value = "GND"
            mock_pwr.lib_id = "power:GND"
            mock_pwr.footprint = ""
            mock_pwr.position = MagicMock(x=150.0, y=150.0)
            mock_pwr.rotation = 0.0
            mock_pwr.properties = {}
            mock_pwr_pin = MagicMock()
            mock_pwr_pin.number = "1"
            mock_pwr_pin.name = "~"
            mock_pwr_pin.pin_type = MagicMock(value="power_in")
            mock_pwr.pins = [mock_pwr_pin]
            mock_pwr.get_pin_position = MagicMock(return_value=MagicMock(x=150.0, y=150.0))

            # Net
            mock_net = MagicMock()
            mock_net.name = "VCC"
            mock_net.labels = ["label-uuid-1"]
            mock_net.pins = [MagicMock(reference="R1")]

            # Label
            mock_label = MagicMock()
            mock_label.uuid = "label-uuid-1"
            mock_label.text = "VCC"

            # Create mock schematic
            mock_sch = MagicMock()
            mock_sch.components = [mock_comp, mock_pwr]
            mock_sch.labels = [mock_label]
            mock_sch.title_block = {
                "title": "Full Test",
                "date": "2024-01-20",
                "rev": "B",
                "company": "Acme Corp",
            }
            mock_sch._data = {
                "sheets": [
                    {
                        "name": "Sheet1",
                        "filename": "sheet1.kicad_sch",
                        "pins": [],
                    }
                ]
            }

            # First pin connected, power symbol pin returns None
            def get_net_side_effect(ref, pin_num):
                if ref == "R1":
                    return mock_net
                return None

            mock_sch.get_net_for_pin = MagicMock(side_effect=get_net_side_effect)
            mock_load.return_value = mock_sch

            result = parse_schematic("/fake/path.kicad_sch")

            # Verify all sections are populated
            assert isinstance(result, ParsedSchematic)
            assert len(result.components) == 1
            assert len(result.power_symbols) == 1
            assert len(result.nets) == 1
            assert len(result.sheets) == 1
            assert len(result.unconnected_pins) == 1  # Power symbol pin is unconnected
            assert isinstance(result.title_block, TitleBlockInfo)
            assert result.title_block.title == "Full Test"
