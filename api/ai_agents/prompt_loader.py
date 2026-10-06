"""Loads agent/system prompts from `ai_agents/prompts/*.md` — never hardcoded in Python."""
from __future__ import annotations

from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str, **format_kwargs) -> str:
    """Load `ai_agents/prompts/{name}.md` and optionally `.format(**format_kwargs)` it.

    `.format()` is only applied when format_kwargs is non-empty, so prompts
    containing literal `{` `}` (e.g. JSON examples) stay safe by default.
    """
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    text = path.read_text(encoding="utf-8")
    if format_kwargs:
        text = text.format(**format_kwargs)
    return text
