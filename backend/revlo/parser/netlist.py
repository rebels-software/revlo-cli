"""KiCad CLI netlist export and parsing for ground-truth connectivity."""

from __future__ import annotations

import logging
import platform
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


def detect_kicad_cli() -> str | None:
    """Find kicad-cli binary. Check PATH, then known install paths."""
    # 1. shutil.which("kicad-cli")
    found = shutil.which("kicad-cli")
    if found:
        return found
    # 2. macOS: /Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
    if platform.system() == "Darwin":
        mac_path = Path("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")
        if mac_path.is_file():
            return str(mac_path)
    # 3. Windows: C:\Program Files\KiCad\*\bin\kicad-cli.exe
    if platform.system() == "Windows":
        import glob as globmod

        for match in globmod.glob(r"C:\Program Files\KiCad\*\bin\kicad-cli.exe"):
            return match
    return None


def export_netlist(kicad_cli: str, sch_path: str) -> str | None:
    """Run kicad-cli sch export netlist and return .net file content or None."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "output.net"
        try:
            result = subprocess.run(
                [kicad_cli, "sch", "export", "netlist", sch_path, "-o", str(out_path)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                logger.warning(
                    "kicad-cli export failed (rc=%d): %s",
                    result.returncode,
                    result.stderr[:500],
                )
                return None
            if not out_path.is_file():
                logger.warning("kicad-cli did not produce output file")
                return None
            return out_path.read_text(encoding="utf-8")
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("kicad-cli export error: %s", exc)
            return None


@dataclass
class NetlistData:
    """Parsed netlist data from kicad-cli export."""

    pin_nets: dict[tuple[str, str], str] = field(default_factory=dict)
    # (component_ref, pin_number) -> net_name


# Regex patterns for .net file parsing
_NET_NAME_RE = re.compile(r'\(name\s+"([^"]*)"\)')
_NODE_RE = re.compile(r'\(node\s+\(ref\s+"([^"]*)"\)\s+\(pin\s+"([^"]*)"\)')


def parse_netlist(content: str) -> NetlistData:
    """Parse (nets ...) section from .net file content.

    Extracts each (net ...) block, gets the net name and all (node ...) entries.
    Skips nets starting with "unconnected-" -- those pins are floating.
    """
    data = NetlistData()

    # Find the (nets ...) section
    nets_start = content.find("(nets")
    if nets_start == -1:
        return data

    # Walk through each (net ...) block using balanced-paren extraction
    idx = nets_start
    while True:
        net_start = content.find("(net ", idx)
        if net_start == -1:
            break

        # Balanced-paren extraction
        depth = 0
        net_end = net_start
        for i in range(net_start, len(content)):
            if content[i] == "(":
                depth += 1
            elif content[i] == ")":
                depth -= 1
                if depth == 0:
                    net_end = i + 1
                    break

        net_block = content[net_start:net_end]
        idx = net_end

        # Extract net name
        name_match = _NET_NAME_RE.search(net_block)
        if not name_match:
            continue
        net_name = name_match.group(1)

        # Skip unconnected nets
        if net_name.startswith("unconnected-"):
            continue

        # Extract all nodes
        for node_match in _NODE_RE.finditer(net_block):
            ref = node_match.group(1)
            pin = node_match.group(2)
            if pin:  # Skip empty pin numbers
                data.pin_nets[(ref, pin)] = net_name

    return data


def try_export_netlist(sch_path: str) -> NetlistData | None:
    """Detect kicad-cli, export + parse netlist. Returns None if unavailable."""
    cli = detect_kicad_cli()
    if not cli:
        logger.info("kicad-cli not found -- using fallback connectivity")
        return None
    logger.info("Found kicad-cli at %s", cli)
    content = export_netlist(cli, sch_path)
    if not content:
        return None
    return parse_netlist(content)
