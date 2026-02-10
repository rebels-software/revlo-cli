"""Test suite for connectivity module in revlo.parser.connectivity."""

from unittest.mock import MagicMock

from revlo.parser.connectivity import build_net_list, _is_power_net
from revlo.parser.models import ParsedComponent, ParsedNet, ParsedPin, PinConnection


class TestIsPowerNet:
    """Test _is_power_net() helper function (US-004 AC4)."""

    def test_power_net_by_component_ref(self):
        """Test that nets connected to #PWR components are classified as power."""
        assert _is_power_net("SomeNet", ["#PWR001"]) is True
        assert _is_power_net("SomeNet", ["U1", "#PWR002", "U2"]) is True
        assert _is_power_net("RandomName", ["#PWR01"]) is True

    def test_power_net_by_name_vcc_vdd_vss(self):
        """Test that VCC, VDD, VSS nets are classified as power."""
        assert _is_power_net("VCC", []) is True
        assert _is_power_net("VDD", []) is True
        assert _is_power_net("VSS", []) is True
        assert _is_power_net("VDC", []) is True
        assert _is_power_net("vcc", []) is True  # Case insensitive
        assert _is_power_net("vdd", []) is True

    def test_power_net_by_name_gnd_variants(self):
        """Test that GND and variants are classified as power."""
        assert _is_power_net("GND", []) is True
        assert _is_power_net("GNDA", []) is True
        assert _is_power_net("GNDD", []) is True
        assert _is_power_net("GNDREF", []) is True
        assert _is_power_net("gnd", []) is True  # Case insensitive

    def test_power_net_by_name_vbus(self):
        """Test that VBUS is classified as power."""
        assert _is_power_net("VBUS", []) is True
        assert _is_power_net("vbus", []) is True

    def test_power_net_by_name_voltage_rails(self):
        """Test that voltage rails like +3V3, +5V, +12V are classified as power."""
        assert _is_power_net("+3V3", []) is True
        assert _is_power_net("+5V", []) is True
        assert _is_power_net("+12V", []) is True
        assert _is_power_net("-12V", []) is True
        assert _is_power_net("+1V8", []) is True
        assert _is_power_net("+2V5", []) is True
        assert _is_power_net("+3.3V", []) is True
        assert _is_power_net("+1.8V", []) is True
        assert _is_power_net("+2.5V", []) is True

    def test_signal_nets_not_classified_as_power(self):
        """Test that signal nets are not classified as power."""
        assert _is_power_net("SDA", []) is False
        assert _is_power_net("SCL", []) is False
        assert _is_power_net("MISO", []) is False
        assert _is_power_net("MOSI", []) is False
        assert _is_power_net("CLK", []) is False
        assert _is_power_net("RESET", []) is False
        assert _is_power_net("USB_DP", []) is False
        assert _is_power_net("USB_DM", []) is False

    def test_signal_nets_with_regular_refs(self):
        """Test that signal nets with regular component refs are not power."""
        assert _is_power_net("SDA", ["U1", "U2"]) is False
        assert _is_power_net("CLK", ["U1", "R1"]) is False


