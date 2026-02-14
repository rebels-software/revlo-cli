# Orchestrator Routing Logic

This file defines how the review engine routes schematic chunks to specialist agents and how findings are merged.

## Chunk-to-Agent Routing

### ic_context chunks

Every `ic_context` chunk is sent to these agents:
1. **signal_integrity_review** -- checks pull-ups, termination, ESD, impedance
2. **ic_pin_config_review** -- checks pin conflicts, boot config, unused pins, debug pins
3. **bom_lifecycle_review** -- checks component lifecycle, sourcing, values

Additionally, if the chunk contains nets matching any of these interface patterns, also route to **interface_grounding_review**:
- USB nets: net names containing "USB", "D+", "D-", "DP", "DM"
- I2C nets: net names containing "I2C", "SDA", "SCL"
- SPI nets: net names containing "SPI", "MOSI", "MISO", "SCK", "SCLK", "CS"
- CAN nets: net names containing "CAN", "CANH", "CANL"
- UART nets: net names containing "UART", "TX", "RX", "TXD", "RXD"

### power_rail chunks

Every `power_rail` chunk is sent to these agents:
1. **power_supply_review** -- checks regulators, caps, protection, thermal
2. **pcb_layout_review** -- checks trace width, ground plane, decoupling placement

## Finding Merge and Deduplication

When multiple agents return findings for the same chunk, apply these rules:

### Deduplication
- Two findings are considered duplicates if they share the same `component_ref` AND the same `category`.
- When duplicates are found, keep the finding with the **highest confidence** score.
- If confidence is equal, keep the finding with the **higher severity** (error > warning > suggestion).

### Severity Ranking
1. `error` (highest) -- design will fail or cause damage
2. `warning` (medium) -- reliability or performance risk
3. `suggestion` (lowest) -- best-practice improvement

### Merge Procedure
1. Collect all findings from all agents for a given chunk.
2. Group findings by (component_ref, category).
3. For each group with more than one finding, keep only the highest-priority finding per the rules above.
4. Sort final findings by severity (errors first), then by component_ref alphabetically.

## Agent Prompt Assembly

Each specialist agent prompt is assembled by concatenating:
1. `base_ee_knowledge.md` (shared EE fundamentals)
2. The specialist's own skill file (e.g., `power_supply_review.md`)
3. The serialized chunk data (components, nets, unconnected pins, datasheet specs)

This ensures every agent has baseline EE knowledge plus its domain-specific checklist.
