"""bug-016 — IN-7 asked a borrower who never changed jobs for an offer letter.

On LF-XMB2, borrower 2 has held one job since 2021-01-25 and IN-7 still told the processor to "obtain an
offer letter, contract, and pay stubs from the new position". The rule's prose scope says "every borrower
on the loan with a job change"; its judgment block tested for nothing, so it ran on every borrower.

The tag it reasons over cannot scope it either: `income.same_line_of_work`'s production prompt answers
"yes" when there is a single employer throughout, so "never changed jobs" and "moved within the same
field" are the same answer there. The scope has to come from the APPLICATION's employment records, which
is the only place that says what came before.

Two halves, tested here: the recipe that reads those records, and the rule that is now scoped by it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult
from app.verification.rule_engine.judgment import evaluate_judgment_rule
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.pii import PiiField
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.derived import _income_has_job_change
from app.verification.tag_materialization.subjects import BorrowerSubject

pytestmark = pytest.mark.anyio

_B = UUID("00000000-0000-0000-0000-0000000b0016")


def _f(value: str) -> Field:
    return Field.present(value, source=FieldSource.EXTRACTED)


def _tag(value: str) -> Tag:
    return Tag(
        value=value,
        confidence=None,
        reasoning="fixture",
        source_facts=("raw",),
        produced_by=TagProducedBy.PARSED,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _snap(
    *,
    mismo: dict[str, Field | PiiField] | None = None,
    tags: dict[str, dict[str, Tag]] | None = None,
    docs: list[DocumentEntry] | None = None,
) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 9, 11, tzinfo=UTC),
        documents=DocumentsSection.present(list(docs or [])),
        mismo=MismoSection.present(mismo or {}),
        tags=TagsSection.present(tags or {}),
    )


def _value(mismo: dict[str, Field | PiiField], *, index: int = 1) -> str:
    snap = _snap(mismo=mismo)
    value, _reason = _income_has_job_change(snap, str(_B), BorrowerSubject(str(_B), index, snap))
    return str(value)


# --------------------------------------------------------------------------- #
# The recipe — read from the application's own employment records
# --------------------------------------------------------------------------- #
def test_a_prior_employer_and_a_current_one_is_a_job_change() -> None:
    """THE LF-XMB2 BORROWER 1 SHAPE: PNC ended 2026-03-03, FNB current from 2026-03-09."""
    assert (
        _value(
            {
                "borrower.1.employer.1.is_current": _f("False"),
                "borrower.1.employer.1.end_date": _f("2026-03-03"),
                "borrower.1.employer.2.is_current": _f("True"),
                "borrower.1.employer.2.start_date": _f("2026-03-09"),
            }
        )
        == "yes"
    )


def test_is_current_false_counts_as_ended_without_an_end_date() -> None:
    """Either flag is the same fact said a different way, and a MISMO export may carry only one."""
    assert (
        _value(
            {
                "borrower.1.employer.1.is_current": _f("False"),
                "borrower.1.employer.2.is_current": _f("True"),
            }
        )
        == "yes"
    )


def test_a_single_current_employer_is_not_a_job_change() -> None:
    """THE LF-XMB2 BORROWER 2 SHAPE — the finding this ticket exists to stop."""
    assert (
        _value(
            {
                "borrower.1.employer.1.is_current": _f("True"),
                "borrower.1.employer.1.start_date": _f("2021-01-25"),
            }
        )
        == "no"
    )


def test_employment_that_has_only_ended_is_not_a_job_change() -> None:
    """A termination is IN-15's question. Calling it a job change would send IN-7 after an offer letter
    for a role the borrower does not have."""
    assert (
        _value(
            {
                "borrower.1.employer.1.is_current": _f("False"),
                "borrower.1.employer.1.end_date": _f("2026-01-31"),
            }
        )
        == "no"
    )


def test_an_ended_employer_beside_a_flagless_one_is_still_a_job_change() -> None:
    """bug-016 review — THE ROW THAT STATED NEITHER FLAG USED TO VANISH.

    The count was `if ended … elif is_current`, so a record with no `is_current` and no `end_date` was
    neither, and a borrower with one ENDED employer beside one flagless employer read "no" — IN-7
    skipping a real job change in silence, which is the failure its scope exists to prevent, inverted.

    Not hypothetical in shape: `stated_employers.is_current` is nullable and, as its own column comment
    records, every employer imported before LP-624 carried NULL there; `put()` omits a NULL, so those
    rows reach the snapshot stating only a name — exactly what LF-6T3N's fixture still does.
    """
    assert (
        _value(
            {
                "borrower.1.employer.1.is_current": _f("False"),
                "borrower.1.employer.1.end_date": _f("2026-03-03"),
                "borrower.1.employer.2.name": _f("Northgate Warehousing"),  # states neither flag
            }
        )
        == "yes"
    )


def test_employers_stating_no_flags_at_all_are_not_a_job_change() -> None:
    """The other half of that repair, and why it is not just "count everything as current": with NOTHING
    ended there is no move to judge. LF-6T3N's shape — two employer rows per borrower, names only — must
    stay "no", which is what keeps IN-7 out of scope there rather than asking about an unevidenced move.
    """
    assert (
        _value(
            {
                "borrower.1.employer.1.name": _f("Acme Logistics Inc"),
                "borrower.1.employer.2.name": _f("Northgate Warehousing"),
            }
        )
        == "no"
    )


def test_no_employment_records_is_unknown_never_no() -> None:
    """FAIL-CLOSED. "no" would silently remove IN-7 from a file whose employment simply was not
    imported; "unknown" makes the rule abstain and say so."""
    assert _value({"borrower.1.borrower_id": _f(str(_B))}) == "unknown"


def test_an_absent_application_is_unknown() -> None:
    snap = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 9, 11, tzinfo=UTC),
        documents=DocumentsSection.present([]),
        mismo=MismoSection.failed("no import"),
        tags=TagsSection.present({}),
    )
    value, reason = _income_has_job_change(snap, str(_B), BorrowerSubject(str(_B), 1, snap))
    assert value == "unknown" and "not on the file" in reason


def test_one_borrowers_job_change_does_not_reach_another() -> None:
    """Borrower 1 moved; borrower 2 did not. The recipe reads only its own subject's index."""
    facts: dict[str, Field | PiiField] = {
        "borrower.1.employer.1.is_current": _f("False"),
        "borrower.1.employer.1.end_date": _f("2026-03-03"),
        "borrower.1.employer.2.is_current": _f("True"),
        "borrower.2.employer.1.is_current": _f("True"),
    }
    assert _value(facts, index=1) == "yes"
    assert _value(facts, index=2) == "no"


