"""Stage 3B acceptance (build prompt §6): round 1 of the fictional UWM file, from the borrower's
statements arriving to the package she uploads.

One file, in the order the screens happen, with fictional statement PDFs generated here (real pages,
so the package's page counts and merges are measured, not assumed):

1. S3-07 — the August statement with 5 of 6 pages cannot reach Ready;
2. a statement for the wrong account is rejected with the reason;
3. S3-08 — the $4,000.00 deposit on 08/21 is flagged against the $2,870.66 threshold;
4. S3-09 — accepting the evidence proposes the figures and changes nothing until they are applied;
   applying goes through the stated-financials edits;
5. the DTI 44% to 46% change is flagged "re-run DU", and 46% to 48% is not;
6. S3-10 — the package has one named PDF and one note per ready condition;
7. Mark submitted moves exactly those to Sent to lender, and the lender's track never moves.

The expected values are written from the build prompt, the plan and the screens by hand, not read back
from the code's output.
"""

from __future__ import annotations

import io
import json
import zipfile
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pymupdf
import pytest
from app.models.activity_log import ActivityLog
from app.models.condition import Condition, ConditionPrepStatus
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_item import ConditionItem
from app.models.condition_vocabulary import ConditionItemStatus
from app.models.document import Document
from app.models.stated_financials import StatedAsset
from app.schemas.condition import PrepStatusRequest
from app.services import condition_evidence, condition_package, figures_check
from app.services.condition_evidence import check_document
from app.services.condition_plan import remove_item
from app.services.condition_status import move_prep_status
from app.services.dti import build_dti_calculation
from app.services.figures_check import du_rerun_reasons
from app.storage import get_storage_backend
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.statement_fixture import (
    add_declarations,
    add_statement,
    august,
    july,
    july_and_august,
)
from tests.conditions.test_condition_evidence import TODAY, _asked, _evidence, _results
from tests.conditions.test_figures_check import _like_the_letter

DASH = "\u2013"


def _pdf(title: str, pages: int) -> bytes:
    """A fictional statement: `pages` real pages, each saying what it is."""
    doc = pymupdf.open()
    for number in range(pages):
        doc.new_page().insert_text((72, 72), f"{title} — page {number + 1}")
    content = bytes(doc.tobytes())
    doc.close()
    return content


async def _store(document: Document, company_id: Any, pages: int) -> None:
    document.storage_path = await get_storage_backend().save(
        company_id=company_id,
        file_id=document.loan_file_id,
        document_id=document.id,
        filename=document.original_filename,
        content=_pdf(document.original_filename, pages),
    )


async def _item(db: AsyncSession, condition: Condition, key: str) -> ConditionItem:
    return (
        await db.execute(
            select(ConditionItem).where(
                ConditionItem.condition_id == condition.id,
                ConditionItem.key == key,
                ConditionItem.deleted_at.is_(None),
            )
        )
    ).scalar_one()


async def _prep_moves(db: AsyncSession, loan_file_id: Any) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(ConditionEvent)
            .where(
                ConditionEvent.loan_file_id == loan_file_id,
                ConditionEvent.kind == ConditionEventKind.CONDITION_PREP_MOVED,
            )
        )
        or 0
    )


def test_the_du_tolerance_examples() -> None:
    """Step 5: Fannie Mae B3-2-10's own examples (STOP AND ASK 2 records the crossing reading)."""
    flagged, _ = du_rerun_reasons(old_dti=Decimal("44"), new_dti=Decimal("46"))
    assert flagged == ["the DTI rises above 45% (44% → 46%)"]
    assert du_rerun_reasons(old_dti=Decimal("46"), new_dti=Decimal("48")) == ([], [])


