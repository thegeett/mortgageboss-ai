"""The couldnt_check reasons speak MORTGAGE, not engine (LP-376-C) — the ticket, in a test.

A loan processor reads these. NO user-facing reason may contain engine vocabulary: a dotted tag id
(`id.dob`), a content-id hash (`txn54c6…`), or the words `operand` / `load-bearing tag` / `subject`. This
scans the reason each of the four sites produces (gate, consistency <2, applicability, absent-document) and
asserts it is clean — AND that it still names WHAT is missing.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from app.verification.rule_engine.applicability import (
    absent_document_couldnt_check,
    resolve_applicability,
)
from app.verification.rule_engine.gate import evaluate_gate
from app.verification.rule_engine.reasons import fact_label
from app.verification.rules.specs import TagCondition, _as_conditions
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

# A dotted tag id (id.dob), a content-id hash (txn54c6…/doc067c2…), and the raw engine words.
_DOTTED_ID = re.compile(r"\b[a-z][a-z_]*(?:\.[a-z][a-z_]*)+\b")
_CONTENT_ID = re.compile(r"\b(?:txn|doc)[0-9a-f]{6,}\b")
_ENGINE_WORDS = (
    "operand",
    "load-bearing",
    "load bearing",
    "load_bearing",
    " subject",
    "gather_tag",
)


def _engine_vocab(reason: str) -> str | None:
    """The first piece of engine vocabulary in a user-facing reason, or None if it is clean."""
    if (m := _DOTTED_ID.search(reason)) is not None:
        return f"dotted id {m.group(0)!r}"
    if (m := _CONTENT_ID.search(reason)) is not None:
        return f"content-id {m.group(0)!r}"
    low = reason.lower()
    for word in _ENGINE_WORDS:
        if word in low:
            return f"engine word {word!r}"
    return None


def _tag(value: str, *, confidence: float | None = 0.9) -> Tag:
    return Tag(
        value=value,
        confidence=confidence,
        reasoning="fixture",
        source_facts=("raw",),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _assert_clean(reason: str) -> None:
    found = _engine_vocab(reason)
    assert found is None, (
        f"engine vocabulary leaked into a processor-facing reason: {found}\n  {reason!r}"
    )


# --------------------------------------------------------------------------- #
# The gate — absent / unknown / low-confidence
# --------------------------------------------------------------------------- #
def test_gate_absent_reason_is_human() -> None:
    r = evaluate_gate({"id.dob": None}, confidence_floor=0.5).reason or ""
    _assert_clean(r)
    assert fact_label("id.dob") in r  # names the missing fact in mortgage terms


def test_gate_unknown_reason_is_human() -> None:
    r = evaluate_gate({"id.ssn_hash": _tag("unknown")}, confidence_floor=0.5).reason or ""
    _assert_clean(r)
    assert fact_label("id.ssn_hash") in r


def test_gate_low_confidence_reason_is_human() -> None:
    r = (
        evaluate_gate({"txn.amount": _tag("5000", confidence=0.4)}, confidence_floor=0.5).reason
        or ""
    )
    _assert_clean(r)
    assert "review" in r.lower()


# --------------------------------------------------------------------------- #
# Applicability — a document that could not be classified + a genuinely-absent expected document
# --------------------------------------------------------------------------- #
def test_untyped_document_reason_is_human_and_names_the_document() -> None:
    applic = TagCondition(tag="document.document_type", op="eq", value="title_commitment")
    subject_tags: Mapping[str, Tag] = {"document.document_type": _tag("unknown")}
    terminal = resolve_applicability(applic, subject_tags)
    assert terminal is not None
    _assert_clean(terminal[1])
    assert "title commitment" in terminal[1] and "classif" in terminal[1].lower()


def test_absent_expected_document_reason_is_human_and_names_the_action() -> None:
    applic = TagCondition(tag="document.document_type", op="eq", value="title_commitment")
    # Every (present) subject is confidently out of scope → the good "no title commitment" sentence.
    reason = absent_document_couldnt_check(
        applic,
        expected=True,
        subjects=[("d1", {"document.document_type": _tag("paystub")})],
        documents_absent=False,
    )
    assert reason is not None
    _assert_clean(reason)
    assert "title commitment" in reason and "request" in reason.lower()


def test_non_document_applicability_reason_names_the_fact_not_a_document() -> None:
    # AS-1's applicability is txn.is_money_in (a TRANSACTION predicate, not a document type). An unknown
    # direction must NOT read as "classify the document / the 'in'" — it names the mortgage FACT.
    applic = TagCondition(tag="txn.is_money_in", op="eq", value="in")
    unknown = resolve_applicability(applic, {"txn.is_money_in": _tag("unknown")})
    assert unknown is not None
    _assert_clean(unknown[1])
    assert "deposit direction" in unknown[1] and "document" not in unknown[1].lower()

    absent = resolve_applicability(applic, {})  # tag not produced
    assert absent is not None
    _assert_clean(absent[1])
    assert "deposit direction" in absent[1] and "document" not in absent[1].lower()


def test_every_live_rule_reason_tag_has_a_curated_fact_label() -> None:
    # DRIFT GUARD (LP-376-C review): a live rule's couldnt_check reason interpolates fact_label(tag) for the
    # tag whose absence/unknown caused it. An UNMAPPED tag degrades to a humanized STEM — clean-looking (so
    # _assert_clean passes) but NOT the curated mortgage phrase. Assert every such tag is mapped, so a new
    # live rule cannot silently ship a half-translated reason.
    from app.verification.rule_engine.reasons import _FACT_LABELS
    from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
    from app.verification.rules.specs import DOC_TYPE_TAG, load_rule_spec

    missing: dict[str, set[str]] = {}
    for rule_id in ACTIVE_RULE_IDS:
        spec = load_rule_spec(rule_id)
        tags: set[str] = set()
        if spec.deterministic is not None:
            tags |= set(spec.deterministic.gated_tags)
            # LP-517: applicability may be a CONJUNCTION — every predicate can produce the reason.
            for applic in _as_conditions(spec.deterministic.applicability):
                if applic.tag_id != DOC_TYPE_TAG:
                    tags.add(applic.tag_id)
        if spec.judgment is not None:
            tags |= set(spec.judgment.load_bearing_tags)
            for applic in _as_conditions(spec.judgment.applicability):
                if applic.tag_id != DOC_TYPE_TAG:
                    tags.add(applic.tag_id)
        if spec.consistency is not None:
            tags.add(spec.consistency.gather_tag)
            if spec.consistency.gather_filter is not None:
                tags.add(spec.consistency.gather_filter.tag)
        unmapped = {t for t in tags if t not in _FACT_LABELS}
        if unmapped:
            missing[rule_id] = unmapped
    assert not missing, (
        f"live rules whose couldnt_check reason-tags lack a curated fact label: {missing}"
    )