def test_a_non_borrower_subject_abstains() -> None:
    snap = _snap()
    value, _reason = _income_has_job_change(snap, "loan", object())
    assert value == "unknown"


# --------------------------------------------------------------------------- #
# The rule — IN-7 is scoped by it, BEFORE the gate and before any AI call
# --------------------------------------------------------------------------- #
class _Reasoner:
    def __init__(self, value: str) -> None:
        self.value = value
        self.calls = 0

    async def __call__(self, _context: str) -> RuleJudgmentResult:
        self.calls += 1
        return RuleJudgmentResult(RuleJudgment(self.value, 0.9, "stub"), 1, 1, "stub", False)


def _borrower_snap(tags: dict[str, Tag]) -> Snapshot:
    return _snap(
        docs=[
            DocumentEntry(
                content_id="docpaystub00000001",
                document_type="pay_stub",
                belongs_to=(BorrowerRef(borrower_id=_B, name="fixture"),),
            )
        ],
        tags={str(_B): tags},
    )


async def test_a_borrower_who_has_not_changed_jobs_is_out_of_scope() -> None:
    """THE FIX. not_applicable — and the model is never asked, so an out-of-scope borrower costs
    nothing in spend as well as nothing on the processor's queue."""
    stub = _Reasoner("yes")
    results = await evaluate_judgment_rule(
        load_rule_spec("IN-7"),
        _borrower_snap(
            {
                "income.has_job_change": _tag("no"),
                "income.same_line_of_work": _tag("yes"),
            }
        ),
        reasoner=stub,
    )

    assert [r.evaluation.verdict for r in results] == [Verdict.NOT_APPLICABLE]
    assert stub.calls == 0


async def test_a_borrower_who_did_change_jobs_is_still_judged() -> None:
    stub = _Reasoner("yes")
    results = await evaluate_judgment_rule(
        load_rule_spec("IN-7"),
        _borrower_snap(
            {
                "income.has_job_change": _tag("yes"),
                "income.same_line_of_work": _tag("yes"),
            }
        ),
        reasoner=stub,
    )

    (result,) = results
    assert result.evaluation.verdict is Verdict.NEEDS_REVIEW  # a judgment never auto-ships
    assert result.evaluation.ratification_pending and stub.calls == 1


async def test_an_unstated_employment_history_abstains_rather_than_judging() -> None:
    """absent ≠ out of scope. The rule cannot judge a job change it cannot see, and says so."""
    stub = _Reasoner("yes")
    results = await evaluate_judgment_rule(
        load_rule_spec("IN-7"),
        _borrower_snap({"income.same_line_of_work": _tag("yes")}),
        reasoner=stub,
    )

    (result,) = results
    assert result.evaluation.verdict is Verdict.COULDNT_CHECK and stub.calls == 0


async def test_a_same_field_move_is_no_longer_told_to_document_a_new_position() -> None:
    """The third half of the bug: "yes" had no wording of its own, so it borrowed the text written for a
    borrower who changed FIELD — "Document the new position …" — which is not what a same-line move
    needs. It needs the income evidenced in the role the borrower now holds."""
    stub = _Reasoner("yes")
    results = await evaluate_judgment_rule(
        load_rule_spec("IN-7"),
        _borrower_snap(
            {
                "income.has_job_change": _tag("yes"),
                "income.same_line_of_work": _tag("yes"),
            }
        ),
        reasoner=stub,
    )

    fix = results[0].evaluation.how_to_fix or ""
    assert "Document the new position" not in fix
    assert "pay stub" in fix.lower() and "verification of employment" in fix.lower()
