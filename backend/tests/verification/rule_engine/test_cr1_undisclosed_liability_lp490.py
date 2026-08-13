"""LP-490 — CR-1 (undisclosed liability). ⚠️ BUILDS INERT.

⚠️ INERT BY DESIGN. CR-1 gates on `liab.in_application`, an AI tag with no measured accuracy. Its bar is
`not-calibratable-yet`, for which `is_eligible()` returns False (LP-484), so CR-1 is NOT live. A test
below pins that, so a later ticket cannot activate it by accident.

⚠️ ONE MATCHER, TWO VIEWS. LP-483 built the comparison once, as the `credit_profile` AI group on the
LIABILITY subject (ADR-375). CR-1 reads that per-liability judgment directly (WHICH debt); CR-4 reads
`credit.undisclosed_tradeline`, a deterministic borrower rollup over the SAME tag. This file proves they
cannot disagree about one file — the reason no second matcher was written here.

⚠️ EVERY VERDICT ASSERTION RUNS THROUGH A REAL RULE EVALUATION (LP-487's standing rule): a scripted
`credit_profile` reasoner drives materialize_tags(), which produces the per-liability tag AND the derived
rollup, and both rules are then evaluated by the real evaluator. Nothing is asserted by calling a recipe.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.verification.eval.stubs import stub_materialization_reasoners
from app.verification.rule_engine.activation_bars import is_eligible, load_activation_bars
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rule_engine.result import Verdict
from app.verification.rules.distrust import distrusted_tag_ids
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    ListRow,
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

_STUB_MODEL = "stub-cr1"
_BORROWER_ID = UUID("96000000-0000-4000-8000-000000000001")
_BORROWER = (BorrowerRef(borrower_id=_BORROWER_ID, name="Test Borrower"),)


class _ScriptedMatcher:
    """Replays the `credit_profile` group with a per-subject answer, keyed by the tradeline's creditor.

    ⚠️ It answers the ONE narrow question the real group asks — "is THIS debt on the application?" — and
    nothing else. It never decides a verdict; the rule does.
    """

    def __init__(self, by_creditor: dict[str, str]) -> None:
        self.by_creditor = by_creditor
        self.calls = 0

    async def __call__(self, context_json: str) -> AiGroupResult:
        self.calls += 1
        payload = json.loads(context_json)
        judgments = []
        for subject in payload.get("subjects", []):
            # ⚠️ KEY ON THE SUBJECT'S OWN creditor_name, never on the whole context blob. The context
            # deliberately includes ALL the stated liabilities (that is the other side of the
            # comparison), so a substring match against the blob resolves every subject to the same
            # answer — a fixture bug that would have made these assertions meaningless.
            answer = self.by_creditor.get(str(subject.get("creditor_name", "")), "unknown")
            judgments.append(
                AiSubjectJudgment(
                    index=int(subject["index"]),
                    tags={"in_application": AiTagJudgment(answer, 0.9, "scripted for the test")},
                )
            )
        return AiGroupResult(
            judgments, input_tokens=1, output_tokens=1, model=_STUB_MODEL, truncated=False
        )


def _tradelines(rows: list[dict[str, str]]) -> DocumentEntry:
    return DocumentEntry(
        content_id="cr-1",
        document_type="credit_report",
        # ⚠️ A BORROWER IS REQUIRED FOR CR-4. Borrower subjects come from documents' `belongs_to`
        # (LP-202), and CR-4's rollup materialises on the BORROWER subject — with no borrower there is
        # no rollup and CR-4 abstains, which would make the CR-1/CR-4 agreement proof vacuous.
        belongs_to=_BORROWER,
        fields={"report_date": Field.present("2026-07-01", source=FieldSource.EXTRACTED)},
        lists={
            "tradelines": tuple(
                ListRow(
                    fields={
                        k: Field.present(v, source=FieldSource.EXTRACTED) for k, v in row.items()
                    },
                    row_id=f"cr-1-row{i}",
                )
                for i, row in enumerate(rows)
            )
        },
    )


def _mismo(liabilities: list[tuple[str, str, str, str]]) -> dict[str, Field]:
    # ⚠️ THE BORROWER FACTS ARE REQUIRED FOR CR-4. Borrower subjects are enumerated from MISMO
    # `borrower.{n}.borrower_id` (NOT from documents' belongs_to), and CR-4's rollup materialises on the
    # borrower subject — without one there is no rollup, CR-4 abstains, and the CR-1/CR-4 agreement
    # proof below would pass vacuously.
    out: dict[str, Field] = {
        "borrower.1.borrower_id": Field.present(str(_BORROWER_ID), source=FieldSource.PARSED),
        "borrower.1.first_name": Field.present("Test", source=FieldSource.PARSED),
    }
    for index, (ltype, holder, payment, balance) in enumerate(liabilities, start=1):
        for name, value in (
            ("type", ltype),
            ("holder_name", holder),
            ("monthly_payment", payment),
            ("unpaid_balance", balance),
        ):
            out[f"liability.{index}.{name}"] = Field.present(value, source=FieldSource.PARSED)
    return out


def _snapshot(rows: list[dict[str, str]], liabilities: list[tuple[str, str, str, str]]) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        documents=DocumentsSection.present([_tradelines(rows)] if rows else []),
        mismo=MismoSection.present(_mismo(liabilities)),
        tags=TagsSection.present({}),
    )


def _reasoners(answers: dict[str, str]) -> dict:
    """⚠️ STUB EVERY DECLARED GROUP, then override `credit_profile`.

    Overriding one group alone is NOT enough: materialize_tags runs every declared AI group, and any
    group without a seam falls through to the REAL MODEL. An earlier version of this file did exactly
    that and made live API calls from the test suite. A complete seam is the only safe shape.
    """
    return {**stub_materialization_reasoners(), "credit_profile": _ScriptedMatcher(answers)}


async def _evaluate(snapshot: Snapshot, answers: dict[str, str], rule_id: str):
    """The REAL path: scripted matcher → materialisation (per-liability tag + derived rollup) → the
    real rule evaluator."""
    materialized = await materialize_tags(snapshot, ai_reasoners=_reasoners(answers))
    evaluations, _tags = await evaluate_rules(materialized, rule_ids=(rule_id,))
    return evaluations


# --------------------------------------------------------------------------- #
# ⚠️ INERT — the first thing this cohort must prove
# --------------------------------------------------------------------------- #
def test_cr1_is_inert_and_cannot_be_eligible() -> None:
    """`not-calibratable-yet` → is_eligible False (LP-484). If a later ticket sets validated:true or
    changes the status to force this rule live without scoring liab.in_application, this fails."""
    bar = load_activation_bars()["CR-1"]
    assert bar.status == "not-calibratable-yet"
    assert bar.validated is False
    assert not is_eligible(bar)
    assert "CR-1" not in ACTIVE_RULE_IDS
    assert bar.load_bearing_ai_tags == ("liab.in_application",)


# --------------------------------------------------------------------------- #
# LF-96SV's shape — the ONE real file carrying both sides
# --------------------------------------------------------------------------- #
_LF96SV_STATED = [
    ("Revolving", "DIGITAL FED CREDIT UNI", "502", "10600"),
    ("Revolving", "HAPPEN BANK", "386", "10518"),
    ("Revolving", "DISCOVERC", "209", "10430"),
    ("Revolving", "AMEX", "269", "4212"),
    ("Revolving", "BANK OF AMERICA", "66", "66"),
]
_LF96SV_ROWS = [
    {"creditor_name": "DIGITAL FED CREDIT UNI", "monthly_payment": "502", "balance": "10600"},
    {"creditor_name": "HAPPEN BANK", "monthly_payment": "386", "balance": "10518"},
    {"creditor_name": "DISCOVERC", "monthly_payment": "209", "balance": "10430"},
    {"creditor_name": "AMEX", "monthly_payment": "269", "balance": "4212"},
    {"creditor_name": "BANK OF AMERICA", "monthly_payment": "66", "balance": "66"},
]


async def test_lf96sv_shape_reports_no_undisclosed_debt_among_the_rows_extracted() -> None:
    """⚠️ THE HONEST CLAIM IS BOUNDED. LF-96SV's payment total 1432 = 502+386+209+269+66 gives a 1:1
    correspondence FROM DATA, so the expected answer is "none undisclosed". But the extraction is
    `partial` and `total_tradeline_count` is not a declared field, so completeness is UNVERIFIABLE: this
    file supports a negative among THE ROWS EXTRACTED, and cannot prove absence.

    The fixture reproduces that shape (the amounts, not the borrower's data — no PII enters the repo)."""
    snapshot = _snapshot(_LF96SV_ROWS, _LF96SV_STATED)
    answers = {row["creditor_name"]: "yes" for row in _LF96SV_ROWS}
    evaluations = await _evaluate(snapshot, answers, "CR-1")
    verdicts = [e.verdict for e in evaluations if e.verdict is not Verdict.NOT_APPLICABLE]
    assert verdicts == [Verdict.SATISFIED] * 5
    assert Verdict.FIRED not in verdicts


async def test_a_tradeline_with_no_counterpart_is_undisclosed() -> None:
    """The adversarial case: a sixth tradeline the application never states."""
    rows = [
        *_LF96SV_ROWS,
        {"creditor_name": "CAPITAL ONE", "monthly_payment": "150", "balance": "3200"},
    ]
    answers = {row["creditor_name"]: "yes" for row in _LF96SV_ROWS} | {"CAPITAL ONE": "no"}
    evaluations = await _evaluate(_snapshot(rows, _LF96SV_STATED), answers, "CR-1")
    fired = [e for e in evaluations if e.verdict is Verdict.FIRED]
    assert len(fired) == 1, "exactly the unmatched tradeline fires"
    # ⚠️ The finding names WHICH debt — that is the whole reason CR-1 is per-liability rather than a
    # borrower-level yes/no. The sixth tradeline is row index 5.
    assert fired[0].subject_id == "cr-1-row5"
    satisfied = [e for e in evaluations if e.verdict is Verdict.SATISFIED]
    assert len(satisfied) == 5, "the five matched debts still resolve"


async def test_an_ambiguous_pair_couldnt_checks_rather_than_guessing() -> None:
    """⚠️ `unknown` → couldnt_check ON THAT DEBT ALONE. The rule does not need to be certain about every
    debt to be useful on the others — the other four still resolve."""
    answers = {row["creditor_name"]: "yes" for row in _LF96SV_ROWS} | {"DISCOVERC": "unknown"}
    evaluations = await _evaluate(_snapshot(_LF96SV_ROWS, _LF96SV_STATED), answers, "CR-1")
    verdicts = [e.verdict for e in evaluations if e.verdict is not Verdict.NOT_APPLICABLE]
    assert verdicts.count(Verdict.COULDNT_CHECK) == 1
    assert verdicts.count(Verdict.SATISFIED) == 4
    assert Verdict.FIRED not in verdicts


async def test_a_stated_liability_with_no_tradeline_is_not_a_cr1_finding() -> None:
    """⚠️ THE REVERSE DIRECTION IS OUT OF SCOPE. CR-1 asks, of each REPORTED debt, "is it on the
    application?". A stated liability with no tradeline is the opposite question, and CR-12's lesson
    (LP-486) is that leaving it in scope produces permanent, unfixable couldnt_checks — a file with 8
    stated liabilities produced 8 of them."""
    stated = [*_LF96SV_STATED, ("Installment", "SOFI PERSONAL LOAN", "310", "9000")]
    evaluations = await _evaluate(
        _snapshot(_LF96SV_ROWS, stated),
        {row["creditor_name"]: "yes" for row in _LF96SV_ROWS},
        "CR-1",
    )
    in_scope = [e for e in evaluations if e.verdict is not Verdict.NOT_APPLICABLE]
    assert len(in_scope) == 5, "only the five REPORTED tradelines are judged"
    assert all(e.verdict is Verdict.SATISFIED for e in in_scope)


async def test_no_credit_report_yields_no_false_all_clear() -> None:
    """⚠️ NEVER SATISFIED ON A MISSING DOCUMENT. "No undisclosed liabilities" on a file with no credit
    report is a false all-clear, which is worse than saying nothing. With no report there are no
    reported-liability subjects, so CR-1 produces no `satisfied` at all."""
    evaluations = await _evaluate(_snapshot([], _LF96SV_STATED), {}, "CR-1")
    assert Verdict.SATISFIED not in [e.verdict for e in evaluations]


# --------------------------------------------------------------------------- #
# ⚠️ CR-1 AND CR-4 CANNOT DISAGREE — the reason no second matcher was written
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("answers", "cr1_has_fired", "cr4_expected"),
    [
        ({r["creditor_name"]: "yes" for r in _LF96SV_ROWS}, False, Verdict.SATISFIED),
        ({**{r["creditor_name"]: "yes" for r in _LF96SV_ROWS}, "AMEX": "no"}, True, Verdict.FIRED),
        ({r["creditor_name"]: "unknown" for r in _LF96SV_ROWS}, False, Verdict.COULDNT_CHECK),
    ],
)
async def test_cr1_and_cr4_cannot_disagree(
    answers: dict[str, str], cr1_has_fired: bool, cr4_expected: Verdict
) -> None:
    """One matcher, two views — proven on the SAME materialised snapshot, through the real evaluator for
    both rules. CR-4's borrower rollup is a pure function of CR-1's per-liability answers, so whenever
    CR-1 fires on any debt CR-4 fires for the borrower, and when every answer is unknown both abstain."""
    snapshot = _snapshot(_LF96SV_ROWS, _LF96SV_STATED)
    materialized = await materialize_tags(snapshot, ai_reasoners=_reasoners(answers))
    cr1, _ = await evaluate_rules(materialized, rule_ids=("CR-1",))
    cr4, _ = await evaluate_rules(materialized, rule_ids=("CR-4",))
    assert (Verdict.FIRED in [e.verdict for e in cr1]) is cr1_has_fired
    assert [e.verdict for e in cr4] == [cr4_expected]


# --------------------------------------------------------------------------- #
# Structure
# --------------------------------------------------------------------------- #
def test_cr1_is_scoped_to_reported_tradelines() -> None:
    applicability = load_rule_spec("CR-1").deterministic.applicability
    assert applicability is not None
    assert (applicability.tag, applicability.op, applicability.value) == (
        "liability.source",
        "eq",
        "credit_report_reported",
    )


def test_the_catch_all_is_an_abstain_not_a_pass() -> None:
    """A `satisfied` default would read an unresolvable pair as disclosed — the false match that hides
    the undisclosed debt this rule exists to catch."""
    outcomes = load_rule_spec("CR-1").deterministic.outcomes
    assert [o.verdict for o in outcomes] == ["fired", "satisfied", "couldnt_check"]
    assert outcomes[-1].default is True


def test_cr1_reads_no_distrusted_tag() -> None:
    gated = set(load_rule_spec("CR-1").deterministic.gated_tags)
    assert not (gated & set(distrusted_tag_ids()))
