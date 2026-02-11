# Revlo — Claude Code Planning Prompt

## What is Revlo?

Revlo is an AI-powered hardware review tool for KiCad projects. It targets hobbyists and small internal teams who don't have a senior EE to review their designs before fabrication. Users upload their KiCad project files and receive a structured review report with findings, severity levels, and actionable recommendations.

Think of it as **SonarQube or GitHub code review, but for PCB/schematic designs**.

Domain ideas: getrevlo.com, revlo.dev, revlo.io, userevlo.com

---

## Core Workflow

```
User uploads .kicad_sch / .kicad_pcb files
  → Python parser extracts structured data (components, nets, connections, traces)
  → Chunker breaks project into reviewable sections (per-IC, per-net, per-interface)
  → Review pipeline sends structured JSON to Claude API with specialized prompts
  → Report generator aggregates findings into a review report
  → User receives report (web UI / PDF / markdown)
```

---

## What Revlo Reviews (Prioritized)

### Layer 1 — Schematic Review (build first, highest value)
- Missing decoupling capacitors on ICs
- Unconnected/floating pins that should be connected
- Missing pull-up/pull-down resistors on buses (I2C, SPI, etc.)
- Voltage level mismatches between connected ICs
- Missing ESD protection on external interfaces (USB, Ethernet)
- Power sequencing issues
- Incorrect crystal/oscillator load capacitor values

### Layer 2 — PCB Layout Review (build second)
- Trace width vs current capacity mismatch
- Inadequate clearances (high-voltage, creepage)
- Ground plane splits under signal traces
- Decoupling cap placement too far from IC pins
- Thermal relief issues
- Antenna keep-out violations

### Layer 3 — BOM / Component Review (build third)
- Obsolete or end-of-life components
- Single-source risk
- Incorrect footprint-to-component mapping

### Layer 4 — Best Practices (build last)
- Testpoint placement suggestions
- Silkscreen readability
- Connector orientation consistency

---

## Datasheet Intelligence

A key differentiator: Revlo doesn't just review against generic rules — it cross-references **actual datasheets** for the specific components in your design. This is what a senior EE does manually.

### Datasheet Lookup Flow

```
Parsed component (e.g. "STM32F401CEU6", "ESP32-S3", "LM1117-3.3")
  → Normalize part number (strip package suffixes, aliases)
  → Check local cache (SQLite or filesystem)
  → Query external API (Octopart → DigiKey → Mouser → web search fallback)
  → Download PDF
  → Extract key sections via Claude:
      - Absolute maximum ratings
      - Recommended application circuit
      - Pin configuration / pin functions
      - Decoupling / bypass cap recommendations
      - Power supply requirements
      - I/O voltage levels
  → Cache extracted data as structured JSON
  → Feed into review prompts alongside schematic data
```

### Datasheet Sources (priority order)

1. **Octopart API** (free tier) — largest aggregator, returns datasheet PDF links, specs, lifecycle status
2. **DigiKey API** — official distributor, reliable PDFs, also provides stock/pricing for BOM checks
3. **Mouser API** — same as DigiKey, good redundancy
4. **Manufacturer direct** — TI, STMicro, NXP, Microchip, Espressif have predictable URL patterns for datasheets
5. **Web search fallback** — for obscure or niche components

### Datasheet Extraction Strategy

Full datasheets are too large to send to Claude (100+ pages). Extract and cache only:
- **Page detection**: Use Claude to identify which pages contain relevant sections (app circuit, max ratings, pinout)
- **Targeted extraction**: Send only those pages (as images or extracted text) for structured data extraction
- **Cache as JSON**: Store extracted specs per component so you never re-process the same datasheet twice

### What Datasheet Data Enables in Reviews

| Datasheet Info | Review Check |
|----------------|-------------|
| Recommended decoupling caps | Verify exact values match (not just "has a cap") |
| Absolute max voltage ratings | Flag nets that could exceed limits |
| Pin functions (GPIO/ADC/UART) | Verify pin assignments make sense for the design |
| Recommended application circuit | Compare user's circuit against reference design |
| I/O voltage levels | Catch level mismatches between ICs with real specs |
| Thermal pad requirements | Flag missing thermal vias or connections |

### Caching & Storage

- Cache datasheets locally (PDF + extracted JSON) per component
- Use part number as cache key (normalized)
- Datasheet JSON schema: `{ part_number, manufacturer, max_ratings: {}, pin_config: [], app_circuit_notes: [], decoupling: {}, io_levels: {} }`
- Pre-populate cache with the most common hobbyist components (STM32, ESP32, ATmega, RP2040, common LDOs, USB-C controllers)

---

## Claude Agent SDK — Revlo's Backbone

Revlo is built on the **Claude Agent SDK** (`claude-agent-sdk` Python package) — the same infrastructure that powers Claude Code, exposed as a library. Instead of raw API calls, we get the full agent loop, built-in tools, subagents, hooks, sessions, MCP servers, and context management out of the box.

**Docs:** https://platform.claude.com/docs/en/agent-sdk/overview
**Python SDK:** https://github.com/anthropics/claude-agent-sdk-python
**Demo agents:** https://github.com/anthropics/claude-agent-sdk-demos

### Why Agent SDK over raw Claude API?