async def test_stage_3b_from_statements_to_the_package(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = db_session
    loan_file, conditions, actor = await _asked(db)
    await _like_the_letter(db, loan_file, actor)
    # 7086, 6132 and 6637 wait on the borrower; nothing else has moved yet.
    assert {
        code for code, c in conditions.items() if c.prep_status is ConditionPrepStatus.WAITING
    } >= {"7086", "6132", "6637"}

    # She drops 7086's "any other account" item at the start: the one Capital One account covers the
    # shortfall. Kept, it would rightly take ANOTHER account's statement
    # and count its balance, which is not the story the screens tell.
    await remove_item(
        db,
        condition=conditions["7086"],
        item=await _item(db, conditions["7086"], "other_accounts"),
        actor_user_id=actor,
    )

    # ---- 1. S3-07: July has been in the file since 08/20; August arrives with pages 1-5 of 6 ----------------------
    july_doc = await add_statement(db, loan_file, july(), name="july.pdf", via_link=False)
    await _store(july_doc, loan_file.company_id, 6)
    # July is a processor upload from 08/20, before the plan: in the file, never re-checked (S3-07).
    short = await add_statement(db, loan_file, august(pages_present=5), name="august.pdf")
    await _store(short, loan_file.company_id, 5)
    await check_document(db, document_id=short.id, today=TODAY)
    (short_row,) = [e for e in await _evidence(db, conditions["6132"]) if e.document_id == short.id]
    assert _results(short_row)["all_pages"] == (
        "failed",
        f"pages 1{DASH}5 of 6 — page 6 is missing",
    )
    assert conditions["6132"].prep_status is ConditionPrepStatus.WAITING
    assert conditions["7086"].prep_status is ConditionPrepStatus.WAITING

    # ---- 2. a statement for another account is rejected, and says why ---------------------------
    wrong = await add_statement(db, loan_file, august(last4="4471"), name="other-account.pdf")
    await _store(wrong, loan_file.company_id, 6)
    await check_document(db, document_id=wrong.id, today=TODAY)
    (wrong_row,) = [e for e in await _evidence(db, conditions["6132"]) if e.document_id == wrong.id]
    assert _results(wrong_row)["right_account"] == (
        "failed",
        "Capital One ending 4471 — the condition asks for ending 9912",
    )
    assert (await _item(db, conditions["6132"], "statement")).status is not ConditionItemStatus.DONE
    assert conditions["6132"].prep_status is ConditionPrepStatus.WAITING
    # And it answers nothing on 7086, whose statements item asks for ··9912.
    assert not [
        e
        for e in await _evidence(db, conditions["7086"])
        if e.document_id == wrong.id and e.status.value == "accepted"
    ]

    # ---- 3. S3-08: July and August together, 12 pages, with the $4,000.00 mobile deposit --------
    both = await add_statement(db, loan_file, july_and_august(), name="statements.pdf")
    await _store(both, loan_file.company_id, 12)
    await check_document(db, document_id=both.id, today=TODAY)
    (deposit_row,) = [
        e
        for e in await _evidence(db, conditions["7086"])
        if e.document_id == both.id and e.findings
    ]
    assert _results(deposit_row)["covers_required_funds"] == (
        "passed",
        "verified $41,914.42 against $38,210.40 required",
    )
    assert _results(deposit_row)["no_large_deposit"] == (
        "failed",
        "08/21/2026 mobile deposit $4,000.00",
    )
    (finding,) = deposit_row.findings
    assert (finding["date"], finding["amount"], finding["threshold"], finding["status"]) == (
        "2026-08-21",
        "4000.00",
        "2870.66",
        "open",
    )
    # The complete August reaches Ready for 6132; 7086 is held by the open deposit.
    assert conditions["6132"].prep_status is ConditionPrepStatus.READY
    assert conditions["7086"].prep_status is ConditionPrepStatus.WAITING

    # ---- 4. S3-09: nothing proposed until the evidence is accepted; nothing changed until applied -
    assert (await figures_check.figures_check(db, loan_file=loan_file)).changes == []
    # She explains the deposit (S3-08's "Explained").
    await condition_evidence.answer_finding(
        db,
        condition=conditions["7086"],
        evidence_id=deposit_row.id,
        index=0,
        answer="explained",
        reason="Gift from a relative; gift letter and transfer in the file",
        actor_user_id=actor,
    )
    assert conditions["7086"].prep_status is ConditionPrepStatus.READY
    await add_declarations(db, loan_file)

    check = await figures_check.figures_check(db, loan_file=loan_file)
    assert [(c.label, c.in_file, c.from_evidence) for c in check.changes] == [
        ("Verified assets", Decimal("11062.18"), Decimal("41914.42")),
        ("Monthly homeowners insurance", Decimal("120.00"), Decimal("155.00")),
        ("Housing ratio", Decimal("32.51"), Decimal("33.12")),
        ("Debt-to-income (DTI)", Decimal("40.36"), Decimal("40.97")),
    ]
    assert check.du_rerun is False
    asset = (
        await db.execute(select(StatedAsset).where(StatedAsset.loan_file_id == loan_file.id))
    ).scalar_one()
    before = await build_dti_calculation(db, loan_file=loan_file)
    assert asset.value == Decimal("11062.18")
    assert (before.front_end_dti, before.back_end_dti) == (Decimal("32.51"), Decimal("40.36"))

    await figures_check.apply(
        db,
        loan_file=loan_file,
        expected=[
            {
                "key": c.key,
                "in_file": None if c.in_file is None else str(c.in_file),
                "from_evidence": str(c.from_evidence),
            }
            for c in check.changes
        ],
        actor_user_id=actor,
    )
    after = await build_dti_calculation(db, loan_file=loan_file)
    assert asset.value == Decimal("41914.42")
    assert (after.front_end_dti, after.back_end_dti) == (Decimal("33.12"), Decimal("40.97"))
    summaries = set(
        (
            await db.execute(
                select(ActivityLog.summary).where(ActivityLog.loan_file_id == loan_file.id)
            )
        ).scalars()
    )
    # Through the stated-financials edit and the DTI calculator's override, each with its own line.
    assert {"Edited a stated asset", "Applied 2 changes from accepted evidence (7086, 6178)"} <= (
        summaries
    )

    # ---- 6. S3-10: the package --------------------------------------------------------------------
    # 6178's push-back needs no document; she moves it to Ready herself (LP-934 M2).
    await move_prep_status(
        db,
        condition=conditions["6178"],
        payload=PrepStatusRequest(to=ConditionPrepStatus.READY),
        actor_user_id=actor,
    )
    # The credit invoice 0006 found in the file, given its one fictional page.
    invoice = (
        await db.execute(
            select(Document).where(
                Document.loan_file_id == loan_file.id, Document.original_filename == "invoice.pdf"
            )
        )
    ).scalar_one()
    await _store(invoice, loan_file.company_id, 1)

    sent: list[str] = []

    async def notes_model(**kwargs: Any) -> Any:
        sent.append(kwargs["messages"][0]["content"])
        return SimpleNamespace(
            text=json.dumps(
                {
                    "notes": {
                        "6132": "August statement ··9912, consecutive to July, all 12 pages.",
                        # A figure no document carries: code keeps its own note.
                        "7086": "Statements show $45,000.00 on hand.",
                    }
                }
            )
        )

    from app.ai import client

    monkeypatch.setattr(client, "complete", notes_model)
    ready = {code for code, c in conditions.items() if c.prep_status is ConditionPrepStatus.READY}
    assert ready == {"7086", "6132", "6178", "0006"}

    package = await condition_package.build(db, loan_file=loan_file, actor_user_id=actor)
    rows = {r["code"]: r for r in package.rows}
    # One row per ready condition, in sheet order.
    assert [r["code"] for r in package.rows] == ["7086", "6132", "6178", "0006"]
    # One named PDF per condition that has documents; the push-back has none, and says why.
    assert {code: r["file_name"] for code, r in rows.items()} == {
        "7086": "7086 - Assets.pdf",
        "6132": "6132 - Assets.pdf",
        "6178": None,
        "0006": "0006 - Invoice.pdf",
    }
    # Only the passing statement: the 5-page and the wrong-account uploads are not in it.
    assert rows["7086"]["document_ids"] == [str(both.id)]
    assert (rows["7086"]["pages"], rows["0006"]["pages"]) == (12, 1)
    # One note each: the AI's where its numbers are the row's own, code's otherwise.
    assert all(r["note"].strip() for r in package.rows)
    assert (rows["6132"]["note_source"], rows["7086"]["note_source"]) == ("ai", "code")
    assert "45,000" not in rows["7086"]["note"]
    assert rows["7086"]["note"] == (
        "Capital One ··9912 Jul and Aug statements, all 12 pages; $41,914.42 verified against "
        "$38,210.40 required; 08/21 deposit sourced."
    )
    # The model saw each row's facts, never the file.
    (payload,) = sent
    assert {r["code"] for r in json.loads(payload)} == {"7086", "6132", "6178", "0006"}
    assert "ssn" not in payload.lower()

    content, missing = await condition_package.download(db, package=package)
    archive = zipfile.ZipFile(io.BytesIO(content))
    assert sorted(archive.namelist()) == [
        "0006 - Invoice.pdf",
        "6132 - Assets.pdf",
        "7086 - Assets.pdf",
        "notes.txt",
    ]
    assert missing == []
    with pymupdf.open(stream=archive.read("7086 - Assets.pdf"), filetype="pdf") as merged:
        assert merged.page_count == 12
    notes = archive.read("notes.txt").decode().splitlines()
    assert [line.split(" — ", 1)[0] for line in notes] == ["7086", "6132", "6178", "0006"]

    # ---- 7. Mark submitted -------------------------------------------------------------------------
    untouched = {code: c.prep_status for code, c in conditions.items() if code not in rows}
    moves_before = await _prep_moves(db, loan_file.id)
    moved = await condition_package.submit(
        db, loan_file=loan_file, package=package, actor_user_id=actor
    )
    assert moved == ["7086", "6132", "6178", "0006"]
    for code in moved:
        assert conditions[code].prep_status is ConditionPrepStatus.WITH_UNDERWRITER, code
        assert conditions[code].sent_at is not None, code
    assert await _prep_moves(db, loan_file.id) == moves_before + 4
    # Exactly those: every other condition is where it was.
    assert {code: conditions[code].prep_status for code in untouched} == untouched
    # The lender's track never moved, from the first statement to the submit.
    assert {c.lender_status.value for c in conditions.values()} == {"open"}
