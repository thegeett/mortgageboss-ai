"""Prompt loading (LP-38).

Prompts are **iterated content, not code**: they live as files under
``app/ai/prompts/**`` and are loaded at runtime, so they can be versioned,
diffed, and edited without touching Python. :func:`load_prompt` is the one entry
point — classification (LP-38) uses it now, extraction (LP-39) reuses it.

Paths resolve relative to the prompts directory (not the process CWD) and are
checked to stay within it, so a stray ``..`` can't read an arbitrary file.
"""

from functools import cache
from pathlib import Path

_PROMPTS_DIR = (Path(__file__).parent / "prompts").resolve()


@cache
def load_prompt(relative_path: str) -> str:
    """Read a prompt file from the prompts directory, by its relative path.

    ``relative_path`` is POSIX-style relative to ``app/ai/prompts`` (e.g.
    ``"classification/document_classifier.txt"``). The result is cached — prompts
    don't change at runtime. Raises ``ValueError`` if the path escapes the
    prompts dir, and ``FileNotFoundError`` if the file is missing (both are
    programmer errors, surfaced loudly rather than silently returning "").
    """
    full = (_PROMPTS_DIR / relative_path).resolve()
    if full != _PROMPTS_DIR and _PROMPTS_DIR not in full.parents:
        raise ValueError(f"Prompt path escapes the prompts dir: {relative_path!r}")
    return full.read_text(encoding="utf-8")