- **Built-in agent loop** — no manual tool call → result → refine loops to write
- **Subagents** — define specialist EE reviewers that the orchestrator auto-delegates to via the `Task` tool
- **Custom tools via MCP** — define datasheet lookup, calculators, component DB queries as in-process MCP tools using `@tool` decorator
- **Hooks** — inject validation/logging at `PreToolUse`, `PostToolUse`, `Stop` events
- **Sessions** — multi-turn review conversations with full context retention
- **Built-in tools** — `Read`, `Bash`, `Grep`, `Glob`, `WebFetch`, `WebSearch` available immediately
- **Permission control** — fine-grained `canUseTool` callbacks to restrict what each agent can do
- **Context management** — automatic compaction when approaching context limits on large projects

### Architecture: Orchestrator + Specialist Subagents

```
                        ┌──────────────────────┐
                        │  Revlo Orchestrator   │  ← Main agent, routes to specialists
                        │  (Claude Opus/Sonnet) │     Merges findings, ranks severity
                        └──────────┬───────────┘
                                   │ Task tool (auto-delegation)
            ┌──────────┬───────────┼───────────┬──────────┐
            ▼          ▼           ▼           ▼          ▼
     ┌───────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
     │ Power     │ │ Signal  │ │ IC Pin  │ │ BOM &   │ │ Layout  │
     │ Supply    │ │ Integ.  │ │ Config  │ │ Lifecycle│ │ Review  │
     │ Subagent  │ │ Subagent│ │ Subagent│ │ Subagent│ │ Subagent│
     │ (Sonnet)  │ │ (Sonnet)│ │ (Sonnet)│ │ (Sonnet)│ │ (Sonnet)│
     └───────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘
          │              │           │           │           │
     [Custom MCP   [Custom MCP  [Custom MCP  [Octopart   [DRC calc
      tools]        tools]       tools]       MCP tool]    MCP tool]
```

### Subagent Definitions (Programmatic)

Each EE specialist is defined as a subagent via the `agents` parameter. The orchestrator auto-delegates to them via the `Task` tool based on their `description` field.

```python
from claude_agent_sdk import query, ClaudeAgentOptions

# Define specialist subagents
agents = {
    "power-supply-reviewer": {
        "description": "Expert power supply and voltage regulator reviewer. Use for LDO/DC-DC circuits, decoupling, bulk caps, power sequencing, and thermal derating analysis.",
        "prompt": open("revlo/skills/power_supply_review.md").read(),
        "tools": ["Read", "mcp__revlo__lookup_datasheet", "mcp__revlo__calc_power_dissipation"],
        "model": "sonnet",
    },
    "signal-integrity-reviewer": {
        "description": "Expert signal integrity reviewer. Use for I2C/SPI/UART/USB bus analysis, pull-up/pull-down calculations, termination, ESD protection, and differential pair review.",
        "prompt": open("revlo/skills/signal_integrity_review.md").read(),
        "tools": ["Read", "mcp__revlo__lookup_datasheet", "mcp__revlo__calc_pullup"],
        "model": "sonnet",
    },
    "ic-pin-config-reviewer": {
        "description": "Expert IC pin configuration reviewer. Use for MCU/FPGA pin assignments, peripheral mux conflicts, boot strapping, unused pin handling, and alternate function validation.",
        "prompt": open("revlo/skills/ic_pin_config_review.md").read(),
        "tools": ["Read", "mcp__revlo__lookup_datasheet"],
        "model": "sonnet",
    },
    "bom-lifecycle-reviewer": {
        "description": "Expert BOM and component lifecycle reviewer. Use for obsolescence checks, single-source risk, footprint-to-part validation, and availability analysis.",
        "prompt": open("revlo/skills/bom_lifecycle_review.md").read(),
        "tools": ["Read", "mcp__revlo__query_octopart", "mcp__revlo__query_digikey"],
        "model": "sonnet",
    },
    "pcb-layout-reviewer": {
        "description": "Expert PCB layout reviewer. Use for trace width/current analysis, ground plane review, component placement, clearance checks, and thermal design.",
        "prompt": open("revlo/skills/pcb_layout_review.md").read(),
        "tools": ["Read", "mcp__revlo__calc_trace_width", "mcp__revlo__calc_creepage"],
        "model": "sonnet",
    },
}
```

### Custom MCP Tools (In-Process)

Define Revlo-specific tools using the `@tool` decorator and `create_sdk_mcp_server`. These run in-process — no subprocess overhead.

