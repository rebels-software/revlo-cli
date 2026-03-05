# AGENTS.md - Revlo

Revlo is a CLI/TUI tool for reviewing KiCad schematics with AI.

## Commands

```bash
cd backend && uv sync
cd backend && uv run pytest tests/ -v
cd backend && uv run ruff check revlo/
cd backend && uv run python -c "from revlo.parser import parse_schematic; print('OK')"
```

## Notes

- Main code lives in `backend/revlo/`.
- Parser models are in `backend/revlo/parser/`.
- Review, datasheet, and TUI flows are all implemented in the backend package.
- Use `prd.json` for scope and story status.
