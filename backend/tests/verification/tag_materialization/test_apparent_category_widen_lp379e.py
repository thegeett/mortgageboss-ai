"""LP-379-E — the widened txn.apparent_category vocabulary (Priya's labels revealed two perception gaps).

Priya, labeling the real file, reached for categories the enum could not hold: a third-party transfer
(distinct from transfer_own) and a payment to a creditor. Where a tag cannot express a risk, no rule can ever
catch it. This widens the enum with three Priya-pending defaults — transfer_third_party_in /
transfer_third_party_out / debt_payment — DEFINED in the (single, converged) prompt. These pin that the new
values are producible (not coerced to unknown), that gift/loan_proceeds are kept (dormant rules read them),
that unknown stays first-class, and — the critical equivalence — that NO live rule reads apparent_category, so
widening it cannot shift a live verdict (AS-1 does not read it).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from app.ai.tag_production import APPARENT_CATEGORY_VALUES
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
    TransactionRecord,
)
from app.verification.tag_materialization.ai import AiGroupResult, AiSubjectJudgment, AiTagJudgment
from app.verification.tag_materialization.declarations import load_declarations
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio

_NEW = ("transfer_third_party_in", "transfer_third_party_out", "debt_payment")
_SPECS = Path(__file__).resolve().parents[3] / "app/verification/rules/specs"


def _f(v: str) -> Field:
    return Field.present(v, source=FieldSource.EXTRACTED)


def _snap_one_txn() -> tuple[Snapshot, str]:
    txn = TransactionRecord(
        content_id="t1",
        date=_f("2026-04-01"),
        amount=_f("147.70"),
        direction=_f("credit"),
        description=_f("ZELLE FROM RAVI KUMAR"),
    )
    doc = DocumentEntry(
        content_id="doc1",
        document_type="bank_statement",
        fields={"account_number_masked": _f("****1")},
        transactions=(txn,),
    )
    snap = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 20, tzinfo=UTC),
        documents=DocumentsSection.present([doc]),
        mismo=MismoSection.present({}),
        tags=TagsSection.present({}),
    )
    return snap, "t1"


def _stub(category: str):
    async def _call(context_json: str) -> AiGroupResult:
        import json

        subjects = json.loads(context_json)["subjects"]
        return AiGroupResult(
            [
                AiSubjectJudgment(
                    index=int(s["index"]),
                    tags={
                        "is_money_in": AiTagJudgment("in", 0.9, "stub"),
                        "apparent_category": AiTagJudgment(category, 0.9, "stub"),
                    },
                )
                for s in subjects
            ],
            0,
            0,
            "stub",
            False,
        )

    return _call


# --------------------------------------------------------------------------- #
# The widened vocabulary — the three new values, gift/loan kept, unknown first-class
# --------------------------------------------------------------------------- #
def test_enum_is_widened_consistently_across_both_value_sets() -> None:
    csv_values = load_declarations()["txn.apparent_category"].allowed_values or ()
    # both the coercion tuple (standalone path) and the vocabulary CSV (generic path) carry the new values
    for v in _NEW:
        assert v in APPARENT_CATEGORY_VALUES and v in csv_values
    # gift/loan_proceeds are KEPT (dormant AS-2/AS-5/AS-12 read them — D2 does not remove them here)
    assert "gift" in csv_values and "loan_proceeds" in csv_values
    # the two value sets agree exactly, so neither production path coerces differently
    assert set(APPARENT_CATEGORY_VALUES) == set(csv_values)


@pytest.mark.parametrize("category", [*_NEW, "unknown", "gift"])
async def test_new_categories_are_producible_not_coerced(category: str) -> None:
    snap, tid = _snap_one_txn()
    out = await materialize_tags(
        snap,
        ai_reasoners={"txn_stage_a": _stub(category)},
        only_subjects=frozenset({"transaction"}),
        only_groups=frozenset({"txn_stage_a"}),
    )
    assert out.tags.by_subject[tid]["txn.apparent_category"].value == category  # survives coercion


async def test_off_vocab_value_still_coerces_to_unknown() -> None:
    # widening did not weaken the vocabulary guard — an off-set value is still coerced, never smuggled in.
    snap, tid = _snap_one_txn()
    out = await materialize_tags(
        snap,
        ai_reasoners={"txn_stage_a": _stub("definitely_not_a_category")},
        only_subjects=frozenset({"transaction"}),
        only_groups=frozenset({"txn_stage_a"}),
    )
    assert out.tags.by_subject[tid]["txn.apparent_category"].value == "unknown"


# --------------------------------------------------------------------------- #
# THE CRITICAL EQUIVALENCE — no LIVE rule reads apparent_category, so widening shifts nothing
# --------------------------------------------------------------------------- #
def test_only_lp390_7_rules_read_apparent_category_live() -> None:
    readers = []
    for rule_id in ACTIVE_RULE_IDS:
        spec = _SPECS / f"{rule_id}.yaml"
        if spec.is_file() and "apparent_category" in spec.read_text(encoding="utf-8"):
            readers.append(rule_id)
    # LP-390-7 activated AS-2 + AS-12 (they read apparent_category, now measured 100% concrete, LP-390-5a) —
    # the INTENDED live consumers. No OTHER live rule reads it, so the LP-379-E widening still cannot silently
    # change an UNINTENDED live verdict. (AS-2's trigger is loan_proceeds — an original enum value, unaffected
    # by the widening; AS-12 is judgmental — a human ratifies every verdict.)
    assert set(readers) == {"AS-2", "AS-12"}


def test_as1_does_not_read_apparent_category() -> None:
    # AS-1 (live, auto-shipping) reads is_money_in / amount / has_identified_source / source_strength — never
    # apparent_category. So its verdict is IDENTICAL regardless of the enum (structural equivalence, D3).
    as1 = (_SPECS / "AS-1.yaml").read_text(encoding="utf-8")
    assert "apparent_category" not in as1
    assert "txn.is_money_in" in as1 and "txn.has_identified_source" in as1


def test_no_rule_activation_changed() -> None:
    assert ACTIVE_RULE_IDS == (
        "AS-1",
        "OC-2",
        "ID-2",
        "ID-4",
        "ID-1",
        "ID-3",
        "ID-6",
        "ID-7",
        "ID-9",
        "ID-8",
        "IN-2",
        # LP-389 — the first activation pass, via the eligibility gate (activation_bars.is_eligible)
        "IN-1",
        "IN-5",
        "ID-5",  # LP-389-A — the subject mismatch fixed (per-borrower), input now resolves
        # LP-384 — the second activation pass: the stuck deterministic rules, verified on build_lf6t3n_plus
        "AS-9",
        "IN-4",
        "AS-10",
        "AS-2",
        "AS-12",
        "IN-3",
        "IN-7",
        "IN-10",
        "IN-11",
        "AS-11",
        "AS-8",  # LP-406-2b — the first Bucket 2 rule live (statement chaining on stmt.continuity)
        "IN-6",  # LP-412 — Priya signed off the 0.95 bar (calibratable-now, same as IN-5)
        "PC-7",  # LP-412 — Priya signed off the closing window (no-ai-threshold-pending)
        "PC-2",  # LP-407-3 — purchase price matches loan terms
        "IH-3",  # LP-417 — insurance effective date vs closing
        "PC-3",  # LP-407-4 — contract property address vs the loan file
    )