```python
from claude_agent_sdk import tool, create_sdk_mcp_server

@tool("lookup_datasheet", "Get extracted datasheet specs for a component", {
    "part_number": str,
    "sections": list  # ["max_ratings", "app_circuit", "decoupling", "pin_config", "io_levels"]
})
async def lookup_datasheet(args):
    """Fetches cached datasheet data or triggers extraction pipeline."""
    specs = await datasheet_cache.get_or_extract(args["part_number"], args.get("sections"))
    return {"content": [{"type": "text", "text": json.dumps(specs)}]}

@tool("calc_power_dissipation", "Calculate power dissipation for a voltage regulator", {
    "vin": float, "vout": float, "load_current_ma": float, "package": str
})
async def calc_power_dissipation(args):
    pd = (args["vin"] - args["vout"]) * (args["load_current_ma"] / 1000)
    theta_ja = PACKAGE_THERMAL.get(args.get("package", "SOT-223"), 120)
    temp_rise = pd * theta_ja
    return {"content": [{"type": "text", "text": json.dumps({
        "power_dissipation_w": round(pd, 3),
        "estimated_temp_rise_c": round(temp_rise, 1),
        "exceeds_rating": temp_rise > 100
    })}]}

@tool("calc_pullup", "Calculate optimal pull-up resistor for a bus", {
    "bus_type": str, "vdd": float, "bus_capacitance_pf": float, "speed_khz": float
})
async def calc_pullup(args):
    """I2C/SPI pull-up calculation based on rise time and bus capacitance."""
    # ... calculation logic
    return {"content": [{"type": "text", "text": json.dumps(result)}]}

@tool("query_octopart", "Query Octopart API for component lifecycle and availability", {
    "part_number": str
})
async def query_octopart(args):
    """Queries Octopart for lifecycle status, stock, pricing, datasheet URL."""
    result = await octopart_client.search(args["part_number"])
    return {"content": [{"type": "text", "text": json.dumps(result)}]}

@tool("calc_trace_width", "Calculate required trace width for a given current", {
    "current_a": float, "copper_weight_oz": float, "temp_rise_c": float, "layer": str
})
async def calc_trace_width(args):
    """IPC-2152 trace width calculation."""
    # ... calculation logic
    return {"content": [{"type": "text", "text": json.dumps(result)}]}

# Bundle all tools into a single in-process MCP server
revlo_tools = create_sdk_mcp_server(
    name="revlo",
    version="1.0.0",
    tools=[lookup_datasheet, calc_power_dissipation, calc_pullup,
           query_octopart, calc_trace_width]
)
```

### Hooks for Validation & Logging

Use hooks to validate tool inputs, log usage for billing, and enforce safety:

```python
from claude_agent_sdk import ClaudeAgentOptions, HookContext

async def log_tool_usage(input_data, tool_use_id, context):
    """Log every tool call for billing and debugging."""
    await billing_db.record_tool_call(
        review_id=context.metadata.get("review_id"),
        tool_name=input_data["tool_name"],
        timestamp=datetime.utcnow()
    )
    return {}

async def validate_datasheet_lookup(input_data, tool_use_id, context):
    """Ensure part numbers are normalized before lookup."""
    if input_data["tool_name"] == "mcp__revlo__lookup_datasheet":
        part = input_data["tool_input"].get("part_number", "")
        normalized = normalize_part_number(part)
        input_data["tool_input"]["part_number"] = normalized
    return {}

hooks = {
    "PreToolUse": [
        {"callback": validate_datasheet_lookup},
        {"callback": log_tool_usage},
    ]
}
```

### Running a Full Review

The complete review pipeline using the Agent SDK:

```python
from claude_agent_sdk import query, ClaudeAgentOptions

async def run_review(kicad_sch_path: str) -> dict:
    """Run a full Revlo review on a KiCad schematic."""

    # 1. Parse schematic into structured JSON
    parsed = parse_schematic(kicad_sch_path)

    # 2. Build the orchestrator prompt with parsed data
    orchestrator_prompt = f"""
    You are the Revlo review orchestrator. You have received a parsed KiCad schematic.
    Your job is to delegate review tasks to your specialist subagents and produce a
    unified review report.

    Parsed schematic data:
    {json.dumps(parsed, indent=2)}

    Instructions:
    1. Identify which specialist reviewers are needed based on the components present
    2. Delegate to each relevant subagent using the Task tool
    3. Collect all findings
    4. Deduplicate, resolve conflicts, and rank by severity
    5. Output the final review as structured JSON
    """

    # 3. Run the orchestrator with subagents and custom tools
    options = ClaudeAgentOptions(
        model="sonnet",
        agents=agents,                    # Specialist subagents defined above
        mcp_servers={"revlo": revlo_tools},  # Custom MCP tools
        allowed_tools=[
            "Task",                       # Allows subagent delegation
            "mcp__revlo__lookup_datasheet",
            "mcp__revlo__query_octopart",
        ],
        hooks=hooks,
        permission_mode="bypassPermissions",  # Non-interactive server context
    )

    findings = []
    async for message in query(prompt=orchestrator_prompt, options=options):
        if hasattr(message, "result"):
            findings = json.loads(message.result)

    return findings
```

### EE Skill Files (Subagent System Prompts)

Each skill file is a markdown document loaded as the subagent's `prompt`. Stored in `revlo/skills/`:

```
revlo/skills/
├── base_ee_knowledge.md        # Shared EE fundamentals (appended to all subagent prompts)
├── power_supply_review.md      # Power supply subagent prompt + checklist
├── signal_integrity_review.md  # Signal integrity subagent prompt + checklist
├── ic_pin_config_review.md     # Pin config subagent prompt + checklist
├── bom_lifecycle_review.md     # BOM & lifecycle subagent prompt + checklist
├── pcb_layout_review.md        # PCB layout subagent prompt + checklist
└── orchestrator.md             # Orchestrator routing + merging instructions
```

