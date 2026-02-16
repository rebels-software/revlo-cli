"""Test suite for kicad-cli netlist export and parsing."""

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from revlo.parser import NetlistData, build_nets_from_netlist, parse_schematic, try_export_netlist
from revlo.parser.models import ParsedComponent, ParsedPin
from revlo.parser.netlist import detect_kicad_cli, export_netlist, parse_netlist


FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestDetectKicadCli:
    """Test kicad-cli detection logic."""

    def test_detect_from_path(self):
        """kicad-cli on PATH is detected."""
        with patch("revlo.parser.netlist.shutil.which") as mock_which:
            mock_which.return_value = "/usr/local/bin/kicad-cli"
            result = detect_kicad_cli()
            assert result == "/usr/local/bin/kicad-cli"

    def test_detect_macos_fallback(self):
        """macOS install path is checked when not on PATH."""
        with patch("revlo.parser.netlist.shutil.which") as mock_which, \
             patch("revlo.parser.netlist.platform.system") as mock_platform, \
             patch("revlo.parser.netlist.Path.is_file") as mock_is_file:
            mock_which.return_value = None
            mock_platform.return_value = "Darwin"
            mock_is_file.return_value = True
            result = detect_kicad_cli()
            assert result == "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"

    def test_detect_none_when_unavailable(self):
        """Returns None when kicad-cli is not found."""
        with patch("revlo.parser.netlist.shutil.which") as mock_which, \
             patch("revlo.parser.netlist.platform.system") as mock_platform:
            mock_which.return_value = None
            mock_platform.return_value = "Linux"
            result = detect_kicad_cli()
            assert result is None


