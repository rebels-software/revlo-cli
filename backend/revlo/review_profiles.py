"""Built-in review profile definitions for Revlo."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReviewProfileDefinition(BaseModel):
    """Shared configuration format for built-in review profiles."""

    name: str
    display_name: str
    prompt_preamble: str = ""
    enabled_rule_sets: list[str] = Field(default_factory=list)
    severity_weighting: dict[str, int] = Field(default_factory=dict)


_BUILTIN_REVIEW_PROFILES: dict[str, ReviewProfileDefinition] = {
    "generic": ReviewProfileDefinition(
        name="generic",
        display_name="Generic Hardware Review",
        prompt_preamble=(
            "Apply broad schematic-review judgment across power integrity, "
            "connectivity, reset, decoupling, and interface hygiene."
        ),
        enabled_rule_sets=["core_connectivity", "power_integrity", "datasheet_sanity"],
        severity_weighting={"connectivity": 3, "decoupling": 2, "power": 3},
    ),
    "mcu-board": ReviewProfileDefinition(
        name="mcu-board",
        display_name="MCU Board",
        prompt_preamble=(
            "Prioritize MCU bring-up risks: power-pin coverage, reset topology, "
            "clocking, boot straps, debug access, and common serial buses."
        ),
        enabled_rule_sets=["boot_config", "debug_access", "mcu_power", "reset_chain"],
        severity_weighting={"clock": 3, "decoupling": 3, "pull_up": 2, "reset": 3},
    ),
    "sensor-node": ReviewProfileDefinition(
        name="sensor-node",
        display_name="Sensor Node",
        prompt_preamble=(
            "Emphasize low-power operation, sensor interface correctness, analog "
            "signal cleanliness, and pull networks that affect sampling accuracy."
        ),
        enabled_rule_sets=["analog_frontend", "low_power", "sensor_interfaces"],
        severity_weighting={
            "component_value": 2,
            "grounding": 3,
            "power": 3,
            "signal_integrity": 2,
        },
    ),
    "power-supply": ReviewProfileDefinition(
        name="power-supply",
        display_name="Power Supply",
        prompt_preamble=(
            "Focus on regulator topology, feedback networks, stability components, "
            "input and output bulk capacitance, protection, and rail sequencing."
        ),
        enabled_rule_sets=["feedback_network", "protection", "regulator_topology"],
        severity_weighting={"grounding": 2, "power": 4, "thermal": 3},
    ),
}


def list_review_profile_names() -> list[str]:
    """Return built-in profile names sorted for stable validation."""
    return sorted(_BUILTIN_REVIEW_PROFILES)


def get_review_profile_definition(name: str) -> ReviewProfileDefinition:
    """Return a built-in profile definition by normalized name."""
    normalized = name.strip().lower()
    try:
        return _BUILTIN_REVIEW_PROFILES[normalized]
    except KeyError as exc:
        valid = ", ".join(list_review_profile_names())
        raise ValueError(
            f"Unknown review profile '{normalized}'. Valid profiles: {valid}"
        ) from exc
