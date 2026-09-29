"""LP-923's "Done when": a statement missing a page cannot reach Ready, a statement for the wrong
account is rejected with the reason, and a new large deposit is flagged before submission.

Round 1 of the fictional file is confirmed and the borrower email marked sent (so 7086, 6132 and 6637
are Waiting on Borrower). Statements are the fixture's Capital One ··9912 (`statement_fixture`), stored
as the extractor stores them; every check reads them by code.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from app.models.condition import Condition, ConditionPrepStatus
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_evidence import ConditionEvidence, EvidenceStatus
from app.models.condition_item import ConditionItem
from app.models.condition_vocabulary import ConditionItemStatus
from app.models.loan_file import LoanFile
from app.services import condition_evidence, condition_reading
from app.services.condition_drafts import mark_sent
from app.services.condition_evidence import EvidenceRefused, check_document
from app.services.conditions import condition_summary
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.reading_fixture import fake_complete
from tests.conditions.statement_fixture import add_statement, august, july, july_and_august
from tests.conditions.test_condition_drafts import _confirmed, _drafts

TODAY = date(2026, 9, 2)
#: The screens' en dash (S3-07 prints "pages 1 to 5" with one).
DASH = "\u2013"


@pytest.fixture(autouse=True)
def _mocked_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(condition_reading, "complete", fake_complete())


async def _asked(db: AsyncSession) -> tuple[LoanFile, dict[str, Condition], Any]:
    """Round 1 confirmed, the borrower email marked sent: 7086, 6132, 6637 Waiting on Borrower."""
    loan_file, _, conditions, actor = await _confirmed(db)
    borrower, _ = (await _drafts(db, loan_file))["borrower"]
    await mark_sent(db, loan_file=loan_file, draft=borrower, actor_user_id=actor)
    return loan_file, conditions, actor


async def _evidence(db: AsyncSession, condition: Condition) -> list[ConditionEvidence]:
    return list(
        (
            await db.execute(
                select(ConditionEvidence).where(ConditionEvidence.condition_id == condition.id)
            )
        ).scalars()
    )


def _results(evidence: ConditionEvidence) -> dict[str, tuple[str, str]]:
    """The checks as the sheet shows them: the stored ones, and the deposit row from the findings."""
    from app.services.condition_evidence import deposit_check

    out = {c["check"]: (c["result"], c["reason"]) for c in evidence.checks}
    if "covers_required_funds" in out:
        row = deposit_check(evidence.findings or [])
        out[row["check"]] = (row["result"], row["reason"])
    return out


async def test_a_statement_missing_a_page_cannot_reach_ready(db_session: AsyncSession) -> None:
    """S3-07: the August statement arrives with pages 1-5 of 6."""
    loan_file, conditions, _ = await _asked(db_session)
    await check_document(
        db_session, document_id=(await add_statement(db_session, loan_file, july())).id, today=TODAY
    )
    aug = await add_statement(db_session, loan_file, august(pages_present=5))
    await check_document(db_session, document_id=aug.id, today=TODAY)

    (row,) = [e for e in await _evidence(db_session, conditions["6132"]) if e.document_id == aug.id]
    assert _results(row) == {
        "right_account": ("passed", "Capital One ending 9912, matches the condition"),
        "right_period": (
            "passed",
            f"Aug 1{DASH}31, 2026 — the month right after July, already in the file",
        ),
        "right_borrower": ("passed", "Alex Rivera"),
        "inside_lender_dates": (
            "passed",
            "statement date 08/31/2026; asset documents expire 10/30/2026",
        ),
        "all_pages": ("failed", f"pages 1{DASH}5 of 6 — page 6 is missing"),
    }
    assert conditions["6132"].prep_status is ConditionPrepStatus.WAITING
    # ONE DOCUMENT, CHECKED FOR EVERY ITEM IT ANSWERS (§4a change 2, LP-934 M1): 7086 fails it too.
    seven = [e for e in await _evidence(db_session, conditions["7086"]) if e.document_id == aug.id]
    assert seven and all(_results(e)["all_pages"][0] == "failed" for e in seven)
    assert conditions["7086"].prep_status is ConditionPrepStatus.WAITING


async def test_a_statement_for_the_wrong_account_is_rejected_with_the_reason(
    db_session: AsyncSession,
) -> None:
    loan_file, conditions, _ = await _asked(db_session)
    wrong = await add_statement(db_session, loan_file, august(last4="4471"))
    await check_document(db_session, document_id=wrong.id, today=TODAY)
    (row,) = await _evidence(db_session, conditions["6132"])
    assert _results(row)["right_account"] == (
        "failed",
        "Capital One ending 4471 — the condition asks for ending 9912",
    )
    item = await db_session.get(ConditionItem, row.item_id)
    assert item is not None and item.status is not ConditionItemStatus.DONE
    assert conditions["6132"].prep_status is ConditionPrepStatus.WAITING
    # 7086's "any other account" item is the one that may take another account's statement.
    other = [
        e
        for e in await _evidence(db_session, conditions["7086"])
        if (await db_session.get(ConditionItem, e.item_id)).key == "other_accounts"  # type: ignore[union-attr]
    ]
    assert len(other) == 1


async def test_a_new_large_deposit_is_flagged_before_submission(db_session: AsyncSession) -> None:
    """S3-08: the July and August statements together, 12 pages, with a $4,000.00 mobile deposit."""
    loan_file, conditions, _ = await _asked(db_session)
    both = await add_statement(db_session, loan_file, july_and_august())
    await check_document(db_session, document_id=both.id, today=TODAY)
    (row,) = [
        e
        for e in await _evidence(db_session, conditions["7086"])
        if (await db_session.get(ConditionItem, e.item_id)).key == "statements"  # type: ignore[union-attr]
    ]
    results = _results(row)
    assert results["covers_required_funds"] == (
        "passed",
        "verified $41,914.42 against $38,210.40 required",
    )
    assert results["no_large_deposit"] == ("failed", "08/21/2026 mobile deposit $4,000.00")
    (finding,) = row.findings
    assert finding == {
        "kind": "large_deposit",
        "citation": "Fannie Mae B3-4.2-02",
        "date": "2026-08-21",
        "amount": "4000.00",
        "description": "Mobile Deposit",
        "income": "5741.32",
        "threshold": "2870.66",
        "assets_without": "37914.42",
        "required": "38210.40",
        "needed": True,
        "status": "open",
    }
    # Payroll deposits ($2,650.66 each, under the threshold anyway) are not findings.
    assert conditions["7086"].prep_status is ConditionPrepStatus.WAITING


async def test_a_complete_statement_moves_the_condition_to_ready(db_session: AsyncSession) -> None:
    loan_file, conditions, _ = await _asked(db_session)
    await check_document(
        db_session, document_id=(await add_statement(db_session, loan_file, july())).id, today=TODAY
    )
    await check_document(
        db_session,
        document_id=(await add_statement(db_session, loan_file, august())).id,
        today=TODAY,
    )
    assert conditions["6132"].prep_status is ConditionPrepStatus.READY
    moved = (
        await db_session.execute(
            select(ConditionEvent.detail).where(
                ConditionEvent.condition_id == conditions["6132"].id,
                ConditionEvent.kind == ConditionEventKind.CONDITION_PREP_MOVED,
            )
        )
    ).scalars()
    assert {"prep_status_from": "waiting", "prep_status_to": "ready", "by": "evidence"} in list(
        moved
    )
    # 6637 still waits on title's receipt; its clearance item passed ($2,850.00 on 08/06/2026).
    assert conditions["6637"].prep_status is ConditionPrepStatus.WAITING
    clearance = [
        e
        for e in await _evidence(db_session, conditions["6637"])
        if (await db_session.get(ConditionItem, e.item_id)).key == "clearance"  # type: ignore[union-attr]
    ]
    assert _results(clearance[-1])["amount_matches"] == ("passed", "$2,850.00 on 08/06/2026")
    # The lender's track never moves.
    assert {c.lender_status.value for c in conditions.values()} == {"open"}


async def test_accept_anyway_needs_a_reason_and_is_kept(db_session: AsyncSession) -> None:
    loan_file, conditions, actor = await _asked(db_session)
    await check_document(
        db_session, document_id=(await add_statement(db_session, loan_file, july())).id, today=TODAY
    )
    aug = await add_statement(db_session, loan_file, august(pages_present=5))
    await check_document(db_session, document_id=aug.id, today=TODAY)
    (row,) = [e for e in await _evidence(db_session, conditions["6132"]) if e.document_id == aug.id]
    with pytest.raises(EvidenceRefused, match="Say why"):
        await condition_evidence.accept_anyway(
            db_session,
            condition=conditions["6132"],
            evidence_id=row.id,
            reason=" ",
            actor_user_id=actor,
        )
    await condition_evidence.accept_anyway(
        db_session,
        condition=conditions["6132"],
        evidence_id=row.id,
        reason="Page 6 is the bank's blank back page",
        actor_user_id=actor,
    )
    assert row.status is EvidenceStatus.ACCEPTED
    assert conditions["6132"].prep_status is ConditionPrepStatus.READY
    kept = (
        await db_session.execute(
            select(ConditionEvent.detail).where(
                ConditionEvent.condition_id == conditions["6132"].id,
                ConditionEvent.kind == ConditionEventKind.CONDITION_EVIDENCE_ACCEPTED,
            )
        )
    ).scalar_one()
    assert kept["reason"] == "Page 6 is the bank's blank back page"
    assert kept["failed"] == ["all_pages"]


async def test_the_reask_goes_into_a_new_borrower_email(db_session: AsyncSession) -> None:
    loan_file, conditions, actor = await _asked(db_session)
    aug = await add_statement(db_session, loan_file, august(pages_present=5))
    await check_document(db_session, document_id=aug.id, today=TODAY)
    (row,) = [e for e in await _evidence(db_session, conditions["6132"]) if e.document_id == aug.id]
    item = await condition_evidence.reask(
        db_session, condition=conditions["6132"], evidence_id=row.id, actor_user_id=actor
    )
    assert item.name == "Page 6 of the Capital One ··9912 August 2026 statement"
    # The round's borrower email was sent, so the re-ask is in a NEW unsent borrower draft.
    assert item.draft_id is not None
    drafts = await _drafts(db_session, loan_file)
    assert drafts["borrower"][0].id == item.draft_id
    assert "Page 6 of the Capital One" in (drafts["borrower"][1].body or "")


async def test_the_deposit_is_asked_about_or_explained(db_session: AsyncSession) -> None:
    loan_file, conditions, actor = await _asked(db_session)
    both = await add_statement(db_session, loan_file, july_and_august())
    await check_document(db_session, document_id=both.id, today=TODAY)
    (row,) = [e for e in await _evidence(db_session, conditions["7086"]) if e.findings]
    asked = await condition_evidence.answer_finding(
        db_session,
        condition=conditions["7086"],
        evidence_id=row.id,
        index=0,
        answer="ask",
        reason=None,
        actor_user_id=actor,
    )
    assert asked is not None
    assert asked.name == "Letter explaining the $4,000.00 deposit on 08/21/2026"
    # ASKED IS NOT ANSWERED: the check still fails and 7086 still waits.
    assert _results(row)["no_large_deposit"][0] == "failed"
    await condition_evidence.answer_finding(
        db_session,
        condition=conditions["7086"],
        evidence_id=row.id,
        index=0,
        answer="explained",
        reason="Gift from her mother; gift letter and transfer are in the file",
        actor_user_id=actor,
    )
    assert row.findings[0]["status"] == "explained"
    assert _results(row)["no_large_deposit"][0] == "passed"
    statements = await db_session.get(ConditionItem, row.item_id)
    assert statements is not None and statements.status is ConditionItemStatus.DONE


async def test_failed_a_check_counts_what_its_filter_shows(db_session: AsyncSession) -> None:
    loan_file, _, _ = await _asked(db_session)
    await check_document(
        db_session, document_id=(await add_statement(db_session, loan_file, july())).id, today=TODAY
    )
    aug = await add_statement(db_session, loan_file, august(pages_present=5))
    await check_document(db_session, document_id=aug.id, today=TODAY)
    summary = await condition_summary(db_session, loan_file_id=loan_file.id)
    # D1 (LP-934 M1): the 5-page August statement fails 6132, 7086 AND 6637's clearance.
    from app.services.conditions import ConditionFilters, list_conditions_filtered

    rows, _ = await list_conditions_filtered(
        db_session, loan_file_id=loan_file.id, filters=ConditionFilters(failed_check=True)
    )
    assert {c.lender_code for c in rows} == {"6132", "7086", "6637"}
    assert summary.failed_check == 3


def test_a_check_without_its_inputs_is_not_run_never_passed() -> None:
    from app.services.condition_evidence import Context, Statement, run_check

    empty = Statement(None, None, None, None, None, None, None, None)
    ctx = Context(None, None, None, [], None, TODAY, None, None, False)
    for check in (
        "all_pages",
        "right_account",
        "right_borrower",
        "inside_lender_dates",
        "amount_matches",
        "covers_required_funds",
        "signed_and_dated",
    ):
        assert run_check(check, empty, ctx)["result"] == "not_run", check


def test_the_threshold_is_half_the_monthly_income() -> None:
    from app.services.condition_evidence import Deposit, Statement, large_deposits

    statement = Statement(
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        deposits=(
            Deposit(date(2026, 8, 20), Decimal("2870.66"), "Transfer"),  # exactly the threshold
            Deposit(date(2026, 8, 21), Decimal("2870.67"), "Transfer"),  # a cent over
            Deposit(date(2026, 8, 22), Decimal("9000.00"), "PAYROLL DIR DEP"),  # pay
        ),
    )
    found = large_deposits(
        statement, monthly_income=Decimal("5741.32"), required=None, verified=None
    )
    assert [f["amount"] for f in found] == ["2870.67"]


@pytest.fixture
def _drop_db_override() -> Any:
    from app.core.database import get_db
    from app.main import app

    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.usefixtures("_drop_db_override")
async def test_the_sheet_reads_s3_07_and_her_answers_go_through_the_routes(
    db_session: AsyncSession,
) -> None:
    from tests.conditions.test_condition_reading import _client_for

    loan_file, conditions, _ = await _asked(db_session)
    await check_document(
        db_session, document_id=(await add_statement(db_session, loan_file, july())).id, today=TODAY
    )
    aug = await add_statement(db_session, loan_file, august(pages_present=5))
    await check_document(db_session, document_id=aug.id, today=TODAY)
    client, headers = await _client_for(db_session, loan_file)
    async with client:
        rows = (
            await client.get(f"/api/v1/loan-files/{loan_file.id}/conditions", headers=headers)
        ).json()
        six = next(r for r in rows if r["lender_code"] == "6132")
        (card,) = [e for e in six["evidence"] if e["document_id"] == str(aug.id)]
        assert card["title"] == "Capital One statement ··9912 · August 2026 · 5 pages"
        assert card["via_upload_link"] is True
        assert card["failed"] is True
        assert card["reask"] == "page 6"
        assert [c["label"] for c in card["checks"]] == [
            "Right account",
            "Right period",
            "Right borrower",
            "Inside the lender's dates",
            "All pages",
        ]
        summary = (
            await client.get(
                f"/api/v1/loan-files/{loan_file.id}/conditions/summary", headers=headers
            )
        ).json()
        assert summary["failed_check"] == 3
        filtered = (
            await client.get(
                f"/api/v1/loan-files/{loan_file.id}/conditions",
                params={"check": "failed"},
                headers=headers,
            )
        ).json()
        assert {r["lender_code"] for r in filtered} == {"6132", "7086", "6637"}

        base = f"/api/v1/conditions/{conditions['6132'].id}/evidence/{card['id']}"
        refused = await client.post(f"{base}/accept", json={"reason": ""}, headers=headers)
        assert refused.status_code == 422
        accepted = await client.post(
            f"{base}/accept", json={"reason": "blank back page"}, headers=headers
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["prep_status"] == "ready"


@pytest.mark.usefixtures("_drop_db_override")
async def test_another_companys_evidence_is_refused(db_session: AsyncSession) -> None:
    from tests.conditions.test_condition_reading import _client_for

    loan_file, conditions, _ = await _asked(db_session)
    aug = await add_statement(db_session, loan_file, august(pages_present=5))
    await check_document(db_session, document_id=aug.id, today=TODAY)
    (row,) = [e for e in await _evidence(db_session, conditions["6132"]) if e.document_id == aug.id]
    other_file, _, _, _ = await _confirmed(db_session)
    client, headers = await _client_for(db_session, other_file)
    async with client:
        # Their session, our condition: the scoped condition is not found.
        response = await client.post(
            f"/api/v1/conditions/{conditions['6132'].id}/evidence/{row.id}/accept",
            json={"reason": "x"},
            headers=headers,
        )
        assert response.status_code == 404


async def _run_needs_task(
    monkeypatch: pytest.MonkeyPatch, db: AsyncSession, loan_file: LoanFile, document_id: Any
) -> list[str]:
    """Run the real per-file needs task on the test session, its AI passes recorded, not run."""
    from contextlib import asynccontextmanager

    from app.tasks import needs as needs_task

    ran: list[str] = []

    @asynccontextmanager
    async def _session() -> Any:
        yield db

    @asynccontextmanager
    async def _lock(_: str) -> Any:
        yield

    async def _pass(name: str) -> None:
        ran.append(name)

    monkeypatch.setattr(needs_task, "task_session", _session)
    monkeypatch.setattr(needs_task, "loan_file_needs_lock", _lock)
    for name in (
        "apply_ai_needs_for_file_id",
        "consolidate_and_flag",
        "flag_covered_needs",
        "compose_needs",
    ):

        async def _record(*_: Any, _name: str = name, **__: Any) -> None:
            await _pass(_name)

        monkeypatch.setattr(needs_task, name, _record)
    await needs_task._run_needs_update(str(loan_file.id), str(document_id))
    return ran


async def test_the_needs_task_checks_the_arrived_document(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    loan_file, conditions, _ = await _asked(db_session)
    aug = await add_statement(db_session, loan_file, august(pages_present=5))
    ran = await _run_needs_task(monkeypatch, db_session, loan_file, aug.id)
    assert any(e.document_id == aug.id for e in await _evidence(db_session, conditions["6132"]))
    assert ran == [
        "apply_ai_needs_for_file_id",
        "consolidate_and_flag",
        "flag_covered_needs",
        "compose_needs",
    ]


async def test_a_failing_evidence_step_never_stops_the_needs_passes(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    loan_file, _, _ = await _asked(db_session)
    aug = await add_statement(db_session, loan_file, august())

    async def _boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("evidence broke")

    monkeypatch.setattr(condition_evidence, "check_document", _boom)
    ran = await _run_needs_task(monkeypatch, db_session, loan_file, aug.id)
    assert "compose_needs" in ran


async def test_each_statement_goes_only_to_the_items_it_answers(db_session: AsyncSession) -> None:
    loan_file, conditions, _ = await _asked(db_session)
    jul = await add_statement(db_session, loan_file, july())
    await check_document(db_session, document_id=jul.id, today=TODAY)
    # 6132 asks for AUGUST: the July statement is not its evidence.
    assert await _evidence(db_session, conditions["6132"]) == []
    # 7086's "any other account" item never takes the ··9912 statement its sibling asks for.
    keys = {
        (await db_session.get(ConditionItem, e.item_id)).key  # type: ignore[union-attr]
        for e in await _evidence(db_session, conditions["7086"])
    }
    assert keys == {"statements"}


async def test_an_open_deposit_holds_the_condition_until_it_is_answered(
    db_session: AsyncSession,
) -> None:
    from app.services.condition_plan import remove_item

    loan_file, conditions, actor = await _asked(db_session)
    other = next(
        i
        for i in (
            await db_session.execute(
                select(ConditionItem).where(ConditionItem.condition_id == conditions["7086"].id)
            )
        ).scalars()
        if i.key == "other_accounts"
    )
    await remove_item(db_session, condition=conditions["7086"], item=other, actor_user_id=actor)
    both = await add_statement(db_session, loan_file, july_and_august())
    await check_document(db_session, document_id=both.id, today=TODAY)
    (row,) = [e for e in await _evidence(db_session, conditions["7086"]) if e.findings]
    # Every CHECK passed — the deposit is a finding, not a check — and it alone keeps 7086 waiting.
    assert all(c["result"] == "passed" for c in row.checks)
    assert "no_large_deposit" not in {c["check"] for c in row.checks}
    assert conditions["7086"].prep_status is ConditionPrepStatus.WAITING
    await condition_evidence.answer_finding(
        db_session,
        condition=conditions["7086"],
        evidence_id=row.id,
        index=0,
        answer="explained",
        reason="Sale of a car; bill of sale and the buyer's check are in the file",
        actor_user_id=actor,
    )
    assert conditions["7086"].prep_status is ConditionPrepStatus.READY


def test_a_statement_outside_the_lenders_dates_fails() -> None:
    from app.services.condition_evidence import Context, Statement, run_check

    statement = Statement(None, None, None, date(2026, 8, 1), date(2026, 8, 31), None, None, None)
    ctx = Context(None, None, None, [], date(2026, 10, 30), date(2026, 11, 2), None, None, False)
    result = run_check("inside_lender_dates", statement, ctx)
    assert result["result"] == "failed"
    assert result["reason"].endswith("outside the lender's dates")


async def test_accepting_a_statement_does_not_answer_its_deposit(db_session: AsyncSession) -> None:
    """ "Accept anyway" is about a failed CHECK; the deposit is a separate question she must answer."""
    from app.services.condition_plan import remove_item

    loan_file, conditions, actor = await _asked(db_session)
    other = next(
        i
        for i in (
            await db_session.execute(
                select(ConditionItem).where(ConditionItem.condition_id == conditions["7086"].id)
            )
        ).scalars()
        if i.key == "other_accounts"
    )
    await remove_item(db_session, condition=conditions["7086"], item=other, actor_user_id=actor)
    both = await add_statement(db_session, loan_file, july_and_august(pages_present=11))
    await check_document(db_session, document_id=both.id, today=TODAY)
    (row,) = [e for e in await _evidence(db_session, conditions["7086"]) if e.findings]
    await condition_evidence.accept_anyway(
        db_session,
        condition=conditions["7086"],
        evidence_id=row.id,
        reason="page 12 is a blank back page",
        actor_user_id=actor,
    )
    assert conditions["7086"].prep_status is ConditionPrepStatus.WAITING


@pytest.mark.usefixtures("_drop_db_override")
async def test_a_deposit_is_a_finding_never_a_failed_check(db_session: AsyncSession) -> None:
    """LP-934 on S3-08: the deposit keeps S3-12's "Failed a check" unchanged. Seen first on the
    harness shot, where the deposit alone made 7086 read "Evidence failed a check"."""
    from tests.conditions.test_condition_reading import _client_for

    loan_file, _, _ = await _asked(db_session)
    both = await add_statement(db_session, loan_file, july_and_august())
    await check_document(db_session, document_id=both.id, today=TODAY)
    summary = await condition_summary(db_session, loan_file_id=loan_file.id)
    assert summary.failed_check == 0
    client, headers = await _client_for(db_session, loan_file)
    async with client:
        rows = (
            await client.get(f"/api/v1/loan-files/{loan_file.id}/conditions", headers=headers)
        ).json()
    seven = next(r for r in rows if r["lender_code"] == "7086")
    card = next(e for e in seven["evidence"] if e["findings"])
    assert card["failed"] is False and card["reask"] is None
    deposit = next(c for c in card["checks"] if c["check"] == "no_large_deposit")
    assert deposit == {
        "check": "no_large_deposit",
        "label": "No unexplained large deposit",
        "result": "failed",
        "reason": "08/21/2026 mobile deposit $4,000.00",
    }


# --------------------------------------------------------------------------------------------- #
# A rejected statement is not evidence (found by the Stage 3B acceptance test)
# --------------------------------------------------------------------------------------------- #


async def _drop_other_accounts(db: AsyncSession, condition: Condition, actor: Any) -> None:
    """She removes 7086's "any other account" item, so only ··9912 answers it (as in S3-10)."""
    from app.services.condition_plan import remove_item

    other = next(
        i
        for i in (
            await db.execute(
                select(ConditionItem).where(ConditionItem.condition_id == condition.id)
            )
        ).scalars()
        if i.key == "other_accounts"
    )
    await remove_item(db, condition=condition, item=other, actor_user_id=actor)


