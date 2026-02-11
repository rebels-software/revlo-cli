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