Each skill file contains:
- **Role definition**: Persona + expertise scope
- **Review checklist**: Specific items to check with pass/fail criteria
- **Output JSON schema**: Structured format for findings (severity, component, issue, recommendation, reference)
- **Tool usage instructions**: When and how to call available MCP tools
- **Severity classification guide**: Error vs warning vs suggestion criteria
- **Few-shot examples**: 3-5 example findings demonstrating ideal output quality

### Specialist Subagent Details

**1. Power Supply Review Subagent**
- Scope: LDOs, DC-DC converters, voltage rails, decoupling, bulk caps
- MCP Tools: `lookup_datasheet`, `calc_power_dissipation`
- Checks: Input/output cap values vs datasheet, dropout voltage margins, power dissipation estimates, soft-start sequencing, enable pin handling

**2. Signal Integrity Subagent**
- Scope: I2C, SPI, UART, USB, Ethernet, high-speed buses
- MCP Tools: `lookup_datasheet`, `calc_pullup`
- Checks: Pull-up values for bus speed/capacitance, series termination resistors, ESD protection on external interfaces, differential pair matching

**3. IC Pin Configuration Subagent**
- Scope: MCU/FPGA pin assignments, peripheral mapping, boot configuration
- MCP Tools: `lookup_datasheet`
- Checks: Pin function conflicts (two peripherals on same pin), unconnected required pins, boot pin strapping resistors, unused pin handling

**4. BOM & Component Lifecycle Subagent**
- Scope: Component selection, availability, obsolescence, sourcing risk
- MCP Tools: `query_octopart`, `query_digikey`
- Checks: End-of-life / NRND status, single-source components, incorrect footprint-to-part mapping, lead time risks

**5. PCB Layout Review Subagent**
- Scope: Trace routing, copper pours, component placement, mechanical
- MCP Tools: `calc_trace_width`, `calc_creepage`, `lookup_datasheet`
- Checks: Trace width vs current, ground plane continuity, decoupling cap placement proximity, thermal relief

### Evaluation & Quality

Build an evaluation harness to measure agent quality:
- **Test projects**: Curate 20+ KiCad projects with known issues (intentionally flawed designs)
- **Ground truth**: Manually label each issue with severity and category
- **Metrics**: Precision (are flagged issues real?), Recall (did we catch all issues?), Severity accuracy
- **Per-subagent scoring**: Track which subagents perform well vs need skill tuning
- **Regression testing**: Run eval suite after any prompt/skill/tool changes
- **Cost tracking**: Use Agent SDK's built-in `total_cost_usd` and `usage` from subagent results

### Test Data Source

**Primary test project:** STM32F103CBT8_Devel reference design
- **Repo**: https://github.com/danielvilas/STM32-kicad-reference-designs
- **Path**: `STM32F1/STM32F103/STM32F103CBT8_Devel/`
- **Why**: Real hobbyist STM32 dev board with typical elements (LDO power supply, USB, SWD debug, crystal, decoupling caps, GPIO headers)
- **MCU**: STM32F103CBT8 (Cortex-M3, 72MHz, 128KB flash) — one of the most popular hobbyist MCUs

**What to review on this board:**
- Decoupling caps on VDD/VDDA pins (STM32F103 needs 4.7µF + 100nF per VDD)
- Crystal load capacitor values vs HSE specs
- USB data line resistors (22Ω series)
- Boot pin configuration (BOOT0/BOOT1 strapping)
- SWD connector pinout
- Power supply sequencing
- Reset circuit (100nF cap + 10kΩ pull-up typical)

**Note:** With `kicad-sch-api`'s built-in `are_pins_connected()` and `get_net_for_pin()`, many of these checks become simple:
```python
# Check if VDD has decoupling cap
vdd_net = sch.get_net_for_pin("U1", "VDD")
caps_on_vdd = [p for p in vdd_net.pins if "C" in p.component]
if not caps_on_vdd:
    findings.append(Finding(severity="error", message="Missing decoupling cap on VDD"))
```

**Additional test sources:**
- https://github.com/devnithw/stm32-devboard — another STM32F103C8T6 dev board
- Create intentionally flawed variants (missing caps, wrong pull-up values, floating pins) for eval

---

## Technical Architecture

### KiCad File Parsing
- KiCad files use S-expression format (plain text, parseable)
- Key files: `.kicad_sch` (schematic), `.kicad_pcb` (PCB layout), `.kicad_pro` (project settings)
- **Primary:** `kicad-sch-api` — modern Python library with built-in connectivity analysis, hierarchical support, and KiCAD library access
- **Fallback:** `kiutils` (v1.4.8+) for edge cases
- Extract: components (symbols), pins, nets, connections, properties, footprints, traces, zones

### Chunking Strategy (critical — full files are too large for one prompt)
- Per-IC review: IC + surrounding passives + connections
- Per-net review: trace a net across schematic and PCB
- Per-interface review: group related blocks (USB section, power supply, etc.)

### Claude Agent SDK Integration
- **Phase 1**: Use `query()` with a single monolithic prompt + `allowed_tools=["Read"]` (fast to build, validates concept)
- **Phase 2**: Add custom MCP tools (datasheet lookup, calculators) via `create_sdk_mcp_server`
- **Phase 3**: Migrate to multi-subagent architecture with orchestrator auto-delegating via `Task` tool
- **Sonnet** for specialist subagents (cost-efficient at scale)
- **Opus** optionally for orchestrator when reviewing complex multi-subsystem designs
- All subagent responses use structured JSON output schema
- Hooks handle validation, billing, and logging at `PreToolUse` / `PostToolUse` events

