<div align="center">

```
                            ██████╗ ███████╗██╗   ██╗██╗      ██████╗ 
                            ██╔══██╗██╔════╝██║   ██║██║     ██╔═══██╗
                            ██████╔╝█████╗  ██║   ██║██║     ██║   ██║
                            ██╔══██╗██╔══╝  ╚██╗ ██╔╝██║     ██║   ██║
                            ██║  ██║███████╗ ╚████╔╝ ███████╗╚██████╔╝
                            ╚═╝  ╚═╝╚══════╝  ╚═══╝  ╚══════╝ ╚═════╝ 
```

[![Version](https://img.shields.io/badge/version-0.3.0-teal)](https://pypi.org/project/revlo-cli/)
[![Python](https://img.shields.io/pypi/pyversions/revlo-cli)](https://pypi.org/project/revlo-cli/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)

**Review your hardware before it reviews your wallet.**

*AI-powered design review for KiCad schematics*

</div>

## What is Revlo?

Revlo is a command-line tool that catches electrical engineering mistakes in KiCad schematics _before_ they become expensive PCB respins. Point it at a `.kicad_sch` file and get back actionable findings -- missing decoupling caps, wrong pull-up values, unterminated pins, power rail issues -- all verified against real datasheet specifications pulled automatically from the internet.

Revlo is currently an alpha-stage schematic review tool. The implemented runtime focuses on KiCad schematics, datasheet enrichment, terminal-first review workflows, and interactive Ask Mode.

## Features

- **KiCad 6/7/8/9 Parser** -- Extracts components, nets, connectivity, power symbols, and properties from `.kicad_sch` files
- **Hierarchical Sub-sheet Support** -- Recursively parses sub-sheets and resolves cross-sheet nets with instance-aware references
- **Ground-Truth Connectivity via `kicad-cli`** -- Uses KiCad's exported netlist when available, with automatic fallback to parser-derived connectivity
- **Datasheet Intelligence** -- Automatically fetches component datasheets, extracts specs with AI, and caches results locally
- **Comprehensive EE Review** -- Revlo reviews your design across decoupling, pull-ups, unused pins, reset circuits, clock/oscillator, signal integrity, power rails, grounding, ESD, and thermal concerns
- **Confidence-Scored Findings** -- Every finding includes a 0.0-1.0 confidence score so you can prioritize what matters
- **Interactive TUI Browser** -- Browse and filter findings in a full-screen terminal UI with severity highlighting
- **Ask Mode** -- Interactive chat with live access to your schematic via built-in tools
- **Deterministic Rule Engine** -- Built-in checks for power connectivity, decoupling, I2C pull-ups, library hygiene, and BOM coverage run without LLM calls
- **Custom Rule Packs** -- Project-local JSON rule packs execute alongside built-in checks with additive or override modes
- **Review Profiles** -- Built-in profiles (generic, MCU board, sensor node, power supply) tune prompts and severity weighting
- **Baseline & Waiver Tracking** -- Save baselines, classify findings as new/existing/waived/resolved across reviews
- **Schematic Diff Review** -- Compare two schematic revisions and tag change-driven findings
- **CI Integration** -- Non-interactive `check` command with severity/category thresholds and versioned JSON policy output
- **Sign-Off Reports** -- Export stakeholder-ready packets that separate unresolved issues from accepted risk
- **Investigation Mode** -- Focus Ask Mode on a specific finding with expanded tools: decoupling, power tree, reset chain, boot straps, interface bundles, and constraint analysis
- **Branded CLI Output** -- Progress bars, colour-coded severity cards, and a summary line at a glance
- **Review History** -- Every review and conversation is saved automatically; re-open past reviews without re-running
- **JSON & Markdown Export** -- Pipe structured output into your CI/CD pipeline or generate human-readable reports

## Quick Start

### Install

```bash
pip install revlo-cli
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install revlo-cli
```

### First Review

```bash
export OPENAI_API_KEY="sk-proj-..."
revlo review path/to/schematic.kicad_sch
```

That's it. Revlo parses the schematic, fetches datasheets, runs the AI review, and launches the interactive TUI.

## Requirements

- Python 3.11+
- An `OPENAI_API_KEY` (default provider) or `ANTHROPIC_API_KEY` for review and datasheet extraction
- KiCad schematic in modern `.kicad_sch` format

Optional:

- `kicad-cli` installed for more accurate net connectivity
- `MOUSER_API_KEY` and `FARNELL_API_KEY` for broader automatic datasheet lookup

## Configuration

Revlo reads configuration from a `revlo.toml` file in the project directory (or any parent). The file is optional -- all settings have sensible defaults.

```toml
[llm]
provider = "openai"           # "openai" (default) or "anthropic"
review_model = "gpt-5.4"      # Override the review model
extraction_model = "gpt-5.3"  # Override the datasheet extraction model
ask_model = "gpt-5.4"         # Override the Ask Mode model
datasheet_concurrency = 4     # Max concurrent datasheet fetches

[review]
profile = "generic"           # "generic", "mcu-board", "sensor-node", "power-supply"
```

You can also set the provider via environment variable:

```bash
export REVLO_LLM_PROVIDER="anthropic"   # Switch to Anthropic
export REVLO_REVIEW_MODEL="claude-opus-4-6"  # Override model
```

## Example Output

### CLI Progress

```
██████╗ ███████╗██╗   ██╗██╗      ██████╗
██╔══██╗██╔════╝██║   ██║██║     ██╔═══██╗
██████╔╝█████╗  ██║   ██║██║     ██║   ██║
██╔══██╗██╔══╝  ╚██╗ ██╔╝██║     ██║   ██║
██║  ██║███████╗ ╚████╔╝ ███████╗╚██████╔╝
╚═╝  ╚═╝╚══════╝  ╚═══╝  ╚══════╝ ╚═════╝ v0.1
AI-powered design review for KiCad schematics

■ Parsing schematic...
■ Found 47 components, 38 nets
■ Fetching datasheets... ████████████████████⢕⢕⢕⢕⢕⢕⢕⢕⢕⢕ 12/18
  U1: STM32F103CBT6 (fetched)
  U2: AMS1117-3.3 (cached)
  U3: CH340G (manual PDF)
■ Datasheets: 2 cached, 1 manual, 9 fetched, 0 failed
■ Running review...
Found 3 errors, 5 warnings, 4 suggestions
■ Review saved to .revlo/board-review-20250115T103000.json
■ Launching review browser...
```

### Example Findings

```
✗ ERROR U1: Missing decoupling capacitors on VDDA
  STM32F103CBT6 pin 13 (VDDA) requires a 1uF + 10nF decoupling capacitor
  pair per datasheet section 6.1.6, but no capacitors are connected to
  the VDDA net.
  Add a 1uF ceramic + 10nF ceramic capacitor between VDDA (pin 13)
  and GND, placed as close to the pin as possible.

▲ WARN  R3: I2C pull-up resistor value too high for 400kHz operation
  R3 (10kΩ) on the I2C_SCL net exceeds the recommended maximum of
  4.7kΩ for Fast-mode (400kHz) I2C. With a bus capacitance of ~50pF,
  the rise time will be approximately 500ns, violating the 300ns spec.
  Replace R3 with a 2.2kΩ or 4.7kΩ resistor to meet I2C Fast-mode
  rise time requirements.

◆ INFO  U1: Unused GPIO pins left floating
  U1 pins PA8, PA11, PA12 (GPIO) are unconnected and not configured
  as inputs with internal pull-ups in the schematic. Floating inputs
  increase power consumption and may cause spurious interrupts.
  Configure unused GPIOs as outputs driven low, or connect to GND/VCC
  via 10kΩ resistors. Alternatively, ensure firmware enables internal
  pull-ups on these pins.
```

## Ask Mode

Press `a` in the TUI to enter Ask Mode -- an interactive chat with live access to your schematic. Ask complex EE questions and get answers grounded in your actual design.

### Schematic Tools

Revlo can actively explore your design using 4 built-in tools:

| Tool | What it does |
|------|-------------|
| `lookup_component(ref)` | Get full component details: pins, nets, properties, datasheet specs |
| `trace_net(net_name)` | See every component/pin connected to a net |
| `find_unconnected_pins(ref?)` | Find floating pins, optionally filtered by component |
| `list_power_rails()` | List all power nets with connection counts |

### Example

> **You:** Is my reset circuit correct for U1?
>
> **Revlo:** [looks up U1, traces the NRST net]
> The STM32F103 datasheet (p.47) requires a 100nF filter cap on NRST.
> Your circuit has C3 (100nF) to GND and R5 (10k) pull-up to VCC.
> RC time constant: 10k x 100nF = 1ms -- well above the 20us minimum.

Toggle extended thinking with `t` for deeper analysis on complex questions.

## TUI Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Up`/`Down` or `j`/`k` | Navigate findings |
| `e` | Filter: errors only |
| `w` | Filter: warnings only |
| `s` | Filter: suggestions only |
| `f` | Filter: show all |
| `a` | Enter Ask Mode |
| `t` | Toggle extended thinking (in Ask Mode) |
| `m` | Export markdown report |
| `o` | Open datasheet PDF |
| `Esc` | Exit Ask Mode |
| `q` | Quit |

## Review History

Revlo saves every review and Ask Mode conversation automatically.

```bash
# List past reviews for a schematic
revlo history board.kicad_sch

# Re-open last review in TUI (no re-run needed)
revlo open board.kicad_sch

# Load a specific past review
revlo history board.kicad_sch --load 2
```

## How It Works

```
  .kicad_sch file
       │
       ▼
 ┌─────────────┐
 │   Parser    │  Extract components, nets, connectivity,
 │             │  hierarchical sub-sheets, power symbols
 └──────┬──────┘
        │
        ▼
 ┌─────────────┐
 │  Datasheet  │  Resolve MPN → fetch PDF → extract specs
 │  Pipeline   │  (normalize, cache, smart page selection)
 └──────┬──────┘
        │
        ▼
 ┌─────────────┐
 │  Chunker    │  Split into IC-context + power-rail chunks
 └──────┬──────┘
        │
        ▼
 ┌─────────────┐
 │  EE Review  │  AI reviews each chunk against
 │  Engine     │  domain-specific checklists + datasheet specs
 └──────┬──────┘
        │
        ▼
 ┌─────────────┐
 │  Output     │  TUI browser, CLI cards, JSON, Markdown
 └──────┬──────┘
        │
        ▼
 ┌─────────────┐
 │  Ask Mode   │  Interactive chat with schematic tools
 │  (optional) │  Extended thinking for deep EE analysis
 └─────────────┘
```

## Current Scope

Revlo's implemented review path is schematic-first:

- Fully implemented: schematic parsing, datasheet enrichment, AI review, TUI browsing, Ask Mode, review history
- Not yet implemented as a live runtime path: PCB layout review from `.kicad_pcb`, BOM lifecycle analysis, web upload flow

The review engine currently uses a direct Claude API workflow over structured schematic chunks rather than a live multi-agent orchestration layer.

## Datasheet Intelligence

Revlo automatically fetches and analyzes component datasheets to make reviews more accurate. It resolves datasheet PDFs in this order:

1. **Schematic-embedded URL** -- If your KiCad component has a `Datasheet` property, Revlo validates it with a HEAD request and downloads it directly.
2. **Mouser API** -- Searches by manufacturer part number using the [Mouser Search API](https://www.mouser.com/api-hub/).
3. **Farnell/Element14 API** -- Falls back to the [Farnell Product Search API](https://partner.element14.com/docs/Product_Search_API_REST_Description).
4. **Manual PDF** -- If all automated sources fail, you can drop a PDF into the `datasheets/` directory next to your schematic.

### API Keys (Optional)

Mouser and Farnell lookups require free API keys. Without them, Revlo still works using schematic-embedded URLs and manual PDFs.

```bash
# Get a free key at https://www.mouser.com/api-hub/
export MOUSER_API_KEY="your-mouser-api-key"

# Get a free key at https://partner.element14.com/
export FARNELL_API_KEY="your-farnell-api-key"
```

You can also add these to a `.env` file in the project root -- Revlo loads it automatically via `python-dotenv`.

### Manual PDF Fallback

If a datasheet can't be fetched (e.g. vendor blocks programmatic downloads), place the PDF in the `datasheets/` directory next to your schematic. Revlo matches PDFs by manufacturer part number:

```
my-project/
  board.kicad_sch
  datasheets/
    MSPM0G3507SPTR.pdf      # matched by MPN substring
    www.ti.com/              # or in vendor subdirectory
      mspm0g3507.pdf
```

### Caching

Downloaded datasheets and extracted specs are cached in `datasheets/cache.json` with a 90-day TTL. Delete the cache file to force re-fetching.

## CLI Reference

```bash
# Full review with interactive TUI (default)
revlo review board.kicad_sch

# CLI output only (no TUI)
revlo review board.kicad_sch --no-tui

# JSON output to stdout
revlo review board.kicad_sch --json

# Save markdown report to file
revlo review board.kicad_sch --output report.md

# Skip datasheet enrichment (faster, less accurate)
revlo review board.kicad_sch --skip-datasheet

# Filter low-confidence findings
revlo review board.kicad_sch --min-confidence 0.7

# Use a faster model instead of the default Opus review
revlo review board.kicad_sch --model sonnet

# Verbose output (show debug info)
revlo review board.kicad_sch --verbose

# Re-open last review without re-running
revlo open board.kicad_sch

# List past reviews for a schematic
revlo history board.kicad_sch

# Load a specific past review in the TUI
revlo history board.kicad_sch --load 2

# Export sign-off report for stakeholders
revlo review board.kicad_sch --signoff signoff-packet.md

# Use a review profile tuned for MCU boards
revlo review board.kicad_sch --profile mcu-board

# Compare against a previous revision (diff review)
revlo review board.kicad_sch --compare-to board-v1.kicad_sch

# Provide a BOM for sourcing checks
revlo review board.kicad_sch --bom board-bom.csv

# Non-interactive CI check with severity threshold
revlo check board.kicad_sch --fail-on error --policy-json > results.json
```

## CI Integration

Use `revlo check` with `--policy-json` to emit a versioned JSON schema (v1) that downstream tooling can parse reliably. The exit code reflects the `--fail-on` policy:

```bash
# Fail CI on errors, write versioned JSON to results.json
revlo check board.kicad_sch --policy-json --fail-on error --output results.json

# Or pipe to stdout -- exit code 2 means policy violation
revlo check board.kicad_sch --policy-json --fail-on error > results.json
echo "Exit code: $?"
```

The JSON output includes `schema_version`, finding IDs (stable SHA-256 fingerprints), severity, category, confidence, source type, baseline classification, evidence, and review metadata.

## Custom Rule Packs

Create a `revlo-rules.json` file next to your schematic to add project-specific checks:

```json
{
  "schema_version": 1,
  "name": "my-project-rules",
  "additive": true,
  "rules": [
    {
      "id": "no-0201-passives",
      "title": "0201 passives not allowed",
      "severity": "warning",
      "category": "library_hygiene",
      "remediation": "Use 0402 or larger package sizes for manufacturability.",
      "conditions": [
        {"field": "value_contains", "operator": "contains", "value": "0201"}
      ]
    }
  ]
}
```

Set `"additive": false` to replace built-in rules entirely with your custom pack.

## Development

### Setup

```bash
cd backend && uv sync
```

### Run Tests

```bash
cd backend && uv run pytest tests/ -v
```

Note: if the full suite fails, check for missing test fixtures first. The CLI/TUI tests depend on local schematic fixtures in `backend/tests/fixtures/`.

### Lint

```bash
cd backend && uv run ruff check revlo/
```

### Verify Install

```bash
cd backend && uv run python -c "from revlo.parser import parse_schematic; print('OK')"
```

## License

Apache 2.0 -- see [LICENSE](https://github.com/rebels-software/revlo-cli/blob/main/LICENSE) for details.
