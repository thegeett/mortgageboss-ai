"""Defensive parsing helpers for model responses (LP-38 / LP-39).

Model output is text, not a guaranteed-clean JSON object: it may arrive wrapped
in ```` ```json ```` fences, with surrounding prose, or with out-of-range/odd
values. These helpers are the shared, never-raising primitives that
classification (LP-38) and extraction (LP-39) build their type-specific parsers
on. They never raise — callers map ``None`` / fallbacks to a graceful result.
"""

import re
from typing import Any


def extract_json_object(text: str) -> str | None:
    """Pull the first balanced ``{...}`` object out of a model response.

    Tolerates markdown fences and leading/trailing prose by scanning for the
    first ``{`` and matching its closing brace (brace-depth aware, so nested
    objects are handled). Returns the JSON substring, or ``None`` if there is no
    balanced object.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def coerce_confidence(value: Any) -> float:
    """Coerce a model-provided confidence to a float clamped to ``[0, 1]``.

    Accepts numbers or numeric strings; a bool, junk, or anything unparseable
    becomes ``0.0`` (an out-of-range or garbage confidence must not raise or skew
    downstream review).
    """
    if isinstance(value, bool):  # bool is an int subclass — reject it explicitly
        return 0.0
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        match = re.search(r"-?\d+(\.\d+)?", value)
        if match is None:
            return 0.0
        number = float(match.group())
    else:
        return 0.0
    return max(0.0, min(1.0, number))