class TestBuildNetList:
    """Test build_net_list() function (US-004 AC1, AC2, AC3, AC5)."""

    def test_empty_component_list(self):
        """Test build_net_list with empty component list returns empty nets."""
        mock_sch = MagicMock()
        mock_sch.labels = []

        nets, unconnected = build_net_list(mock_sch, [])

        assert nets == []
        assert unconnected == []

    def test_single_component_single_pin_no_net(self):
        """Test component with unconnected pin."""
        mock_sch = MagicMock()
        mock_sch.labels = []
        mock_sch.get_net_for_pin = MagicMock(return_value=None)

        pin = ParsedPin(number="1", name="VCC")
        comp = ParsedComponent(
            reference="U1",
            value="IC",
            lib_id="Device:IC",
            pins=[pin],
        )

        nets, unconnected = build_net_list(mock_sch, [comp])

        assert len(nets) == 0
        assert len(unconnected) == 1
        assert unconnected[0].component_ref == "U1"
        assert unconnected[0].pin_number == "1"
        assert unconnected[0].pin_name == "VCC"

    def test_single_component_single_pin_with_net(self):
        """Test component with single connected pin creates a net."""
        mock_sch = MagicMock()
        mock_sch.labels = []

        # Mock net returned by get_net_for_pin
        mock_net = MagicMock()
        mock_net.name = "VCC"
        mock_net.labels = []
        mock_net.pins = [MagicMock(reference="U1")]
        mock_sch.get_net_for_pin = MagicMock(return_value=mock_net)

        pin = ParsedPin(number="1", name="VCC")
        comp = ParsedComponent(
            reference="U1",
            value="IC",
            lib_id="Device:IC",
            pins=[pin],
        )

        nets, unconnected = build_net_list(mock_sch, [comp])

        assert len(nets) == 1
        assert len(unconnected) == 0
        assert nets[0].name == "VCC"
        assert len(nets[0].pins) == 1
        assert nets[0].pins[0].component_ref == "U1"
        assert nets[0].pins[0].pin_number == "1"

    def test_net_deduplication_two_pins_same_net(self):
        """Test that two pins on the same net are grouped together (US-004 AC3)."""
        mock_sch = MagicMock()
        mock_sch.labels = []

        # Both pins return the same net
        mock_net = MagicMock()
        mock_net.name = "VCC"
        mock_net.labels = []
        mock_net.pins = [
            MagicMock(reference="U1"),
            MagicMock(reference="U2"),
        ]
        mock_sch.get_net_for_pin = MagicMock(return_value=mock_net)

        pin1 = ParsedPin(number="1", name="VCC")
        comp1 = ParsedComponent(
            reference="U1",
            value="IC1",
            lib_id="Device:IC",
            pins=[pin1],
        )

        pin2 = ParsedPin(number="2", name="VCC")
        comp2 = ParsedComponent(
            reference="U2",
            value="IC2",
            lib_id="Device:IC",
            pins=[pin2],
        )

        nets, unconnected = build_net_list(mock_sch, [comp1, comp2])

        # Should have only one net with two pins
        assert len(nets) == 1
        assert len(unconnected) == 0
        assert nets[0].name == "VCC"
        assert len(nets[0].pins) == 2

        # Verify both pins are in the net
        refs = {p.component_ref for p in nets[0].pins}
        assert refs == {"U1", "U2"}

    def test_net_deduplication_avoids_duplicate_pins(self):
        """Test that duplicate pin connections are avoided in net."""
        mock_sch = MagicMock()
        mock_sch.labels = []

        mock_net = MagicMock()
        mock_net.name = "VCC"
        mock_net.labels = []
        mock_net.pins = [MagicMock(reference="U1")]
        mock_sch.get_net_for_pin = MagicMock(return_value=mock_net)

        # Two pins on the same component with same pin number
        pin1 = ParsedPin(number="1", name="VCC")
        pin2 = ParsedPin(number="1", name="VCC")  # Same pin number
        comp = ParsedComponent(
            reference="U1",
            value="IC",
            lib_id="Device:IC",
            pins=[pin1, pin2],
        )

        nets, unconnected = build_net_list(mock_sch, [comp])

        # Should deduplicate: only one pin connection
        assert len(nets) == 1
        assert len(nets[0].pins) == 1
        assert nets[0].pins[0].component_ref == "U1"
        assert nets[0].pins[0].pin_number == "1"

    def test_power_classification_by_component_ref(self):
        """Test power classification by #PWR reference (US-004 AC4)."""
        mock_sch = MagicMock()
        mock_sch.labels = []

        # Net connected to power symbol
        mock_net = MagicMock()
        mock_net.name = "Net-PWR-1"
        mock_net.labels = []
        mock_net.pins = [MagicMock(reference="#PWR001")]
        mock_sch.get_net_for_pin = MagicMock(return_value=mock_net)

        pin = ParsedPin(number="1", name="VCC")
        comp = ParsedComponent(
            reference="#PWR001",
            value="GND",
            lib_id="power:GND",
            pins=[pin],
        )

        nets, unconnected = build_net_list(mock_sch, [comp])

        assert len(nets) == 1
        assert nets[0].is_power is True

    def test_power_classification_by_net_name_vcc(self):
        """Test power classification by net name VCC (US-004 AC4)."""
        mock_sch = MagicMock()
        mock_sch.labels = []

        mock_net = MagicMock()
        mock_net.name = "VCC"
        mock_net.labels = []
        mock_net.pins = [MagicMock(reference="U1")]
        mock_sch.get_net_for_pin = MagicMock(return_value=mock_net)

        pin = ParsedPin(number="1", name="VCC")
        comp = ParsedComponent(
            reference="U1",
            value="IC",
            lib_id="Device:IC",
            pins=[pin],
        )

        nets, unconnected = build_net_list(mock_sch, [comp])

        assert len(nets) == 1
        assert nets[0].name == "VCC"
        assert nets[0].is_power is True

    def test_power_classification_by_net_name_gnd(self):
        """Test power classification by net name GND (US-004 AC4)."""
        mock_sch = MagicMock()
        mock_sch.labels = []

        mock_net = MagicMock()
        mock_net.name = "GND"
        mock_net.labels = []
        mock_net.pins = [MagicMock(reference="U1")]
        mock_sch.get_net_for_pin = MagicMock(return_value=mock_net)

        pin = ParsedPin(number="1", name="GND")
        comp = ParsedComponent(
            reference="U1",
            value="IC",
            lib_id="Device:IC",
            pins=[pin],
        )

        nets, unconnected = build_net_list(mock_sch, [comp])

        assert len(nets) == 1
        assert nets[0].name == "GND"
        assert nets[0].is_power is True

    def test_power_classification_by_net_name_voltage_rail(self):
        """Test power classification by net name +3V3 (US-004 AC4)."""
        mock_sch = MagicMock()
        mock_sch.labels = []

        mock_net = MagicMock()
        mock_net.name = "+3V3"
        mock_net.labels = []
        mock_net.pins = [MagicMock(reference="U1")]
        mock_sch.get_net_for_pin = MagicMock(return_value=mock_net)

        pin = ParsedPin(number="1", name="3V3")
        comp = ParsedComponent(
            reference="U1",
            value="IC",
            lib_id="Device:IC",
            pins=[pin],
        )

        nets, unconnected = build_net_list(mock_sch, [comp])

        assert len(nets) == 1
        assert nets[0].name == "+3V3"
        assert nets[0].is_power is True

    def test_signal_net_classification(self):
        """Test that signal nets are not classified as power (US-004 AC4)."""
        mock_sch = MagicMock()
        mock_sch.labels = []

        mock_net = MagicMock()
        mock_net.name = "SDA"
        mock_net.labels = []
        mock_net.pins = [MagicMock(reference="U1")]
        mock_sch.get_net_for_pin = MagicMock(return_value=mock_net)

        pin = ParsedPin(number="1", name="SDA")
        comp = ParsedComponent(
            reference="U1",
            value="IC",
            lib_id="Device:IC",
            pins=[pin],
        )

        nets, unconnected = build_net_list(mock_sch, [comp])

        assert len(nets) == 1
        assert nets[0].name == "SDA"
        assert nets[0].is_power is False

    def test_multiple_nets_mixed_power_and_signal(self):
        """Test multiple nets with mixed power and signal."""
        mock_sch = MagicMock()
        mock_sch.labels = []

        # Create different nets
        vcc_net = MagicMock()
        vcc_net.name = "VCC"
        vcc_net.labels = []
        vcc_net.pins = [MagicMock(reference="U1")]

        sda_net = MagicMock()
        sda_net.name = "SDA"
        sda_net.labels = []
        sda_net.pins = [MagicMock(reference="U2")]

        gnd_net = MagicMock()
        gnd_net.name = "GND"
        gnd_net.labels = []
        gnd_net.pins = [MagicMock(reference="U3")]

        def get_net_side_effect(ref, pin_num):
            if ref == "U1":
                return vcc_net
            elif ref == "U2":
                return sda_net
            elif ref == "U3":
                return gnd_net
            return None

        mock_sch.get_net_for_pin = MagicMock(side_effect=get_net_side_effect)

        pin1 = ParsedPin(number="1", name="VCC")
        comp1 = ParsedComponent(reference="U1", value="IC1", lib_id="Device:IC", pins=[pin1])

        pin2 = ParsedPin(number="1", name="SDA")
        comp2 = ParsedComponent(reference="U2", value="IC2", lib_id="Device:IC", pins=[pin2])

        pin3 = ParsedPin(number="1", name="GND")
        comp3 = ParsedComponent(reference="U3", value="IC3", lib_id="Device:IC", pins=[pin3])

        nets, unconnected = build_net_list(mock_sch, [comp1, comp2, comp3])

        assert len(nets) == 3
        assert len(unconnected) == 0

        # Find nets by name
        nets_by_name = {net.name: net for net in nets}

        assert "VCC" in nets_by_name
        assert nets_by_name["VCC"].is_power is True

        assert "GND" in nets_by_name
        assert nets_by_name["GND"].is_power is True

        assert "SDA" in nets_by_name
        assert nets_by_name["SDA"].is_power is False

    def test_net_labels_resolved_from_uuids(self):
        """Test that net labels are resolved from label UUIDs."""
        mock_sch = MagicMock()

        # Mock label with UUID
        mock_label = MagicMock()
        mock_label.uuid = "label-uuid-1"
        mock_label.text = "VCC_MAIN"
        mock_sch.labels = [mock_label]

        # Net with label UUID
        mock_net = MagicMock()
        mock_net.name = "VCC"
        mock_net.labels = ["label-uuid-1"]
        mock_net.pins = [MagicMock(reference="U1")]
        mock_sch.get_net_for_pin = MagicMock(return_value=mock_net)

        pin = ParsedPin(number="1", name="VCC")
        comp = ParsedComponent(reference="U1", value="IC", lib_id="Device:IC", pins=[pin])

        nets, unconnected = build_net_list(mock_sch, [comp])

        assert len(nets) == 1
        assert nets[0].labels == ["VCC_MAIN"]

    def test_net_labels_skip_missing_uuids(self):
        """Test that net labels skip UUIDs not found in label lookup."""
        mock_sch = MagicMock()
        mock_sch.labels = []  # Empty labels

        # Net with label UUID that doesn't exist
        mock_net = MagicMock()
        mock_net.name = "VCC"
        mock_net.labels = ["nonexistent-uuid"]
        mock_net.pins = [MagicMock(reference="U1")]
        mock_sch.get_net_for_pin = MagicMock(return_value=mock_net)

        pin = ParsedPin(number="1", name="VCC")
        comp = ParsedComponent(reference="U1", value="IC", lib_id="Device:IC", pins=[pin])

        nets, unconnected = build_net_list(mock_sch, [comp])

        assert len(nets) == 1
        assert nets[0].labels == []  # UUID not resolved

    def test_exception_handling_in_get_net_for_pin(self):
        """Test that exceptions from get_net_for_pin are caught and pin marked unconnected."""
        mock_sch = MagicMock()
        mock_sch.labels = []
        mock_sch.get_net_for_pin = MagicMock(side_effect=Exception("Network error"))

        pin = ParsedPin(number="1", name="VCC")
        comp = ParsedComponent(reference="U1", value="IC", lib_id="Device:IC", pins=[pin])

        nets, unconnected = build_net_list(mock_sch, [comp])

        # Exception should be caught, pin should be unconnected
        assert len(nets) == 0
        assert len(unconnected) == 1
        assert unconnected[0].component_ref == "U1"
        assert unconnected[0].pin_number == "1"

    def test_returns_parsed_net_objects(self):
        """Test that build_net_list returns list of ParsedNet objects (US-004 AC5)."""
        mock_sch = MagicMock()
        mock_sch.labels = []

        mock_net = MagicMock()
        mock_net.name = "VCC"
        mock_net.labels = []
        mock_net.pins = [MagicMock(reference="U1")]
        mock_sch.get_net_for_pin = MagicMock(return_value=mock_net)

        pin = ParsedPin(number="1", name="VCC")
        comp = ParsedComponent(reference="U1", value="IC", lib_id="Device:IC", pins=[pin])

        nets, unconnected = build_net_list(mock_sch, [comp])

        # Verify return types
        assert isinstance(nets, list)
        assert all(isinstance(net, ParsedNet) for net in nets)
        assert isinstance(unconnected, list)
        assert all(isinstance(pin, PinConnection) for pin in unconnected)

    def test_component_with_multiple_pins_on_different_nets(self):
        """Test component with multiple pins connected to different nets."""
        mock_sch = MagicMock()
        mock_sch.labels = []

        vcc_net = MagicMock()
        vcc_net.name = "VCC"
        vcc_net.labels = []
        vcc_net.pins = [MagicMock(reference="U1")]

        gnd_net = MagicMock()
        gnd_net.name = "GND"
        gnd_net.labels = []
        gnd_net.pins = [MagicMock(reference="U1")]

        def get_net_side_effect(ref, pin_num):
            if pin_num == "1":
                return vcc_net
            elif pin_num == "2":
                return gnd_net
            return None

        mock_sch.get_net_for_pin = MagicMock(side_effect=get_net_side_effect)

        pin1 = ParsedPin(number="1", name="VCC")
        pin2 = ParsedPin(number="2", name="GND")
        comp = ParsedComponent(
            reference="U1",
            value="IC",
            lib_id="Device:IC",
            pins=[pin1, pin2],
        )

        nets, unconnected = build_net_list(mock_sch, [comp])

        assert len(nets) == 2
        assert len(unconnected) == 0

        nets_by_name = {net.name: net for net in nets}
        assert "VCC" in nets_by_name
        assert "GND" in nets_by_name

        # Each net should have one pin
        assert len(nets_by_name["VCC"].pins) == 1
        assert len(nets_by_name["GND"].pins) == 1


class TestBuildNetListImport:
    """Test that build_net_list is importable from revlo.parser (US-004 AC1)."""

    def test_import_from_parser_package(self):
        """Test that build_net_list is re-exported from revlo.parser."""
        from revlo.parser import build_net_list as imported_func
        assert callable(imported_func)


class TestConnectivityModuleExists:
    """Test that connectivity.py module exists (US-004 AC1)."""

    def test_connectivity_module_importable(self):
        """Test that connectivity module can be imported."""
        import revlo.parser.connectivity
        assert hasattr(revlo.parser.connectivity, "build_net_list")
        assert hasattr(revlo.parser.connectivity, "_is_power_net")
