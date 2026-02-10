# Revlo

AI-powered hardware review tool for KiCad projects.

## Overview

Revlo parses KiCad schematic files (`.kicad_sch`) into structured data, then feeds that data into an AI model to review designs for common electrical engineering mistakes.

The tool extracts:
- **Components** — reference designators, values, footprints, and pin mappings
- **Nets** — named connections between component pins
- **Connectivity** — full topology of how components are wired together
- **Power symbols** — VCC, GND, and other power rail indicators
- **Hierarchical sheets** — sub-sheet references and their pin interfaces

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager

## Getting Started

```bash
# Install dependencies
cd backend && uv sync

# Verify the installation
cd backend && uv run python -c "from revlo.parser import parse_schematic; print('OK')"
```

## Development

```bash
# Run tests
cd backend && uv run pytest tests/ -v

# Run linter
cd backend && uv run ruff check revlo/
```

## Project Structure

```
backend/
├── pyproject.toml
├── revlo/
│   ├── __init__.py
│   ├── parser/
│   │   ├── __init__.py
│   │   ├── models.py           # Pydantic models for parsed output
│   │   ├── schematic.py        # Main parser using kicad-sch-api
│   │   └── connectivity.py     # Net extraction wrapper
│   └── cli.py                  # CLI stub
└── tests/
    └── fixtures/               # Test KiCad files
```

## KiCad Parsing Pipeline

1. **Load** — Read a `.kicad_sch` file using `kicad-sch-api` (with `kiutils` as fallback)
2. **Extract components** — Walk the schematic tree to pull out all symbols, their properties, and pin definitions
3. **Build nets** — Resolve wires, labels, and global labels into named nets connecting component pins
4. **Detect power** — Identify power symbols and flag power nets (VCC, GND, etc.)
5. **Structure output** — Return a `ParsedSchematic` Pydantic model containing components, nets, power symbols, sheets, and unconnected pins
6. **Serialize** — Call `.model_dump()` for JSON output ready for AI review
