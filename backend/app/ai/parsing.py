"""Defensive parsing helpers for model responses (LP-38 / LP-39).

Model output is text, not a guaranteed-clean JSON object: it may arrive wrapped
in ```` ```json ```` fences, with surrounding prose, or with out-of-range/odd
values. These helpers are the shared, never-raising primitives that
classification (LP-38) and extraction (LP-39) build their type-specific parsers
on. They never raise — callers map ``None`` / fallbacks to a graceful result.
"""

import math
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


def _parse_confidence(value: Any) -> float | None:
    """Parse a confidence to a finite float, or ``None`` if there is no usable number.

    Returns ``None`` when the value is missing, a bool, non-numeric, non-finite
    (``NaN`` / ``Infinity``), or a string containing no number. The number is **not**
    range-checked here — each caller applies its own out-of-range policy (the
    document-level gate clamps to ``[0, 1]``; the per-field path rejects it as
    unassessable). This is the shared primitive behind both public coercers.
    """
    if value is None or isinstance(value, bool):  # bool is an int subclass — reject it
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        match = re.search(r"-?\d+(\.\d+)?", value)
        if match is None:
            return None
        number = float(match.group())
    else:
        return None
    return number if math.isfinite(number) else None  # NaN/Infinity are not confidences


def coerce_confidence(value: Any) -> float:
    """Coerce a document-level confidence to a float in ``[0, 1]``; garbage → ``0.0``.

    The low-confidence review gate (LP-42), classification, and cross-source all
    need a plain float, so a missing / non-numeric / non-finite value collapses to
    ``0.0`` and an out-of-range number is clamped to ``[0, 1]`` (never raises, never
    skews the gate). See :func:`coerce_optional_confidence` for the per-field path
    that keeps genuine absence honest (``None``).
    """
    number = _parse_confidence(value)
    if number is None:
        return 0.0
    return max(0.0, min(1.0, number))


def coerce_optional_confidence(value: Any) -> float | None:
    """Coerce a per-field confidence to a float in ``[0, 1]``, or ``None`` (LP-201).

    Unlike :func:`coerce_confidence` (which defaults missing/garbage to ``0.0`` and
    *clamps* an out-of-range number for the document-level review gate), this
    **never fabricates a number**: an absent, null, boolean, non-finite
    (``NaN`` / ``Infinity``), unparseable, or out-of-range value (e.g. ``1.5`` or the
    ``85`` scraped from ``"85%"``) returns ``None`` — a field the model did not
    honestly rate in ``[0, 1]`` is recorded as "no confidence", not a fake ``1.0``.
    A genuine ``0.0`` the model reported is kept as ``0.0`` (honest), not ``None``.
    """
    number = _parse_confidence(value)
    if number is None or number < 0.0 or number > 1.0:
        return None
    return number