async def test_a_rejected_statement_adds_nothing_to_the_verified_funds(
    db_session: AsyncSession,
) -> None:
    """A ··4471 upload fails "right account" on 7086's statements item. Its balance used to be summed
    into the next statement's "covers required funds": verified $83,828.84 for one account's money."""
    loan_file, conditions, actor = await _asked(db_session)
    await _drop_other_accounts(db_session, conditions["7086"], actor)
    wrong = await add_statement(db_session, loan_file, august(last4="4471"))
    await check_document(db_session, document_id=wrong.id, today=TODAY)
    both = await add_statement(db_session, loan_file, july_and_august())
    await check_document(db_session, document_id=both.id, today=TODAY)
    (row,) = [
        e for e in await _evidence(db_session, conditions["7086"]) if e.document_id == both.id
    ]
    assert _results(row)["covers_required_funds"] == (
        "passed",
        "verified $41,914.42 against $38,210.40 required",
    )


async def test_an_answer_reaches_the_same_deposit_on_every_statement_of_the_account(
    db_session: AsyncSession,
) -> None:
    """The 5-page August and the complete July-August statement both show the 08/21 $4,000.00 deposit.
    Explained once, it is explained on both; the copy on the rejected statement no longer holds 7086."""
    loan_file, conditions, actor = await _asked(db_session)
    await _drop_other_accounts(db_session, conditions["7086"], actor)
    short = await add_statement(db_session, loan_file, august(pages_present=5))
    await check_document(db_session, document_id=short.id, today=TODAY)
    both = await add_statement(db_session, loan_file, july_and_august())
    await check_document(db_session, document_id=both.id, today=TODAY)
    rows = {e.document_id: e for e in await _evidence(db_session, conditions["7086"])}
    assert [f["status"] for f in rows[short.id].findings] == ["open"]  # the positive control
    await condition_evidence.answer_finding(
        db_session,
        condition=conditions["7086"],
        evidence_id=rows[both.id].id,
        index=0,
        answer="explained",
        reason="Gift from a relative",
        actor_user_id=actor,
    )
    assert [(f["status"], f["reason"]) for f in rows[short.id].findings] == [
        ("explained", "Gift from a relative")
    ]
    assert conditions["7086"].prep_status is ConditionPrepStatus.READY
    answered = (
        await db_session.execute(
            select(ConditionEvent.detail).where(
                ConditionEvent.condition_id == conditions["7086"].id,
                ConditionEvent.kind == ConditionEventKind.CONDITION_FINDING_ANSWERED,
            )
        )
    ).scalar_one()
    assert answered["also_answered_on"] == [str(short.id)]