### Prompt Engineering (NOT fine-tuning — start here)
- Claude already knows EE fundamentals well
- Structured skills (subagent prompts) with checklists + few-shot examples get 80%+ accuracy
- The Agent SDK handles the agent loop, tool calling, and context management — focus your effort on writing great skill files
- Fine-tuning only makes sense later with 1000+ labeled review examples from real user projects

---

## Pricing Model

| Tier | Price | Reviews | Target User |
|------|-------|---------|-------------|
| Free | $0 | 2/month | Trial, acquisition |
| Maker | $9/mo | 10/month | Hobbyists with regular projects |
| Pro | $19/mo | 25/month | Serious hobbyists, freelancers |
| Team | $29/mo | 40/month, 3 seats | Small startups, student teams |
| Pay-per-review | $2/review | No subscription | Occasional users, 2-3 boards/year |

**Cost assumptions:**
- ~$0.20-0.30 per review (Claude Sonnet API: 23K input + 8.5K output tokens across subagents)
- Complex projects or cache misses: up to $0.50
- Datasheet caching is critical — cache hits save $0.20+ per review

**Margins (assuming 60% utilization):**
- Maker: 60-75% gross margin
- Pro: 65-75% gross margin
- Team: 55-70% gross margin
- Pay-per-review: 75-85% gross margin ✓ best

**Break-even:** ~15 paying users (mix of Maker + Pro + pay-per-review)

**Cost controls:**
- Pre-populate datasheet cache with top 100 hobbyist components (STM32, ESP32, ATmega, RP2040, common LDOs)
- Component count soft limits per tier (warn at 75+ components, hard limit at 150)
- Pay-per-review is the safety valve — best margins, no commitment

---

## Tech Stack

- **Frontend:** Nuxt.js 4 + shadcn-vue (pnpm)
  - **Framework**: Nuxt.js 4 (Vue 3, file-based routing, SSR/SSG)
  - **Package manager**: pnpm (or bun)
  - **UI Components**: shadcn-vue (Radix Vue primitives + Tailwind CSS)
  - **Styling**: Tailwind CSS 3
  - **State**: Pinia
  - **Forms**: VeeValidate + Zod
  - **File uploads**: vue-dropzone or native drag-and-drop
- **Backend:** Python 3.12+ (FastAPI), managed with **uv**
  - **Package manager**: uv (fast, Rust-based, replaces pip/poetry/venv)
  - **Init**: `uv init backend` creates `pyproject.toml`, `.python-version`, `uv.lock`
  - **Add deps**: `uv add fastapi anthropic kicad-sch-api kiutils pydantic`
  - **Run**: `uv run python -m revlo review ...` or `uv run fastapi dev`
  - **Lock**: `uv.lock` checked into git for reproducible installs
- **Parser:** kicad-sch-api (primary) + kiutils (fallback)
  - **Primary**: `kicad-sch-api` — https://github.com/circuit-synth/kicad-sch-api
    - Built-in connectivity analysis (`are_pins_connected`, `get_net_for_pin`, `get_connected_pins`)
    - Hierarchical design support (multi-sheet, signal tracing across sheets)
    - KiCAD library access for component validation
    - Exact format preservation (byte-perfect output)
    - Object-oriented API with modern collection classes
    - Already uses uv, MIT licensed
  - **Fallback**: `kiutils` — for edge cases or if kicad-sch-api doesn't handle a specific file
- **AI Runtime:** Claude Agent SDK (`claude-agent-sdk` Python package)
  - **Subagents**: 5 specialist EE reviewers + 1 orchestrator, auto-delegated via `Task` tool
  - **Custom MCP tools**: Datasheet lookup, EE calculators, component DB queries — all in-process via `@tool` decorator
  - **Hooks**: `PreToolUse` / `PostToolUse` for validation, billing, logging
  - **Built-in tools**: `Read`, `Bash`, `Grep`, `Glob`, `WebFetch`, `WebSearch`
  - **Sessions**: Multi-turn review with full context retention
  - **Permission control**: `canUseTool` callbacks to restrict subagent access
  - **Model routing**: Sonnet for subagents (cost-efficient), Opus for orchestrator if needed
- **Storage:** S3-compatible for uploaded KiCad projects
- **Database:** PostgreSQL (users, reviews, billing)
- **Auth:** Clerk (has official Nuxt module) or @sidebase/nuxt-auth
- **Payments:** Stripe
- **Deployment:** Vercel, Netlify, or Cloudflare Pages (frontend, all have Nuxt presets) + Railway/Fly.io (backend)

### kicad-sch-api — Why It's Perfect for Revlo

**Repo:** https://github.com/circuit-synth/kicad-sch-api
**PyPI:** `pip install kicad-sch-api`
**Docs:** https://kicad-sch-api.readthedocs.io

`kicad-sch-api` provides exactly what Revlo needs out of the box:

