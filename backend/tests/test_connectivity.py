"""Test suite for connectivity module in revlo.parser.connectivity."""

from unittest.mock import MagicMock

from revlo.parser.connectivity import build_net_list, _is_power_net
from revlo.parser.models import ParsedComponent, ParsedNet, ParsedPin, PinConnection


class TestIsPowerNet:
    """Test _is_power_net() classification logic."""

    def test_power_by_component_ref(self):
        assert _is_power_net("SomeNet", ["#PWR001"]) is True
        assert _is_power_net("SomeNet", ["U1", "#PWR002", "U2"]) is True

    def test_power_by_net_name(self):
        for name in ("VCC", "VDD", "VSS", "VDC", "vcc", "GND", "GNDA", "gnd",
                      "VBUS", "+3V3", "+5V", "+12V", "-12V", "+3.3V"):
            assert _is_power_net(name, []) is True, f"{name} should be power"

    def test_signal_nets_not_power(self):
        for name in ("SDA", "SCL", "MISO", "CLK", "RESET", "USB_DP"):
            assert _is_power_net(name, []) is False, f"{name} should not be power"
            assert _is_power_net(name, ["U1", "U2"]) is False


class TestBuildNetList:
    """Test build_net_list() core functionality."""

    def _mock_sch(self, labels=None):
        mock = MagicMock()
        mock.labels = labels or []
        return mock

    def test_empty_components(self):
        nets, unconnected = build_net_list(self._mock_sch(), [])
        assert nets == []
        assert unconnected == []

    def test_unconnected_pin(self):
        mock_sch = self._mock_sch()
        mock_sch.get_net_for_pin = MagicMock(return_value=None)
        pin = ParsedPin(number="1", name="VCC")
        comp = ParsedComponent(reference="U1", value="IC", lib_id="Device:IC", pins=[pin])
        nets, unconnected = build_net_list(mock_sch, [comp])
        assert len(nets) == 0
        assert len(unconnected) == 1
        assert unconnected[0].component_ref == "U1"

    def test_connected_pin_creates_net(self):
        mock_sch = self._mock_sch()
        mock_net = MagicMock(name="VCC", labels=[], pins=[MagicMock(reference="U1")])
        mock_net.name = "VCC"
        mock_sch.get_net_for_pin = MagicMock(return_value=mock_net)
        pin = ParsedPin(number="1", name="VCC")
        comp = ParsedComponent(reference="U1", value="IC", lib_id="Device:IC", pins=[pin])
        nets, unconnected = build_net_list(mock_sch, [comp])
        assert len(nets) == 1
        assert nets[0].name == "VCC"
        assert len(unconnected) == 0

    def test_deduplication_same_net(self):
        mock_sch = self._mock_sch()
        mock_net = MagicMock(name="VCC", labels=[], pins=[
            MagicMock(reference="U1"), MagicMock(reference="U2"),
        ])
        mock_net.name = "VCC"
        mock_sch.get_net_for_pin = MagicMock(return_value=mock_net)
        comp1 = ParsedComponent(reference="U1", value="IC1", lib_id="Device:IC",
                                pins=[ParsedPin(number="1", name="VCC")])
        comp2 = ParsedComponent(reference="U2", value="IC2", lib_id="Device:IC",
                                pins=[ParsedPin(number="2", name="VCC")])
        nets, _ = build_net_list(mock_sch, [comp1, comp2])
        assert len(nets) == 1
        assert len(nets[0].pins) == 2

    def test_deduplication_same_pin(self):
        mock_sch = self._mock_sch()
        mock_net = MagicMock(name="VCC", labels=[], pins=[MagicMock(reference="U1")])
        mock_net.name = "VCC"
        mock_sch.get_net_for_pin = MagicMock(return_value=mock_net)
        comp = ParsedComponent(reference="U1", value="IC", lib_id="Device:IC",
                               pins=[ParsedPin(number="1", name="VCC"),
                                     ParsedPin(number="1", name="VCC")])
        nets, _ = build_net_list(mock_sch, [comp])
        assert len(nets[0].pins) == 1

    def test_power_classification(self):
        mock_sch = self._mock_sch()
        vcc_net = MagicMock(name="VCC", labels=[], pins=[MagicMock(reference="U1")])
        vcc_net.name = "VCC"
        sda_net = MagicMock(name="SDA", labels=[], pins=[MagicMock(reference="U2")])
        sda_net.name = "SDA"

        def side_effect(ref, pin_num):
            return vcc_net if ref == "U1" else sda_net

        mock_sch.get_net_for_pin = MagicMock(side_effect=side_effect)
        comp1 = ParsedComponent(reference="U1", value="IC1", lib_id="Device:IC",
                                pins=[ParsedPin(number="1", name="VCC")])
        comp2 = ParsedComponent(reference="U2", value="IC2", lib_id="Device:IC",
                                pins=[ParsedPin(number="1", name="SDA")])
        nets, _ = build_net_list(mock_sch, [comp1, comp2])
        by_name = {n.name: n for n in nets}
        assert by_name["VCC"].is_power is True
        assert by_name["SDA"].is_power is False

    def test_label_resolution(self):
        mock_label = MagicMock(uuid="label-uuid-1", text="VCC_MAIN")
        mock_sch = self._mock_sch(labels=[mock_label])
        mock_net = MagicMock(name="VCC", labels=["label-uuid-1"],
                             pins=[MagicMock(reference="U1")])
        mock_net.name = "VCC"
        mock_sch.get_net_for_pin = MagicMock(return_value=mock_net)
        comp = ParsedComponent(reference="U1", value="IC", lib_id="Device:IC",
                               pins=[ParsedPin(number="1", name="VCC")])
        nets, _ = build_net_list(mock_sch, [comp])
        assert nets[0].labels == ["VCC_MAIN"]

    def test_missing_label_uuid_skipped(self):
        mock_sch = self._mock_sch()
        mock_net = MagicMock(name="VCC", labels=["nonexistent-uuid"],
                             pins=[MagicMock(reference="U1")])
        mock_net.name = "VCC"
        mock_sch.get_net_for_pin = MagicMock(return_value=mock_net)
        comp = ParsedComponent(reference="U1", value="IC", lib_id="Device:IC",
                               pins=[ParsedPin(number="1", name="VCC")])
        nets, _ = build_net_list(mock_sch, [comp])
        assert nets[0].labels == []

    def test_exception_marks_pin_unconnected(self):
        mock_sch = self._mock_sch()
        mock_sch.get_net_for_pin = MagicMock(side_effect=Exception("fail"))
        comp = ParsedComponent(reference="U1", value="IC", lib_id="Device:IC",
                               pins=[ParsedPin(number="1", name="VCC")])
        nets, unconnected = build_net_list(mock_sch, [comp])
        assert len(nets) == 0
        assert len(unconnected) == 1

    def test_returns_parsed_net_and_pin_connection_types(self):
        mock_sch = self._mock_sch()
        mock_net = MagicMock(name="VCC", labels=[], pins=[MagicMock(reference="U1")])
        mock_net.name = "VCC"
        mock_sch.get_net_for_pin = MagicMock(return_value=mock_net)
        comp = ParsedComponent(reference="U1", value="IC", lib_id="Device:IC",
                               pins=[ParsedPin(number="1", name="VCC")])
        nets, unconnected = build_net_list(mock_sch, [comp])
        assert all(isinstance(n, ParsedNet) for n in nets)
        assert all(isinstance(p, PinConnection) for p in unconnected)


