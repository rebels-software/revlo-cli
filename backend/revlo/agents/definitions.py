"""Specialist EE agent definitions.

The multi-agent Agent SDK dispatch has been replaced by a single direct
Claude API call using the comprehensive ``ee_review.md`` system prompt.

The old ``get_orchestrator_prompt()`` and ``get_all_agent_definitions()``
functions are kept for backward compatibility but are no longer used by
the review engine.
"""

from __future__ import annotations

from typing import Any

from revlo.skills import load_skill

# ---------------------------------------------------------------------------
# Agent name constants (kept for backward compat / reference)
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
def get_ee_system_prompt() -> str:
    """Return the comprehensive EE review system prompt."""
    return load_skill("ee_review")


def get_orchestrator_prompt() -> str:
    """Return the Team Lead orchestrator system prompt.

    .. deprecated::
        No longer used by the review engine. Kept for backward compatibility.
    """
    return load_skill("orchestrator")


def get_all_agent_definitions() -> dict[str, Any]:
    """Build and return all specialist agent definition dicts.

    .. deprecated::
        No longer used by the review engine. The Agent SDK multi-agent
        dispatch has been replaced by a single direct Claude API call.
        Kept for backward compatibility.

    Returns plain dicts instead of AgentDefinition objects to avoid
    requiring the claude_agent_sdk dependency.
    """
    base_prompt = load_skill("base_ee_knowledge")
    definitions: dict[str, dict[str, str]] = {}

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
        definitions[name] = {
            "description": _AGENT_DESCRIPTIONS[name],
            "prompt": base_prompt + "\n\n" + specialist_prompt,
            "model": "sonnet",
        }

    return definitions