**1. Built-in Connectivity Analysis** — No need to write our own net tracer:
```python
# Check if two pins are electrically connected
if sch.are_pins_connected("R1", "2", "R2", "1"):
    print("Connected!")

# Get the net a pin belongs to
net = sch.get_net_for_pin("U1", "VDD")
print(f"Net: {net.name}, connected pins: {len(net.pins)}")

# Get all pins connected to a specific pin
connected = sch.get_connected_pins("R1", "2")
for pin in connected:
    print(f"  {pin.component}:{pin.pin}")
```

Connectivity analysis includes: direct wire connections, junctions, local/global labels, hierarchical labels (cross-sheet), power symbols (VCC, GND), and sheet pins.

**2. Hierarchical Design Support** — Multi-sheet projects:
```python
# Build hierarchy tree
tree = sch.hierarchy.build_hierarchy_tree(sch, schematic_path)

# Trace signals across sheets
paths = sch.hierarchy.trace_signal_path("VCC")

# Validate sheet pin connections
errors = sch.hierarchy.get_validation_errors()
```

**3. KiCAD Library Access** — Validate components against real symbol libraries:
```python
cache = ksa.library.get_symbol_cache()
cache.discover_libraries(["/path/to/kicad/symbols"])

# Now component lookups use real library data
```

**4. Component Property Management** — Access all component metadata:
```python
comp = sch.components.get("U1")
print(comp.reference, comp.value, comp.lib_id, comp.footprint)

# Get all properties
for prop_name, prop_value in comp.properties.items():
    print(f"  {prop_name}: {prop_value}")
```

**5. Pin Discovery** — Essential for EE review:
```python
# Get all pins for a component
pins = sch.get_component_pins("U1")
for pin in pins:
    print(f"{pin.name} ({pin.type}): pos={pin.position}")

# Find pins by type (power, input, output, passive)
power_pins = sch.find_pins_by_type("U1", "power_in")
```

**Bonus: MCP Server** — The library includes an MCP server with 15 tools. We could potentially expose this to users or use it for schematic manipulation if needed.

### Frontend Structure (Nuxt.js 4 + shadcn-vue)

```
frontend/
├── nuxt.config.ts
├── app.vue
├── pages/
│   ├── index.vue              # Landing page
│   ├── login.vue              # Auth
│   ├── dashboard.vue          # User dashboard, review history
│   └── review/
│       └── [id].vue           # Review results page
├── components/
│   ├── ui/                    # shadcn-vue components (auto-imported)
│   │   ├── button/
│   │   ├── card/
│   │   ├── badge/
│   │   ├── alert/
│   │   ├── dialog/
│   │   └── ...
│   ├── upload/
│   │   └── KicadDropzone.vue  # Drag-and-drop .kicad_sch/.kicad_pcb upload
│   ├── review/
│   │   ├── FindingCard.vue    # Single finding with severity badge
│   │   ├── FindingsList.vue   # Grouped findings by component/category
│   │   ├── SeveritySummary.vue # Error/warning/suggestion counts
│   │   └── ReviewProgress.vue  # Real-time progress during review
│   └── layout/
│       ├── Navbar.vue
│       └── Footer.vue
├── composables/
│   ├── useReview.ts           # Review API calls + state
│   └── useAuth.ts             # Auth state
├── server/
│   └── api/                   # Nuxt server routes (proxy to FastAPI or light endpoints)
├── stores/
│   └── review.ts              # Pinia store for review state
├── assets/
│   └── css/
│       └── main.css           # Tailwind imports + shadcn-vue theme
├── lib/
│   └── utils.ts               # cn() helper for shadcn-vue
├── tailwind.config.ts
└── components.json            # shadcn-vue config
```

**Key shadcn-vue components for Revlo:**
- `Badge` — severity indicators (error/warning/suggestion)
- `Card` — finding cards, review summary
- `Alert` — inline warnings and errors
- `Dialog` — confirmation modals, review details
- `Progress` — review progress bar
- `Tabs` — switch between schematic/PCB/BOM findings
- `Collapsible` — expand/collapse finding details
- `Tooltip` — component reference tooltips

---

## Implementation Order

1. **KiCad schematic parser** — parse `.kicad_sch` into structured JSON (components, nets, pins, connections)
2. **Single review prompt** — get one schematic review working end-to-end with Claude Agent SDK (monolithic prompt, validates the concept)
3. **CLI tool** — `revlo review myproject.kicad_sch` outputs findings to terminal/markdown
4. **Datasheet intelligence** — Octopart API integration, PDF download, Claude-based extraction, local caching
5. **Enhanced reviews with datasheet context** — feed extracted datasheet specs into review prompts for component-specific validation
6. **EE Skills authoring** — write the skill files (system prompts) for each specialist domain: power, signal, pins, BOM, layout
7. **Agent framework** — build custom MCP tools, subagent definitions, hooks using Claude Agent SDK
8. **Specialist subagents** — implement each subagent (power → signal → pins → BOM → layout) one at a time, testing each before moving on
9. **Orchestrator** — build the top-level prompt that uses `Task` tool to delegate to subagents and merge findings
10. **Evaluation harness** — create test projects with known issues, label ground truth, measure precision/recall per subagent
11. **Nuxt.js frontend** — scaffold with `nuxi init`, add shadcn-vue, build upload UI + review results page
12. **FastAPI backend** — REST endpoints for upload, review trigger, results retrieval, webhook for async reviews
13. **PCB layout review** — add `.kicad_pcb` parsing and wire up the layout subagent
14. **Billing** — Stripe integration with tiered pricing
15. **Polish** — PDF reports, severity filtering, review history, dashboard

