"""Specialist EE agent definitions for the Claude Agent SDK multi-agent dispatch."""

from __future__ import annotations

from typing import Any

from revlo.skills import load_skill

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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def get_orchestrator_prompt() -> str:
    """Return the Team Lead orchestrator system prompt."""
    return load_skill("orchestrator")


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
