# AGENTS.md - Revlo

## Project Overview

Revlo is an AI-powered hardware review tool for KiCad projects. It parses `.kicad_sch` files into structured JSON, then uses Claude to review designs for common EE mistakes.

## Development Commands

```bash
# Install dependencies
cd backend && uv sync

# Run tests
cd backend && uv run pytest tests/ -v

# Lint
cd backend && uv run ruff check revlo/

# Verify imports
cd backend && uv run python -c "from revlo.parser import parse_schematic; print('OK')"
```

## Project Structure

```
backend/
├── pyproject.toml
├── revlo/
│   ├── __init__.py
│   ├── parser/
│   │   ├── __init__.py
│   │   ├── models.py         # Pydantic models for parsed output
│   │   ├── schematic.py      # Main parser using kicad-sch-api
│   │   └── connectivity.py   # Net extraction wrapper
│   └── cli.py                # CLI stub
└── tests/
    └── fixtures/             # Test KiCad files
```

## Key Patterns

- **Parser library**: kicad-sch-api (primary), kiutils (fallback)
- **Models**: Pydantic v2 BaseModel with .model_dump() for JSON
- **Package manager**: uv

## Dependencies

- fastapi, uvicorn, anthropic, kicad-sch-api, pydantic, httpx, kiutils
- Dev: pytest, pytest-asyncio, ruff

## Task Tracking

See `prd.json` for user stories. Update `progress.txt` as work completes.