---

## Your Task (Claude Code)

Start with steps 1-3, then move to 4-5, then 6-10:

**Phase 1 — Core Review Pipeline:**

0. Set up the backend project with uv:
   ```bash
   cd revlo && uv init backend
   cd backend
   uv add fastapi uvicorn anthropic kicad-sch-api pydantic httpx
   uv add kiutils  # Fallback parser
   uv add --dev pytest pytest-asyncio ruff
   ```

1. Build a Python KiCad schematic parser using `kicad-sch-api` that extracts structured JSON from `.kicad_sch` files. Use the library's built-in features:
   ```python
   import kicad_sch_api as ksa
   
   # Load schematic
   sch = ksa.load_schematic("project.kicad_sch")
   
   # Get all components with properties
   for comp in sch.components.all():
       print(f"{comp.reference}: {comp.lib_id}, value={comp.value}")
       for pin in sch.get_component_pins(comp.reference):
           print(f"  Pin {pin.name}: {pin.position}")
   
   # Built-in connectivity analysis
   if sch.are_pins_connected("R1", "2", "C1", "1"):
       print("R1 pin 2 connected to C1 pin 1")
   
   # Get net for a pin
   net = sch.get_net_for_pin("U1", "VDD")
   print(f"Power net: {net.name}")
   
   # Get all pins connected to a specific pin
   connected = sch.get_connected_pins("R1", "2")
   ```
   
   The output JSON should include: all components (reference, value, lib_id, footprint, properties, pin positions), all nets and their connections, power symbols, hierarchical sheets, and unconnected pins. Fall back to `kiutils` if kicad-sch-api fails to parse a specific file.

2. Build a review engine module that takes the parsed JSON, chunks it into reviewable sections, sends each to the Claude API with a structured review prompt (Layer 1 checks), and aggregates the findings into a report.

3. Wire it up as a CLI: `uv run python -m revlo review <path_to_kicad_sch>` that outputs a markdown review report. Test on the STM32F103CBT8_Devel project from https://github.com/danielvilas/STM32-kicad-reference-designs

**Phase 2 — Datasheet Intelligence:**

4. Build a datasheet lookup module: takes a component part number, normalizes it, queries Octopart API (free tier), downloads the PDF, and caches it locally.

5. Build a datasheet extractor: sends key pages of the PDF to Claude, extracts structured JSON (max ratings, recommended app circuit, decoupling requirements, pin config, I/O levels), and caches the extracted data.

6. Enhance the review prompts to include datasheet context: instead of generic "check for decoupling caps", the prompt now says "STM32F401 datasheet recommends 4.7µF + 100nF on each VDD pin — verify this matches."

**Phase 3 — EE Subagents via Claude Agent SDK:**

7. Install the Claude Agent SDK: `uv add claude-agent-sdk`. Author the EE skill files in `revlo/skills/`. Start with `base_ee_knowledge.md` (shared EE fundamentals), then write `power_supply_review.md` as the first specialist skill. Each skill file defines: role/persona, review checklist with pass/fail criteria, output JSON schema, tool usage instructions, severity classification guide, and 3-5 few-shot example findings.

8. Build custom MCP tools using `@tool` decorator and `create_sdk_mcp_server`: `lookup_datasheet`, `calc_power_dissipation`, `calc_pullup`, `query_octopart`, `calc_trace_width`. These run in-process with no subprocess overhead.

9. Define specialist subagents programmatically via the `agents` parameter in `ClaudeAgentOptions`. Start with the Power Supply subagent — it's the most impactful and testable. Each subagent gets: a skill file as its `prompt`, restricted `tools` list (only MCP tools it needs), and `model: "sonnet"`. Verify it produces good findings on test projects before building the next. Then: Signal Integrity → IC Pin Config → BOM & Lifecycle → PCB Layout.

10. Build the orchestrator. It receives the full parsed project, uses `Task` tool to auto-delegate to subagents based on their `description` fields, collects findings, deduplicates, and produces the final ranked report. Use `permission_mode="bypassPermissions"` for non-interactive server context.

11. Add hooks: `PreToolUse` for part number normalization and input validation, `PostToolUse` for billing/logging. Wire up cost tracking using the Agent SDK's built-in `total_cost_usd` and `usage` from subagent results.

12. Build the evaluation harness in `eval/`. Create 5+ test KiCad projects with intentionally planted issues. Label ground truth findings. Measure per-subagent precision and recall. Run this after every skill/tool change to catch regressions.

**Phase 4 — Nuxt.js Frontend:**

13. Scaffold the frontend:
    ```bash
    npx nuxi init frontend
    cd frontend && pnpm install
    npx shadcn-vue@latest init
    ```
    Configure Tailwind with Revlo brand colors from the brand book (Deep Navy `#0A1628`, Electric Teal `#00D4AA`, etc.).

14. Build the upload flow: `KicadDropzone.vue` component with drag-and-drop for `.kicad_sch` / `.kicad_pcb` files. On upload, POST to FastAPI backend, show `ReviewProgress.vue` with real-time status (parsing → reviewing → complete).

