"""Agent definitions for the Claude Agent SDK multi-agent dispatch."""

from revlo.agents.definitions import (
    AGENT_NAMES,
    get_all_agent_definitions,
    get_orchestrator_prompt,
)

__all__ = [
    "AGENT_NAMES",
    "get_all_agent_definitions",
    "get_orchestrator_prompt",
]
