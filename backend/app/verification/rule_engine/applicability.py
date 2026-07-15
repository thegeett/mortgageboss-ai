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


# The subject_id a missing-document couldnt_check is keyed under — a STABLE identity per (rule, type),
# so cross-run reconciliation carries it forward / retires it when the document appears.
def missing_document_subject_id(applic: TagCondition) -> str:
    return f"missing:{applic.value}"


def absent_document_couldnt_check(
    applic: TagCondition | None,
    expected: bool,
    subjects: list[tuple[str, Mapping[str, Tag]]],
    *,
    documents_absent: bool,
) -> str | None:
    """LP-330 — should a per_document rule emit a MISSING-DOCUMENT couldnt_check?

    The §8 question is NOT "did the filter match anything" — it is "SHOULD this document exist for this
    file?". Returns a reason (naming the expected type) when the document is EXPECTED yet CONFIDENTLY
    ABSENT: every subject is clearly out of scope (all ``not_applicable`` — none in scope, none
    ambiguous). Returns ``None`` (→ LP-329's not_applicable default) when the rule doesn't declare the
    document expected, OR any subject is in scope (the document EXISTS), OR any subject's type is
    ``"unknown"`` (we cannot claim it is absent — that subject already couldnt_checks), OR the
    documents section itself is ABSENT (a build degradation: we COULDN'T LOOK, so "confidently absent"
    is a lie — the §8 fourth case, distinct from confidently-absent; the missing SECTION is recorded by
    the orchestrator's degradation scan, not mis-attributed here as a missing document).

    A missing EXPECTED document is LOST VISIBILITY (Tab 1, BLOCKS), NOT scope-false (Tab 4)."""
    if applic is None or not expected or documents_absent:
        return None
    for _sid, tags in subjects:
        terminal = resolve_applicability(applic, tags)
        if terminal is None:  # a subject IS in scope → the document exists → not absent
            return None
        if terminal[0] is Verdict.COULDNT_CHECK:  # an unknown-type subject → cannot claim absence
            return None
    # Every subject (or an empty-but-PRESENT documents section) is confidently out of scope → absent.
    return (
        f"no '{applic.value}' document in the file — the rule requires one to evaluate "
        f"(the document is expected but missing; lost visibility, not out of scope)"
    )


__all__ = [
    "absent_document_couldnt_check",
    "missing_document_subject_id",
    "resolve_applicability",
]
