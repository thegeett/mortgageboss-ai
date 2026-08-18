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

from collections.abc import Mapping, Sequence

from app.verification.rule_engine.reasons import document_label, fact_phrase
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import DOC_TYPE_TAG, TagCondition
from app.verification.snapshot.tag import Tag

_UNKNOWN = "unknown"


def _undetermined_reason(applic: TagCondition, *, present_but_unclear: bool) -> str:
    """The couldnt_check reason when the applicability predicate's tag is absent/unknown — SHAPE-AWARE
    (LP-376-C): a per-DOCUMENT rule (the predicate IS the document type) asks for classification; ANY
    other predicate (e.g. AS-1's ``txn.is_money_in``) names the mortgage FACT it needs, never a document
    action for a non-document fact."""
    if applic.tag_id == DOC_TYPE_TAG:
        verb = "could not be classified" if present_but_unclear else "has not been classified"
        return (
            f"a document in the file {verb} — it may be the {document_label(applic.value)} this "
            "check needs; classify it so the check can run"
        )
    verb = "could not be determined" if present_but_unclear else "has not been determined"
    return (
        f"{fact_phrase(applic.tag_id)} {verb} — this check needs it to tell whether the rule "
        "applies here"
    )


def resolve_applicability(
    applic: TagCondition,
    subject_tags: Mapping[str, Tag],
    loan_tags: Mapping[str, Tag] | None = None,
) -> tuple[Verdict, str] | None:
    """``None`` → the rule APPLIES to this subject; otherwise the terminal (verdict, reason).

    ABSENT / ``"unknown"`` predicate tag → couldnt_check (cannot tell if it applies); a predicate that
    is DEFINITELY false → not_applicable (out of scope). The predicate holding → the rule applies."""
    # A `loan_tag` condition reads the LOAN subject's map, not this subject's (LP-517). Defaulting
    # `loan_tags` to empty rather than to `subject_tags` keeps the failure honest: a loan-scoped
    # predicate on a caller that did not supply them reads ABSENT -> couldnt_check, never accidentally
    # matching a same-named tag on the subject.
    source = subject_tags if applic.tag is not None else (loan_tags or {})
    tag = source.get(applic.tag_id)
    if tag is None:
        return (Verdict.COULDNT_CHECK, _undetermined_reason(applic, present_but_unclear=False))
    if tag.value == _UNKNOWN:
        return (Verdict.COULDNT_CHECK, _undetermined_reason(applic, present_but_unclear=True))
    matches = (tag.value == applic.value) if applic.op == "eq" else (tag.value != applic.value)
    if not matches:
        return (
            Verdict.NOT_APPLICABLE,
            f"the rule does not apply to this subject "
            f"({applic.tag_id} {applic.op} {applic.value!r} is false)",
        )
    return None


def resolve_applicabilities(
    applics: Sequence[TagCondition],
    subject_tags: Mapping[str, Tag],
    loan_tags: Mapping[str, Tag] | None = None,
) -> tuple[Verdict, str] | None:
    """The same contract as :func:`resolve_applicability`, over a CONJUNCTION of predicates (LP-517).

    A rule's scope is often two facts, not one — AS-2 applies to money-IN transactions AND only on a
    PURCHASE. Expressing that needed a bespoke combined tag per rule, which merged two different
    abstentions into one enum and lost the per-predicate reason.

    ⚠️ ORDER OF PRECEDENCE, and it is not "first predicate wins": EVERY predicate is evaluated, then

      * any predicate DEFINITELY FALSE  -> not_applicable. Scope-false beats data-missing: a money-OUT
        transaction is out of scope for an earnest-money check whether or not the loan purpose is known,
        so reporting "we could not tell" about it would be false.
      * else any predicate ABSENT / "unknown" -> couldnt_check, carrying THAT predicate's own reason, so
        the message still names the fact that is missing.
      * else -> the rule applies.
    """
    undetermined: tuple[Verdict, str] | None = None
    for applic in applics:
        terminal = resolve_applicability(applic, subject_tags, loan_tags)
        if terminal is None:
            continue
        if terminal[0] is Verdict.NOT_APPLICABLE:
            return terminal
        if undetermined is None:
            undetermined = terminal
    return undetermined


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
    # LP-376-C: name the document + the action (this good sentence is only reached when NO document is
    # unclassified — otherwise it is correctly suppressed above, since an untyped doc might BE this one).
    return (
        f"no {document_label(applic.value)} is in the file — this check needs one; request it "
        "from the borrower or originator"
    )


__all__ = [
    "absent_document_couldnt_check",
    "missing_document_subject_id",
    "resolve_applicabilities",
    "resolve_applicability",
]
