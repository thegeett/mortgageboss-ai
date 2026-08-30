"""Which extracted fields get checked even when the model is sure (LP-UI-032).

Confidence tiering lets a processor skip the fields nobody needs to re-read. The
model's own certainty is the wrong sole input to that, because **the expensive
errors are the confident ones** — a hallucinated licence expiry arrives at 0.99
(LP-508, docs 146/294). So criticality overrides confidence: a field naming money,
a rate or an identity is flagged whatever number sits beside it.

The list is DATA (``critical_fields.yaml``), the same posture as
``distrusted_fields.yaml``: reviewable, prunable, and carrying the reason for each
exclusion so a domain review is a reading task.

**Keyed on the field NAME, not on (document_type, field).** A money figure is a
money figure on whatever document it appears, and at 1,603 typed-core keys across
121 document types a per-document list would stop being legible — which is the
same as stopping being reviewed.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml

_PATH = Path(__file__).with_name("critical_fields.yaml")


class CriticalityError(Exception):
    """The critical-field list is malformed."""


@cache
def _document() -> dict[str, object]:
    raw = yaml.safe_load(_PATH.read_text())
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise CriticalityError("critical_fields.yaml: the top level must be a mapping")
    return raw


@cache
def critical_fields() -> frozenset[str]:
    """Every field name that is checked regardless of confidence.

    Flattened across the YAML's category groups — the groups exist to keep the file
    readable and reviewable, and carry no meaning at read time.
    """
    groups = _document().get("critical") or {}
    if not isinstance(groups, dict):
        raise CriticalityError("critical_fields.yaml `critical` must map a category to a list")
    out: set[str] = set()
    for category, names in groups.items():
        if not isinstance(names, list):
            raise CriticalityError(f"critical_fields.yaml critical.{category} must be a list")
        for name in names:
            text = str(name or "").strip()
            if not text:
                raise CriticalityError(f"critical_fields.yaml critical.{category}: an empty entry")
            if text in out:
                # A name in two categories is not harmful at read time, but it means
                # two people classified it and only one of them will be updated.
                raise CriticalityError(f"critical_fields.yaml: {text} is listed twice")
            out.add(text)
    return frozenset(out)


@cache
def reviewed_not_critical() -> dict[str, str]:
    """``{field: why it looked critical and is not}``.

    Half the value of the file. An unexplained absence is indistinguishable from an
    oversight, and this is the half that makes a later review cheap.
    """
    raw = _document().get("reviewed_not_critical") or {}
    if not isinstance(raw, dict):
        raise CriticalityError("critical_fields.yaml `reviewed_not_critical` must be a mapping")
    out: dict[str, str] = {}
    for field, reason in raw.items():
        text = str(reason or "").strip()
        if not text:
            raise CriticalityError(
                f"critical_fields.yaml reviewed_not_critical.{field}: a reason is REQUIRED — "
                "an entry with no reason cannot be reviewed or pruned"
            )
        out[str(field)] = text
    return out


@cache
def identity_fields() -> frozenset[str]:
    """The `identity` category alone — the fields that must never render in the clear.

    Read from the same list rather than kept separately: an SSN field added to
    `critical.identity` is by construction one a screen must mask, and two lists
    would eventually disagree about the same field. The frontend keeps its own
    masking set as a floor, so a backend that stops answering cannot un-mask
    anything that is masked today.
    """
    groups = _document().get("critical") or {}
    if not isinstance(groups, dict):
        raise CriticalityError("critical_fields.yaml `critical` must map a category to a list")
    names = groups.get("identity") or []
    if not isinstance(names, list):
        raise CriticalityError("critical_fields.yaml critical.identity must be a list")
    return frozenset(str(n).strip() for n in names if str(n or "").strip())


def is_sensitive(field: str) -> bool:
    """Whether displaying `field` in the clear would put an identifier on a screen."""
    return field in identity_fields()


def is_critical(field: str) -> bool:
    """Whether `field` is checked regardless of the model's confidence in it."""
    return field in critical_fields()