class TestBuildMergedNetList:
    """Test build_merged_net_list() for hierarchical sheet merging (US-022)."""

    def _mock_sch(self, labels=None):
        mock = MagicMock()
        mock.labels = labels or []
        return mock

    def test_empty_sheet_pairs_returns_empty(self):
        """Empty input returns empty lists (US-022 AC8)."""
        from revlo.parser.connectivity import build_merged_net_list
        nets, unconnected = build_merged_net_list([])
        assert nets == []
        assert unconnected == []

    def test_single_sheet_delegates_to_build_net_list(self):
        """Single sheet delegates to build_net_list for efficiency (US-022 AC8)."""
        from revlo.parser.connectivity import build_merged_net_list

        mock_sch = self._mock_sch()
        mock_net = MagicMock(name="VCC", labels=[], pins=[MagicMock(reference="U1")])
        mock_net.name = "VCC"
        mock_sch.get_net_for_pin = MagicMock(return_value=mock_net)

        comp = ParsedComponent(reference="U1", value="IC", lib_id="Device:IC",
                               pins=[ParsedPin(number="1", name="VCC")])

        nets, unconnected = build_merged_net_list([(mock_sch, [comp])])

        assert len(nets) == 1
        assert nets[0].name == "VCC"

    def test_merges_nets_by_name_across_sheets(self):
        """Nets with same name are merged across sheets (US-022 AC7)."""
        from revlo.parser.connectivity import build_merged_net_list

        # First sheet with VCC net
        sch1 = self._mock_sch()
        net1 = MagicMock(name="VCC", labels=[], pins=[MagicMock(reference="U1")])
        net1.name = "VCC"
        sch1.get_net_for_pin = MagicMock(return_value=net1)
        comp1 = ParsedComponent(reference="U1", value="IC1", lib_id="Device:IC",
                                pins=[ParsedPin(number="1", name="VCC")])

        # Second sheet with VCC net
        sch2 = self._mock_sch()
        net2 = MagicMock(name="VCC", labels=[], pins=[MagicMock(reference="U2")])
        net2.name = "VCC"
        sch2.get_net_for_pin = MagicMock(return_value=net2)
        comp2 = ParsedComponent(reference="U2", value="IC2", lib_id="Device:IC",
                                pins=[ParsedPin(number="1", name="VCC")])

        nets, _ = build_merged_net_list([(sch1, [comp1]), (sch2, [comp2])])

        # Should have one merged VCC net
        assert len(nets) == 1
        assert nets[0].name == "VCC"
        # Should have pins from both sheets
        assert len(nets[0].pins) == 2
        refs = {p.component_ref for p in nets[0].pins}
        assert refs == {"U1", "U2"}

    def test_deduplicates_pins_across_sheets(self):
        """Duplicate pin connections are removed when merging (US-022 AC7)."""
        from revlo.parser.connectivity import build_merged_net_list

        # Same pin appears in both sheets (shouldn't happen in real data, but test robustness)
        sch1 = self._mock_sch()
        net1 = MagicMock(name="VCC", labels=[], pins=[MagicMock(reference="U1")])
        net1.name = "VCC"
        sch1.get_net_for_pin = MagicMock(return_value=net1)
        comp1 = ParsedComponent(reference="U1", value="IC", lib_id="Device:IC",
                                pins=[ParsedPin(number="1", name="VCC")])

        sch2 = self._mock_sch()
        net2 = MagicMock(name="VCC", labels=[], pins=[MagicMock(reference="U1")])
        net2.name = "VCC"
        sch2.get_net_for_pin = MagicMock(return_value=net2)
        comp2 = ParsedComponent(reference="U1", value="IC", lib_id="Device:IC",
                                pins=[ParsedPin(number="1", name="VCC")])

        nets, _ = build_merged_net_list([(sch1, [comp1]), (sch2, [comp2])])

        # Should deduplicate - only one pin connection
        assert len(nets) == 1
        assert len(nets[0].pins) == 1

    def test_merges_labels_across_sheets(self):
        """Net labels are merged and deduplicated (US-022 AC7)."""
        from revlo.parser.connectivity import build_merged_net_list

        # First sheet with label
        label1 = MagicMock(uuid="uuid1", text="VCC_MAIN")
        sch1 = self._mock_sch(labels=[label1])
        net1 = MagicMock(name="VCC", labels=["uuid1"], pins=[MagicMock(reference="U1")])
        net1.name = "VCC"
        sch1.get_net_for_pin = MagicMock(return_value=net1)
        comp1 = ParsedComponent(reference="U1", value="IC", lib_id="Device:IC",
                                pins=[ParsedPin(number="1", name="VCC")])

        # Second sheet with different label
        label2 = MagicMock(uuid="uuid2", text="VCC_SUB")
        sch2 = self._mock_sch(labels=[label2])
        net2 = MagicMock(name="VCC", labels=["uuid2"], pins=[MagicMock(reference="U2")])
        net2.name = "VCC"
        sch2.get_net_for_pin = MagicMock(return_value=net2)
        comp2 = ParsedComponent(reference="U2", value="IC", lib_id="Device:IC",
                                pins=[ParsedPin(number="1", name="VCC")])

        nets, _ = build_merged_net_list([(sch1, [comp1]), (sch2, [comp2])])

        # Should have both labels
        assert len(nets) == 1
        assert set(nets[0].labels) == {"VCC_MAIN", "VCC_SUB"}

    def test_power_classification_promoted_across_sheets(self):
        """If any sheet classifies a net as power, it's promoted to power (US-022 AC7)."""
        from revlo.parser.connectivity import build_merged_net_list

        # First sheet: VCC is signal (no power symbol)
        sch1 = self._mock_sch()
        net1 = MagicMock(name="VCC", labels=[], pins=[MagicMock(reference="U1")])
        net1.name = "VCC"
        sch1.get_net_for_pin = MagicMock(return_value=net1)
        comp1 = ParsedComponent(reference="U1", value="IC", lib_id="Device:IC",
                                pins=[ParsedPin(number="1", name="VCC")])

        # Second sheet: VCC has power symbol (classified as power)
        sch2 = self._mock_sch()
        net2 = MagicMock(name="VCC", labels=[], pins=[
            MagicMock(reference="#PWR001"),
            MagicMock(reference="U2"),
        ])
        net2.name = "VCC"
        sch2.get_net_for_pin = MagicMock(return_value=net2)
        comp2 = ParsedComponent(reference="U2", value="IC", lib_id="Device:IC",
                                pins=[ParsedPin(number="1", name="VCC")])
        pwr = ParsedComponent(reference="#PWR001", value="VCC", lib_id="power:VCC",
                              pins=[ParsedPin(number="1", name="VCC")])

        nets, _ = build_merged_net_list([(sch1, [comp1]), (sch2, [comp2, pwr])])

        # Should be classified as power
        assert len(nets) == 1
        assert nets[0].is_power is True

    def test_unconnected_pins_collected_from_all_sheets(self):
        """Unconnected pins from all sheets are collected (US-022 AC7)."""
        from revlo.parser.connectivity import build_merged_net_list

        # Sheet 1: U1 pin 1 unconnected
        sch1 = self._mock_sch()
        sch1.get_net_for_pin = MagicMock(return_value=None)
        comp1 = ParsedComponent(reference="U1", value="IC", lib_id="Device:IC",
                                pins=[ParsedPin(number="1", name="NC")])

        # Sheet 2: U2 pin 2 unconnected
        sch2 = self._mock_sch()
        sch2.get_net_for_pin = MagicMock(return_value=None)
        comp2 = ParsedComponent(reference="U2", value="IC", lib_id="Device:IC",
                                pins=[ParsedPin(number="2", name="NC")])

        _, unconnected = build_merged_net_list([(sch1, [comp1]), (sch2, [comp2])])

        # Should have unconnected pins from both sheets
        assert len(unconnected) == 2
        refs = {(p.component_ref, p.pin_number) for p in unconnected}
        assert refs == {("U1", "1"), ("U2", "2")}