15. Build the review results page (`pages/review/[id].vue`): `SeveritySummary.vue` at top (error/warning/suggestion counts with colored badges), `FindingsList.vue` below grouped by component or category, each `FindingCard.vue` expandable with full details + datasheet references.

16. Build the dashboard (`pages/dashboard.vue`): review history table, usage stats, upgrade CTA for free tier users.

17. Wire up auth (Clerk or Auth.js) and Stripe billing portal integration.

**Tip:** Start with CLI (Phase 1-3) for early validation — share on Reddit/HackerNews EE communities before investing in the full web app. The CLI can become your power-user tool even after the web app launches.

Use a clean project structure (monorepo with backend + frontend):
```
revlo/
├── backend/                   # Python FastAPI backend (uv-managed)
│   ├── pyproject.toml         # uv project config + dependencies
│   ├── uv.lock                # Lockfile (commit to git)
│   ├── .python-version        # Python version (e.g., 3.12)
│   ├── revlo/
│   │   ├── __init__.py
│   │   ├── parser/
│   │   │   ├── __init__.py
│   │   │   ├── schematic.py      # Main parser using kicad-sch-api
│   │   │   ├── connectivity.py   # Wrapper around kicad-sch-api connectivity
│   │   │   ├── fallback.py       # kiutils fallback for edge cases
│   │   │   └── models.py         # Pydantic models for parsed output
│   │   ├── datasheets/
│   │   │   ├── __init__.py
│   │   │   ├── lookup.py          # API lookups (Octopart, DigiKey, Mouser, web fallback)
│   │   │   ├── extractor.py       # PDF → structured JSON extraction via Claude
│   │   │   ├── cache.py           # Local cache management (SQLite + filesystem)
│   │   │   └── normalizer.py      # Part number normalization and alias resolution
│   │   ├── skills/                # Subagent system prompts (markdown files)
│   │   │   ├── base_ee_knowledge.md
│   │   │   ├── power_supply_review.md
│   │   │   ├── signal_integrity_review.md
│   │   │   ├── ic_pin_config_review.md
│   │   │   ├── bom_lifecycle_review.md
│   │   │   ├── pcb_layout_review.md
│   │   │   └── orchestrator.md
│   │   ├── agents/
│   │   │   ├── __init__.py
│   │   │   ├── definitions.py    # Subagent definitions (agents dict)
│   │   │   ├── tools.py           # Custom MCP tools (@tool + create_sdk_mcp_server)
│   │   │   └── hooks.py           # PreToolUse/PostToolUse hooks
│   │   ├── reviewer/
│   │   │   ├── __init__.py
│   │   │   ├── engine.py          # Review pipeline — calls query() with orchestrator
│   │   │   ├── prompts.py         # Legacy single-prompt path (Phase 1 fallback)
│   │   │   └── chunker.py         # Splits parsed data into review sections
│   │   ├── report/
│   │   │   ├── __init__.py
│   │   │   └── markdown.py        # Markdown report generator
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── main.py            # FastAPI app
│   │   │   ├── routes/
│   │   │   │   ├── reviews.py     # POST /reviews, GET /reviews/{id}
│   │   │   │   ├── upload.py      # POST /upload
│   │   │   │   └── billing.py     # Stripe webhooks
│   │   │   └── deps.py            # Dependency injection (db, auth)
│   │   └── cli.py                 # CLI entry point
│   ├── tests/
│   ├── eval/
│   │   ├── harness.py
│   │   ├── metrics.py
│   │   ├── projects/              # Test KiCad projects
│   │   │   ├── stm32f103_devel/   # Clone of danielvilas reference design
│   │   │   ├── stm32_devboard/    # Clone of devnithw board
│   │   │   ├── flawed_power/      # Intentionally broken power supply
│   │   │   ├── missing_caps/      # Missing decoupling caps
│   │   │   └── README.md
│   │   └── ground_truth/          # Expected findings per project (JSON)
│   ├── examples/
│   ├── .cache/
│   ├── pyproject.toml
│   └── README.md
│
├── frontend/                  # Nuxt.js 4 + shadcn-vue frontend (pnpm)
│   ├── nuxt.config.ts
│   ├── package.json
│   ├── pnpm-lock.yaml         # Lockfile (commit to git)
│   ├── app.vue
│   ├── pages/
│   │   ├── index.vue              # Landing page
│   │   ├── login.vue
│   │   ├── dashboard.vue
│   │   └── review/
│   │       └── [id].vue           # Review results
│   ├── components/
│   │   ├── ui/                    # shadcn-vue components
│   │   ├── upload/
│   │   │   └── KicadDropzone.vue
│   │   ├── review/
│   │   │   ├── FindingCard.vue
│   │   │   ├── FindingsList.vue
│   │   │   ├── SeveritySummary.vue
│   │   │   └── ReviewProgress.vue
│   │   └── layout/
│   ├── composables/
│   │   ├── useReview.ts
│   │   └── useAuth.ts
│   ├── stores/
│   │   └── review.ts              # Pinia store
│   ├── server/api/                # Nuxt server routes (optional proxy)
│   ├── assets/css/main.css
│   ├── lib/utils.ts               # cn() helper
│   ├── tailwind.config.ts
│   └── components.json            # shadcn-vue config
│
└── README.md                  # Monorepo root README
```
