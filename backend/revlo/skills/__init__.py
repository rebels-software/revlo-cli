"""EE specialist agent prompt files for the Claude Agent SDK."""

from pathlib import Path

_SKILLS_DIR = Path(__file__).parent


def load_skill(name: str) -> str:
    """Load a skill markdown file by name (without .md extension)."""
    path = _SKILLS_DIR / f"{name}.md"
    return path.read_text()