class TestExportNetlist:
    """Test kicad-cli netlist export subprocess call."""

    def test_export_success(self, tmp_path):
        """Successful netlist export returns file content."""
        with patch("revlo.parser.netlist.subprocess.run") as mock_run, \
             patch("revlo.parser.netlist.Path.is_file") as mock_is_file, \
             patch("revlo.parser.netlist.Path.read_text") as mock_read:
            mock_run.return_value = Mock(returncode=0, stderr="")
            mock_is_file.return_value = True
            mock_read.return_value = "(export (nets))"

            result = export_netlist("/usr/bin/kicad-cli", "test.kicad_sch")
            assert result == "(export (nets))"

    def test_export_nonzero_return_code(self):
        """Non-zero return code returns None."""
        with patch("revlo.parser.netlist.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stderr="error")
            result = export_netlist("/usr/bin/kicad-cli", "test.kicad_sch")
            assert result is None

    def test_export_timeout(self):
        """Timeout returns None."""
        from subprocess import TimeoutExpired
        with patch("revlo.parser.netlist.subprocess.run") as mock_run:
            mock_run.side_effect = TimeoutExpired(cmd="kicad-cli", timeout=60)
            result = export_netlist("/usr/bin/kicad-cli", "test.kicad_sch")
            assert result is None


class TestParseNetlist:
    """Test .net file parsing logic."""

    def test_parse_empty_content(self):
        """Empty content returns empty NetlistData."""
        result = parse_netlist("")
        assert result.pin_nets == {}

    def test_parse_no_nets_section(self):
        """Content without (nets section returns empty NetlistData."""
        content = "(export (version E) (components))"
        result = parse_netlist(content)
        assert result.pin_nets == {}

    def test_parse_single_net(self):
        """Single net with two nodes is parsed correctly."""
        content = '''
        (nets
          (net (code "1") (name "+3V3")
            (node (ref "C1") (pin "1"))
            (node (ref "U1") (pin "6"))))
        '''
        result = parse_netlist(content)
        assert result.pin_nets == {
            ("C1", "1"): "+3V3",
            ("U1", "6"): "+3V3",
        }

    def test_parse_skips_unconnected_nets(self):
        """Nets starting with 'unconnected-' are skipped."""
        content = '''
        (nets
          (net (code "1") (name "GND")
            (node (ref "C1") (pin "2")))
          (net (code "2") (name "unconnected-(C4-Pad2)")
            (node (ref "C4") (pin "2"))))
        '''
        result = parse_netlist(content)
        assert result.pin_nets == {("C1", "2"): "GND"}
        assert ("C4", "2") not in result.pin_nets

    def test_parse_skips_empty_pin_numbers(self):
        """Nodes with empty pin numbers are skipped."""
        content = '''
        (nets
          (net (code "9") (name "Net-(U1-PA28)")
            (node (ref "U1") (pin ""))
            (node (ref "U1") (pin "3"))))
        '''
        result = parse_netlist(content)
        # Pin "" should be skipped, pin "3" should be mapped
        assert result.pin_nets == {("U1", "3"): "Net-(U1-PA28)"}

    def test_parse_multiple_nets(self):
        """Multiple nets are parsed and deduplicated."""
        content = '''
        (nets
          (net (code "1") (name "+3V3")
            (node (ref "C1") (pin "1"))
            (node (ref "U1") (pin "6")))
          (net (code "2") (name "GND")
            (node (ref "C1") (pin "2"))
            (node (ref "R2") (pin "1"))
            (node (ref "U1") (pin "7"))))
        '''
        result = parse_netlist(content)
        assert result.pin_nets == {
            ("C1", "1"): "+3V3",
            ("U1", "6"): "+3V3",
            ("C1", "2"): "GND",
            ("R2", "1"): "GND",
            ("U1", "7"): "GND",
        }


class TestParseMSPM0Fixture:
    """Test parsing the real MSPM0-simple-pcb.net fixture."""

    @pytest.fixture
    def fixture_content(self) -> str:
        """Load the MSPM0 netlist fixture."""
        fixture_path = FIXTURES_DIR / "MSPM0-simple-pcb.net"
        return fixture_path.read_text()

    def test_parse_mspm0_fixture(self, fixture_content):
        """Parse the MSPM0 fixture and verify key connections."""
        result = parse_netlist(fixture_content)

        # U1 pin 6 (VDD) → +3V3
        assert result.pin_nets.get(("U1", "6")) == "+3V3"

        # U1 pin 7 (VSS) → GND
        assert result.pin_nets.get(("U1", "7")) == "GND"

        # R2 pin 1 → GND
        assert result.pin_nets.get(("R2", "1")) == "GND"

        # R2 pin 2 → /ROSC
        assert result.pin_nets.get(("R2", "2")) == "/ROSC"

        # C1 pin 1 → +3V3
        assert result.pin_nets.get(("C1", "1")) == "+3V3"

        # C1 pin 2 → GND
        assert result.pin_nets.get(("C1", "2")) == "GND"

        # C4 pin 2 should NOT be in pin_nets (it's unconnected)
        assert ("C4", "2") not in result.pin_nets

    def test_mspm0_net_count(self, fixture_content):
        """MSPM0 fixture should have 9 named nets (non-unconnected)."""
        result = parse_netlist(fixture_content)
        unique_nets = set(result.pin_nets.values())

        # Expected nets: +1V35, +3V3, /HFXIN, /HFXOUT, /NRST, /ROSC, /VREF+, GND, Net-(U1-PA28)
        expected_nets = {"+1V35", "+3V3", "/HFXIN", "/HFXOUT", "/NRST", "/ROSC", "/VREF+", "GND", "Net-(U1-PA28)"}
        assert unique_nets == expected_nets

    def test_mspm0_pin_count(self, fixture_content):
        """Count total connected pins in MSPM0 fixture."""
        result = parse_netlist(fixture_content)
        # Expected: ~28 connected pins (U1 has 48 pins, most are unconnected in this simple design)
        # Let's count exactly what's in the netlist (non-unconnected pins)
        # From the fixture: we can see 9 nets with multiple pins each
        # The exact count depends on the fixture, but it should be > 20 and < 40
        assert len(result.pin_nets) >= 20
        assert len(result.pin_nets) <= 40


class TestBuildNetsFromNetlist:
    """Test building ParsedNet list from NetlistData."""

    def test_build_nets_basic(self):
        """Build nets from simple NetlistData."""
        netlist = NetlistData(pin_nets={
            ("C1", "1"): "+3V3",
            ("U1", "6"): "+3V3",
            ("C1", "2"): "GND",
            ("U1", "7"): "GND",
        })

        components = [
            ParsedComponent(
                reference="C1",
                value="10u",
                lib_id="Device:C",
                footprint="C_0805",
                position=(0, 0),
                rotation=0.0,
                pins=[
                    ParsedPin(number="1", name="", position=(0, 0), electrical_type="passive", connected_net=None),
                    ParsedPin(number="2", name="", position=(0, 0), electrical_type="passive", connected_net=None),
                ],
                properties={},
                source_sheet="",
            ),
            ParsedComponent(
                reference="U1",
                value="MCU",
                lib_id="MCU:MCU",
                footprint="LQFP",
                position=(0, 0),
                rotation=0.0,
                pins=[
                    ParsedPin(number="6", name="VDD", position=(0, 0), electrical_type="power_in", connected_net=None),
                    ParsedPin(number="7", name="VSS", position=(0, 0), electrical_type="power_in", connected_net=None),
                ],
                properties={},
                source_sheet="",
            ),
        ]

        nets, unconnected = build_nets_from_netlist(netlist, components)

        # Should have 2 nets: +3V3 and GND
        assert len(nets) == 2
        net_names = {n.name for n in nets}
        assert net_names == {"+3V3", "GND"}

        # +3V3 and GND should be classified as power nets
        for net in nets:
            assert net.is_power is True

        # No unconnected pins (all 4 pins are in netlist)
        assert len(unconnected) == 0

    def test_build_nets_identifies_unconnected_pins(self):
        """Pins not in netlist are added to unconnected list."""
        netlist = NetlistData(pin_nets={
            ("C4", "1"): "/NRST",
        })

        components = [
            ParsedComponent(
                reference="C4",
                value="470n",
                lib_id="Device:C",
                footprint="C_0805",
                position=(0, 0),
                rotation=0.0,
                pins=[
                    ParsedPin(number="1", name="", position=(0, 0), electrical_type="passive", connected_net=None),
                    ParsedPin(number="2", name="", position=(0, 0), electrical_type="passive", connected_net=None),
                ],
                properties={},
                source_sheet="",
            ),
        ]

        nets, unconnected = build_nets_from_netlist(netlist, components)

        # Pin 1 is connected, pin 2 is unconnected
        assert len(unconnected) == 1
        assert unconnected[0].component_ref == "C4"
        assert unconnected[0].pin_number == "2"

    def test_build_nets_power_classification(self):
        """Power net classification works via net name patterns."""
        netlist = NetlistData(pin_nets={
            ("R1", "1"): "+3V3",
            ("R1", "2"): "/ROSC",
            ("R2", "1"): "GND",
            ("R2", "2"): "signal_net",
        })

        components = [
            ParsedComponent(
                reference="R1",
                value="5k1",
                lib_id="Device:R",
                footprint="R_0603",
                position=(0, 0),
                rotation=0.0,
                pins=[
                    ParsedPin(number="1", name="", position=(0, 0), electrical_type="passive", connected_net=None),
                    ParsedPin(number="2", name="", position=(0, 0), electrical_type="passive", connected_net=None),
                ],
                properties={},
                source_sheet="",
            ),
            ParsedComponent(
                reference="R2",
                value="100k",
                lib_id="Device:R",
                footprint="R_0603",
                position=(0, 0),
                rotation=0.0,
                pins=[
                    ParsedPin(number="1", name="", position=(0, 0), electrical_type="passive", connected_net=None),
                    ParsedPin(number="2", name="", position=(0, 0), electrical_type="passive", connected_net=None),
                ],
                properties={},
                source_sheet="",
            ),
        ]

        nets, unconnected = build_nets_from_netlist(netlist, components)

        # Find each net and check power classification
        net_by_name = {n.name: n for n in nets}

        assert net_by_name["+3V3"].is_power is True
        assert net_by_name["GND"].is_power is True
        assert net_by_name["/ROSC"].is_power is False
        assert net_by_name["signal_net"].is_power is False


class TestTryExportNetlist:
    """Test convenience wrapper function."""

    def test_try_export_cli_not_found(self):
        """Returns None when kicad-cli is not found."""
        with patch("revlo.parser.netlist.detect_kicad_cli") as mock_detect:
            mock_detect.return_value = None
            result = try_export_netlist("test.kicad_sch")
            assert result is None

    def test_try_export_success(self):
        """Returns parsed NetlistData on success."""
        with patch("revlo.parser.netlist.detect_kicad_cli") as mock_detect, \
             patch("revlo.parser.netlist.export_netlist") as mock_export:
            mock_detect.return_value = "/usr/bin/kicad-cli"
            mock_export.return_value = '(nets (net (code "1") (name "GND") (node (ref "C1") (pin "2"))))'

            result = try_export_netlist("test.kicad_sch")
            assert result is not None
            assert result.pin_nets == {("C1", "2"): "GND"}

    def test_try_export_export_fails(self):
        """Returns None when export_netlist fails."""
        with patch("revlo.parser.netlist.detect_kicad_cli") as mock_detect, \
             patch("revlo.parser.netlist.export_netlist") as mock_export:
            mock_detect.return_value = "/usr/bin/kicad-cli"
            mock_export.return_value = None

            result = try_export_netlist("test.kicad_sch")
            assert result is None


class TestMSPM0NetlistIntegration:
    """Integration test: parse MSPM0 schematic with real netlist data."""

    @pytest.fixture
    def mspm0_netlist(self) -> NetlistData:
        """Load and parse the MSPM0 netlist fixture."""
        fixture_path = FIXTURES_DIR / "MSPM0-simple-pcb.net"
        content = fixture_path.read_text()
        return parse_netlist(content)

    def test_mspm0_schematic_with_netlist(self, mspm0_netlist):
        """Parse MSPM0 schematic with netlist data and verify connectivity."""
        sch_path = str(FIXTURES_DIR / "MSPM0-simple-pcb.kicad_sch")
        result = parse_schematic(sch_path, netlist=mspm0_netlist)

        # Find U1 (the MCU)
        u1 = next((c for c in result.components if c.reference == "U1"), None)
        assert u1 is not None

        # Find pin 6 (VDD) and pin 7 (VSS)
        pin6 = next((p for p in u1.pins if p.number == "6"), None)
        pin7 = next((p for p in u1.pins if p.number == "7"), None)
        assert pin6 is not None
        assert pin7 is not None

        # Verify connectivity via netlist (not kicad-sch-api)
        assert pin6.connected_net == "+3V3"
        assert pin7.connected_net == "GND"

        # Find R2
        r2 = next((c for c in result.components if c.reference == "R2"), None)
        assert r2 is not None
        r2_pin1 = next((p for p in r2.pins if p.number == "1"), None)
        r2_pin2 = next((p for p in r2.pins if p.number == "2"), None)
        assert r2_pin1.connected_net == "GND"
        assert r2_pin2.connected_net == "/ROSC"

        # Find C4 (capacitor with one floating pin)
        c4 = next((c for c in result.components if c.reference == "C4"), None)
        assert c4 is not None
        c4_pin2 = next((p for p in c4.pins if p.number == "2"), None)

        # C4:2 should be in unconnected_pins list
        unconnected_refs = [(u.component_ref, u.pin_number) for u in result.unconnected_pins]
        assert ("C4", "2") in unconnected_refs

    def test_mspm0_net_classification(self, mspm0_netlist):
        """Verify power net classification with netlist-based connectivity."""
        sch_path = str(FIXTURES_DIR / "MSPM0-simple-pcb.kicad_sch")
        result = parse_schematic(sch_path, netlist=mspm0_netlist)

        # Find key nets
        net_by_name = {n.name: n for n in result.nets}

        # Power nets
        assert "+3V3" in net_by_name
        assert net_by_name["+3V3"].is_power is True

        assert "GND" in net_by_name
        assert net_by_name["GND"].is_power is True

        assert "+1V35" in net_by_name
        assert net_by_name["+1V35"].is_power is True

        # Signal nets
        assert "/ROSC" in net_by_name
        assert net_by_name["/ROSC"].is_power is False

        assert "/NRST" in net_by_name
        assert net_by_name["/NRST"].is_power is False
