"""Declared subject applicability (LP-329, GAP-C) — SHARED across the deterministic + judgment
evaluators, so a rule can scope itself to the subjects it applies to (e.g. a POA rule to POA
documents) without flooding couldnt_check across every out-of-scope subject.

THE §8 HONESTY CONTRACT — not_applicable (scope-false) must NEVER absorb couldnt_check (data-missing):

* the predicate tag says the subject is OUT OF SCOPE → ``not_applicable`` (Tab 4 — the rule was never
  relevant to this subject; a paystub for a POA rule). No gate, no AI, no tag. NOT a gap.
* the predicate tag is ABSENT / ``"unknown"`` → ``couldnt_check`` (Tab 1 — we cannot tell IF the rule
  applies; a present-but-unreadable document). It IS a gap and it blocks.

These are completely different, and conflating them would hide a real gap behind a false
"not applicable". The predicate is DATA (a :class:`TagCondition`); no document types live in code.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import TagCondition
from app.verification.snapshot.tag import Tag

_UNKNOWN = "unknown"


def resolve_applicability(
    applic: TagCondition, subject_tags: Mapping[str, Tag]
) -> tuple[Verdict, str] | None:
    """``None`` → the rule APPLIES to this subject; otherwise the terminal (verdict, reason).

    ABSENT / ``"unknown"`` predicate tag → couldnt_check (cannot tell if it applies); a predicate that
    is DEFINITELY false → not_applicable (out of scope). The predicate holding → the rule applies."""
    tag = subject_tags.get(applic.tag)
    if tag is None:
        return (
            Verdict.COULDNT_CHECK,
            f"applicability tag '{applic.tag}' was not produced — cannot tell if the rule applies",
        )
    if tag.value == _UNKNOWN:
        return (
            Verdict.COULDNT_CHECK,
            f"applicability tag '{applic.tag}' is unknown — cannot confirm the rule applies",
        )
    matches = (tag.value == applic.value) if applic.op == "eq" else (tag.value != applic.value)
    if not matches:
        return (
            Verdict.NOT_APPLICABLE,
            f"the rule does not apply to this subject "
            f"({applic.tag} {applic.op} {applic.value!r} is false)",
        )
    return None


__all__ = ["resolve_applicability"]
