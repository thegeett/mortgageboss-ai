"""LP-333 — income activation: the derived-reads-materialized-tags data-flow fix + IN-2 live.

THE DATA-FLOW FIX (the diagnosis's linchpin): a derived recipe may AGGREGATE other materialized tags
(the income recipes sum a borrower's documented income across its documents), but `produce_derived_tags`
was fed the ORIGINAL (pre-materialization) snapshot, so it read an empty tags layer → every income
derived tag abstained → the rule couldnt_checked LIVE. LP-333 runs derived LAST against a snapshot
carrying the freshly-built parsed + AI tags. This module proves it, and proves IN-2 (parsed-only, no
uncalibrated AI) now activates end-to-end.

IN-1 stays evaluated + correct (the LP-332 mechanism) but is DE-ACTIVATED: its feed (income.documented_monthly)
is an uncalibrated AI structuring tag feeding a deterministic fraud verdict, and is not wired into the
orchestrator's required AI groups. See docs/tickets/LP-333.md.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rule_engine.result import Verdict
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.tag_materialization.ai import (
    AiGroupResult,
    AiSubjectJudgment,
    AiTagJudgment,
)
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio

_B = uuid4()

# Materialize with NO AI groups — IN-2's chain is parsed → derived only (no uncalibrated AI).
_NO_AI = frozenset()
_SUBJECTS = frozenset({"document", "loan", "borrower"})


def _f(value: str) -> Field:
    return Field.present(value, source=FieldSource.EXTRACTED)


def _snap(*, doc_fields: dict, mismo: dict | None = None) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
        documents=DocumentsSection.present(
            [
                DocumentEntry(
                    content_id="ps",
                    document_type="pay_stub",
                    belongs_to=(BorrowerRef(borrower_id=_B, name="Sam"),),
                    fields={k: _f(v) for k, v in doc_fields.items()},
                )
            ]
        ),
        mismo=MismoSection.present(mismo or {"borrower.1.borrower_id": _f(str(_B))}),
        tags=TagsSection.present({}),
    )


# --------------------------------------------------------------------------- #
# THE DATA-FLOW FIX — a derived recipe reads tags materialized THIS run
# --------------------------------------------------------------------------- #
async def test_derived_recipe_reads_freshly_parsed_tags() -> None:
    # income.pay_date (parsed) → income.days_since_most_recent_pay (derived) must see it. Before the fix
    # the derived recipe read the pre-materialization (empty) tags → "unknown".
    out = await materialize_tags(
        _snap(doc_fields={"pay_date": "2026-05-20"}), only_groups=_NO_AI, only_subjects=_SUBJECTS
    )
    days = out.tags.by_subject["loan"]["income.days_since_most_recent_pay"]
    assert days.value == "56"  # 2026-07-15 - 2026-05-20, computed from the freshly-parsed pay_date


async def test_derived_abstains_when_its_feeding_tag_is_absent() -> None:
    # No pay_date field → income.pay_date absent → the derived tag abstains (honest couldnt_check feed).
    out = await materialize_tags(_snap(doc_fields={}), only_groups=_NO_AI, only_subjects=_SUBJECTS)
    assert out.tags.by_subject["loan"]["income.days_since_most_recent_pay"].value == "unknown"


class _AiStub:
    """A deterministic income_amounts reasoner — returns the given short-name values for each subject."""

    def __init__(self, by_short: dict[str, str]) -> None:
        self.by_short = by_short

    async def __call__(self, context_json: str) -> AiGroupResult:
        subjects = json.loads(context_json)["subjects"]
        judgments = [
            AiSubjectJudgment(
                index=int(s["index"]),
                tags={k: AiTagJudgment(v, 0.9, "stub") for k, v in self.by_short.items()},
            )
            for s in subjects
        ]
        return AiGroupResult(judgments, 1, 1, "stub", False)


async def test_derived_recipe_reads_freshly_produced_ai_tags() -> None:
    # THE REORDER'S MOTIVATING CASE (AI → derived): income.documented_monthly is an AI tag (income_amounts
    # group), and the per-borrower shortfall recipe AGGREGATES it. Derived runs LAST, so the AI tag produced
    # THIS run is visible. Before the fix (derived BEFORE ai) the recipe read an empty tags layer → abstained.
    snap = _snap(
        doc_fields={},  # the AI stub supplies documented_monthly — not a parsed field
        mismo={
            "borrower.1.borrower_id": _f(str(_B)),
            "borrower.1.income.1.monthly_amount": _f("5000"),
        },
    )
    stub = _AiStub({"type": "base", "documented_monthly": "3000", "qualifying_monthly": "3000"})
    out = await materialize_tags(
        snap,
        ai_reasoners={"income_amounts": stub},
        only_groups=frozenset({"income_amounts"}),
        only_subjects=_SUBJECTS,
    )
    # The AI tag materialized on the document this run...
    assert out.tags.by_subject["ps"]["income.documented_monthly"].value == "3000"
    # ...and the derived PER-BORROWER recipe SAW it: (5000 - 3000) / 5000 = 0.4 (AI → derived, reorder).
    assert out.tags.by_subject[str(_B)]["income.documented_income_shortfall_pct"].value == "0.4"


# --------------------------------------------------------------------------- #
# IN-2 ACTIVATES — a REAL verdict end-to-end through the orchestrator (not couldnt_check)
# --------------------------------------------------------------------------- #
async def test_in2_is_active() -> None:
    # LP-333 activated IN-2 and deferred IN-1; LP-389 re-activated IN-1 (documented_monthly now calibrated 100%).
    assert "IN-2" in ACTIVE_RULE_IDS and "IN-1" in ACTIVE_RULE_IDS


async def test_in2_fires_end_to_end_through_the_registry() -> None:
    # A stale pay stub (56 days > the 30-day window) → IN-2 FIRES, a REAL verdict, not couldnt_check.
    out = await materialize_tags(
        _snap(doc_fields={"pay_date": "2026-05-20"}), only_groups=_NO_AI, only_subjects=_SUBJECTS
    )
    results, _ = await evaluate_rules(out, rule_ids=("IN-2",))
    assert [r.verdict for r in results] == [Verdict.FIRED] and results[0].reasoning


async def test_in2_satisfied_for_a_recent_paystub() -> None:
    out = await materialize_tags(
        _snap(doc_fields={"pay_date": "2026-07-05"}), only_groups=_NO_AI, only_subjects=_SUBJECTS
    )
    results, _ = await evaluate_rules(out, rule_ids=("IN-2",))
    assert [r.verdict for r in results] == [Verdict.SATISFIED]  # 10 days old, within the window


async def test_in2_couldnt_check_when_no_pay_date() -> None:
    # The degraded path holds — a file with no pay date → couldnt_check (never a fabricated recency).
    out = await materialize_tags(_snap(doc_fields={}), only_groups=_NO_AI, only_subjects=_SUBJECTS)
    results, _ = await evaluate_rules(out, rule_ids=("IN-2",))
    assert [r.verdict for r in results] == [Verdict.COULDNT_CHECK]


# --------------------------------------------------------------------------- #
# THE LOAN CANARY — id.app_required_fields_present unchanged under the reorder
# --------------------------------------------------------------------------- #
async def test_loan_recipe_unchanged_under_the_reorder() -> None:
    # id.app_required_fields_present reads raw MISMO (not tags) → the derived-last reorder is a no-op.
    complete = _snap(
        doc_fields={},
        mismo={
            "borrower.1.borrower_id": _f(str(_B)),
            # LP-509-A2: the real emitted key names (first_name/last_name, address_line).
            "borrower.1.first_name": _f("Sam"),
            "borrower.1.last_name": _f("Tan"),
            "borrower.1.ssn": _f("x"),
            "loan.amount": _f("100"),
            "property.address_line": _f("1 Main"),
        },
    )
    out = await materialize_tags(complete, only_groups=_NO_AI, only_subjects=_SUBJECTS)
    assert out.tags.by_subject["loan"]["id.app_required_fields_present"].value == "complete"
