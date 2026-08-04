"""Belt-and-braces PII redaction — the SECOND layer, over what the model returned.

The first layer is the model itself (``bench_pii_prompt`` → ``[NAME]``/``[SSN]``/… placeholders).
This second layer is a deterministic regex sweep over EVERY string value the extraction produced —
typed fields, every list row, and the additional_sections catch-all — to catch identity data the
model missed. It reuses the snapshot layer's ``_DESC_REDACT`` long-digit-run pattern (a real SSN and
a real home address were previously found in a catch-all — the catch-all is where unanticipated PII
hides) plus email and long-phone patterns.

Conservative by design: it redacts only high-confidence identity SHAPES (a 9+-digit run, an email,
an SSN/phone pattern). It does NOT try to catch names/addresses — those are the model's job (layer 1)
because a regex cannot tell "AMBIO INC" (an employer, KEEP) from a person's name. So a bench report
should be read as: layer 1 (model) placeholds identity; layer 2 (this) is the digit/email backstop.
"""

from __future__ import annotations

import re
from typing import Any

# Reuse the snapshot backstop: a run of 9+ digits (SSN, account/loan number, long id), optionally
# separated by spaces/hyphens. A masked last-4 (``****1234``) has <9 digits, so it survives (a signal).
_DIGIT_RUN = re.compile(r"\d(?:[\s-]?\d){8,}")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\b(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")

_REDACTED = "[redacted]"


def redact_string(value: str) -> tuple[str, int]:
    """Redact identity shapes in one string. Returns (scrubbed, number_of_substitutions)."""
    hits = 0
    for pattern in (_EMAIL, _SSN, _PHONE, _DIGIT_RUN):
        value, n = pattern.subn(_REDACTED, value)
        hits += n
    return value, hits


def redact_tree(obj: Any) -> tuple[Any, int]:
    """Recursively redact every string value in a nested dict/list structure (in a COPY — the input
    is never mutated). Returns (scrubbed_copy, total_substitutions). Non-string scalars pass through —
    they cannot carry an identity string."""
    if isinstance(obj, str):
        return redact_string(obj)
    if isinstance(obj, dict):
        out: dict[Any, Any] = {}
        total = 0
        for k, v in obj.items():
            out[k], n = redact_tree(v)
            total += n
        return out, total
    if isinstance(obj, (list, tuple)):
        items = []
        total = 0
        for v in obj:
            scrubbed, n = redact_tree(v)
            items.append(scrubbed)
            total += n
        return (items, total)
    return obj, 0
