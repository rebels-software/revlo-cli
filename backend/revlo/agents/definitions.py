"""Specialist EE agent definitions and chunk-to-agent routing logic."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from revlo.skills import load_skill

if TYPE_CHECKING:
    from revlo.reviewer.chunker import ReviewChunk

# ---------------------------------------------------------------------------
# Agent name constants
# ---------------------------------------------------------------------------
AGENT_NAMES = [
    "signal_integrity_review",
    "ic_pin_config_review",
    "bom_lifecycle_review",
    "interface_grounding_review",
    "power_supply_review",
    "pcb_layout_review",
]

# IC-context chunks always go to these agents.
_IC_ALWAYS = ["signal_integrity_review", "ic_pin_config_review", "bom_lifecycle_review"]

# Power-rail chunks always go to these agents.
_POWER_ALWAYS = ["power_supply_review", "pcb_layout_review"]

# ---------------------------------------------------------------------------
# Interface-net detection patterns (case-insensitive)
# ---------------------------------------------------------------------------
_INTERFACE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"USB|D\+|D-|DP|DM", re.IGNORECASE),
    re.compile(r"I2C|SDA|SCL", re.IGNORECASE),
    re.compile(r"SPI|MOSI|MISO|SCK|SCLK|CS", re.IGNORECASE),
    re.compile(r"CAN|CANH|CANL", re.IGNORECASE),
    re.compile(r"UART|TX|RX|TXD|RXD", re.IGNORECASE),
]


def _has_interface_nets(chunk: ReviewChunk) -> bool:
    """Return True if any net name in the chunk matches an interface pattern."""
    for net in chunk.nets:
        for pattern in _INTERFACE_PATTERNS:
            if pattern.search(net.name):
                return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def get_agents_for_chunk(chunk: ReviewChunk) -> list[str]:
    """Return the list of specialist agent names that should review *chunk*.

    Routing rules (from orchestrator.md):
    - ic_context -> signal_integrity, ic_pin_config, bom_lifecycle
                    + interface_grounding if interface nets detected
    - power_rail -> power_supply, pcb_layout
    """
    if chunk.chunk_type == "ic_context":
        agents = list(_IC_ALWAYS)
        if _has_interface_nets(chunk):
            agents.append("interface_grounding_review")
        return agents
    elif chunk.chunk_type == "power_rail":
        return list(_POWER_ALWAYS)
    else:
        # Unknown chunk type -- return empty so caller can fall back.
        return []


def get_all_agent_definitions() -> dict[str, Any]:
    """Build and return all specialist AgentDefinition objects.

    Imports ``claude_agent_sdk`` lazily to avoid import errors when the
    Claude Code CLI is not installed.

    Each agent prompt = base_ee_knowledge + specialist skill.
    """
    from claude_agent_sdk import AgentDefinition

    base_prompt = load_skill("base_ee_knowledge")
    definitions: dict[str, AgentDefinition] = {}

    _AGENT_DESCRIPTIONS = {
        "signal_integrity_review": "Signal integrity specialist: pull-ups, termination, ESD, impedance",
        "ic_pin_config_review": "IC pin config specialist: pin conflicts, boot, unused pins, debug",
        "bom_lifecycle_review": "BOM lifecycle specialist: EOL, sourcing, values, packages",
        "interface_grounding_review": "Interface and grounding specialist: USB, I2C, SPI, CAN, UART, ground planes",
        "power_supply_review": "Power supply specialist: regulators, caps, protection, thermal",
        "pcb_layout_review": "PCB layout specialist: trace width, ground plane, decoupling placement",
    }

    for name in AGENT_NAMES:
        specialist_prompt = load_skill(name)
        definitions[name] = AgentDefinition(
            description=_AGENT_DESCRIPTIONS[name],
            prompt=base_prompt + "\n\n" + specialist_prompt,
            model="sonnet",
        )

    return definitions