async def test_a_deposit_on_a_rejected_statement_does_not_hold_the_condition(
    db_session: AsyncSession,
) -> None:
    """Another account's statement (rejected, "right account") shows its own large deposit. It is not
    submitted, so it does not hold 7086 once the real statement's deposit is explained."""
    loan_file, conditions, actor = await _asked(db_session)
    await _drop_other_accounts(db_session, conditions["7086"], actor)
    wrong = await add_statement(db_session, loan_file, august(last4="4471"))
    await check_document(db_session, document_id=wrong.id, today=TODAY)
    both = await add_statement(db_session, loan_file, july_and_august())
    await check_document(db_session, document_id=both.id, today=TODAY)
    rows = {e.document_id: e for e in await _evidence(db_session, conditions["7086"])}
    # The positive control: the rejected statement's own deposit is open and needed.
    assert [(f["status"], f["needed"]) for f in rows[wrong.id].findings] == [("open", True)]
    await condition_evidence.answer_finding(
        db_session,
        condition=conditions["7086"],
        evidence_id=rows[both.id].id,
        index=0,
        answer="explained",
        reason="Gift from a relative",
        actor_user_id=actor,
    )
    # Another account's deposit is not this one: it keeps its own status.
    assert [f["status"] for f in rows[wrong.id].findings] == ["open"]
    assert conditions["7086"].prep_status is ConditionPrepStatus.READY


# --------------------------------------------------------------------------------------------- #
# AS-04's receipt is checked against the receipt's own amount (LP-938 review)
# --------------------------------------------------------------------------------------------- #


async def _receipt_item(db: AsyncSession, condition: Condition) -> ConditionItem:
    return (
        await db.execute(
            select(ConditionItem).where(
                ConditionItem.condition_id == condition.id, ConditionItem.key == "receipt"
            )
        )
    ).scalar_one()


async def test_an_earnest_money_receipt_is_checked_against_its_own_amount(
    db_session: AsyncSession,
) -> None:
    """Title's receipt for the $2,850.00 deposit. Before LP-938's follow-up its amount was extracted and
    never read: "Amount matches" was not run ("no transactions could be read"), so every real receipt
    stopped at Received. With the statements, 6637 is now Ready by evidence alone."""
    from tests.conditions.statement_fixture import add_receipt

    loan_file, conditions, _ = await _asked(db_session)
    receipt = await add_receipt(db_session, loan_file)
    await check_document(db_session, document_id=receipt.id, today=TODAY)
    (row,) = [
        e for e in await _evidence(db_session, conditions["6637"]) if e.document_id == receipt.id
    ]
    assert _results(row) == {"amount_matches": ("passed", "$2,850.00 on 08/03/2026")}
    assert (await _receipt_item(db_session, conditions["6637"])).status is ConditionItemStatus.DONE

    both = await add_statement(db_session, loan_file, july_and_august())
    await check_document(db_session, document_id=both.id, today=TODAY)
    assert conditions["6637"].prep_status is ConditionPrepStatus.READY


async def test_a_receipt_for_another_amount_fails_and_says_receipt(
    db_session: AsyncSession,
) -> None:
    from tests.conditions.statement_fixture import add_receipt

    loan_file, conditions, _ = await _asked(db_session)
    receipt = await add_receipt(db_session, loan_file, amount="2500.00")
    await check_document(db_session, document_id=receipt.id, today=TODAY)
    (row,) = [
        e for e in await _evidence(db_session, conditions["6637"]) if e.document_id == receipt.id
    ]
    assert _results(row) == {"amount_matches": ("failed", "no $2,850.00 on this receipt")}
    assert (
        await _receipt_item(db_session, conditions["6637"])
    ).status is not ConditionItemStatus.DONE
