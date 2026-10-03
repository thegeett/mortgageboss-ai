"""LP-953 — linking (items 6 and 7 of the 2026-09-30 staging trial).

The file: the shipped UWM round-1 sheet on a file whose lender is UWM, read and planned, so 0006 is IV-01
(credit report invoice), 1582 IV-02 (processing invoice) and 0007 IV-03 (inspection invoice), each wanting
`service_invoice`. The documents are fictional rows; only their type, name and status matter here.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from app.conditions.library import load_library
from app.models import Company
from app.models.condition import Condition, ConditionPrepStatus
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_evidence import (
    ConditionEvidence,
    ConditionItemUnlink,
    EvidenceOrigin,
)
from app.models.condition_item import ConditionItem
from app.models.condition_vocabulary import ConditionItemStatus, PlanOption
from app.models.document import Document, DocumentStatus, UploadSource
from app.models.loan_file import LoanFile
from app.services import condition_reading
from app.services.condition_evidence import accept_anyway, check_document
from app.services.condition_lender import set_file_lender
from app.services.condition_links import LinkRefused, link_document, unlink_document
from app.services.condition_matching import document_answers, match_words_for
from app.services.condition_plan import PlanRefused, build_plan, set_next_step, update_item
from app.services.condition_reading import read_round
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.reading_fixture import fake_complete
from tests.conditions.test_lp949_lender_on_the_file import _by_code, _file_without_lender
from tests.models.conftest_helpers import make_loan_file

INVOICE_TYPES = {"IV-01": "credit", "IV-02": "processing", "IV-03": "inspection"}


@pytest.fixture(autouse=True)
def _model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(condition_reading, "complete", fake_complete())


@pytest.fixture(autouse=True)
def _drop_db_override() -> Any:
    from app.core.database import get_db
    from app.main import app

    yield
    app.dependency_overrides.pop(get_db, None)


async def _planned(db: AsyncSession) -> tuple[LoanFile, dict[str, Condition]]:
    loan_file, round_ = await _file_without_lender(db)
    await set_file_lender(
        db, loan_file=loan_file, lender_key="uwm", lender_id=None, actor_user_id=None
    )
    await read_round(db, round_id=round_.id)
    await build_plan(db, round_id=round_.id)
    return loan_file, await _by_code(db, loan_file)


async def _item(db: AsyncSession, condition: Condition) -> ConditionItem:
    items = list(
        await db.scalars(
            select(ConditionItem)
            .where(ConditionItem.condition_id == condition.id, ConditionItem.deleted_at.is_(None))
            .order_by(ConditionItem.sequence)
        )
    )
    assert items, condition.lender_code
    return items[0]


async def _doc(
    db: AsyncSession,
    loan_file: LoanFile,
    *,
    document_type: str | None,
    name: str,
    status: DocumentStatus = DocumentStatus.COMPLETED,
) -> Document:
    doc = Document(
        loan_file_id=loan_file.id,
        original_filename=f"{uuid4().hex[:6]}.pdf",
        mime_type="application/pdf",
        file_size_bytes=10,
        storage_path=f"{loan_file.id}/{uuid4().hex}.pdf",
        document_type=document_type,
        document_name=name,
        status=status,
        upload_source=UploadSource.USER_UPLOAD,
    )
    db.add(doc)
    await db.flush()
    return doc


def _now(row: Any, field: str) -> Any:
    """Read a status afresh: mypy narrows `x.status` across the awaits that change it."""
    return getattr(row, field)


async def _rows(db: AsyncSession, item: ConditionItem) -> list[ConditionEvidence]:
    return list(
        await db.scalars(select(ConditionEvidence).where(ConditionEvidence.item_id == item.id))
    )


async def _events(db: AsyncSession, condition: Condition, kind: ConditionEventKind) -> list[Any]:
    return list(
        await db.scalars(
            select(ConditionEvent).where(
                ConditionEvent.condition_id == condition.id, ConditionEvent.kind == kind
            )
        )
    )


# --------------------------------------------------------------------------------------------- #
# Item 6: one matching rule, every invoice pair in both directions
# --------------------------------------------------------------------------------------------- #


def test_no_library_item_key_contains_a_dot() -> None:
    """The premise `library_item_for` (and LP-948's `item_words`) splits a part's key on."""
    keys = [item.key for t in load_library().types.values() for item in t.items]
    assert keys and not [key for key in keys if "." in key]


@pytest.mark.parametrize("item_type", sorted(INVOICE_TYPES))
@pytest.mark.parametrize("document_word", sorted(INVOICE_TYPES.values()))
def test_each_invoice_item_takes_only_its_own_invoice(item_type: str, document_word: str) -> None:
    library_type = load_library().get(item_type)
    assert library_type is not None
    item = library_type.items[0]
    document = Document(
        document_type="service_invoice", document_name=f"{document_word.title()} invoice 07/15"
    )
    answers = document_answers(
        wanted=item.documents, match_words=match_words_for(item_type, item.key), document=document
    )
    assert answers is (INVOICE_TYPES[item_type] == document_word), (item_type, document_word)


async def test_an_arriving_processing_invoice_answers_1582_and_not_the_credit_invoice(
    db_session: AsyncSession,
) -> None:
    loan_file, conditions = await _planned(db_session)
    credit, processing = (
        await _item(db_session, conditions["0006"]),
        await _item(db_session, conditions["1582"]),
    )
    invoice = await _doc(
        db_session, loan_file, document_type="service_invoice", name="Processing invoice"
    )
    await check_document(db_session, document_id=invoice.id)
    assert [r.document_id for r in await _rows(db_session, processing)] == [invoice.id]
    assert await _rows(db_session, credit) == []


async def test_an_arriving_credit_invoice_answers_0006(db_session: AsyncSession) -> None:
    """The positive control: the right invoice still links."""
    loan_file, conditions = await _planned(db_session)
    credit = await _item(db_session, conditions["0006"])
    invoice = await _doc(
        db_session, loan_file, document_type="service_invoice", name="Credit report invoice"
    )
    await check_document(db_session, document_id=invoice.id)
    assert [r.document_id for r in await _rows(db_session, credit)] == [invoice.id]


# --------------------------------------------------------------------------------------------- #
# Item 7: Link, Change, Unlink, Upload here, "Already in the file"
# --------------------------------------------------------------------------------------------- #


async def test_a_link_to_a_document_still_being_read_waits_then_is_checked(
    db_session: AsyncSession,
) -> None:
    loan_file, conditions = await _planned(db_session)
    item = await _item(db_session, conditions["0006"])
    doc = await _doc(
        db_session, loan_file, document_type=None, name="", status=DocumentStatus.PENDING
    )
    row = await link_document(
        db_session,
        condition=conditions["0006"],
        item=item,
        document_id=doc.id,
        page=2,
        actor_user_id=None,
    )
    assert row.origin is EvidenceOrigin.MANUAL and row.page == 2
    assert [c["check"] for c in row.checks] == ["document_read"]
    assert _now(item, "status") is ConditionItemStatus.RECEIVED
    assert item.document_id == doc.id and item.document_page == 2

    doc.document_type, doc.document_name = "service_invoice", "Credit report invoice"
    doc.status = DocumentStatus.COMPLETED
    await check_document(db_session, document_id=doc.id)
    await db_session.refresh(row)
    assert "document_read" not in [c["check"] for c in row.checks]
    assert _now(item, "status") is ConditionItemStatus.DONE


async def test_a_mismatched_link_fails_a_check_and_does_not_reach_ready(
    db_session: AsyncSession,
) -> None:
    loan_file, conditions = await _planned(db_session)
    condition = conditions["0006"]
    item = await _item(db_session, condition)
    report = await _doc(db_session, loan_file, document_type="credit_report", name="Credit report")
    row = await link_document(
        db_session,
        condition=condition,
        item=item,
        document_id=report.id,
        page=None,
        actor_user_id=None,
    )
    [mismatch] = [c for c in row.checks if c["check"] == "right_document_type"]
    assert mismatch["result"] == "failed"
    assert "credit report" in mismatch["reason"] and "invoice" in mismatch["reason"]
    assert _now(item, "status") is not ConditionItemStatus.DONE
    assert _now(condition, "prep_status") is not ConditionPrepStatus.READY

    # HER DECISION, recorded: Accept anyway makes the item done.
    from tests.conditions.test_condition_plan import _actor

    await accept_anyway(
        db_session,
        condition=condition,
        evidence_id=row.id,
        reason="The lender takes the fee page of the report",
        actor_user_id=await _actor(db_session, loan_file),
    )
    assert _now(item, "status") is ConditionItemStatus.DONE


async def test_unlink_deletes_the_row_records_her_choice_and_arrival_does_not_put_it_back(
    db_session: AsyncSession,
) -> None:
    loan_file, conditions = await _planned(db_session)
    condition = conditions["0006"]
    item = await _item(db_session, condition)
    invoice = await _doc(
        db_session, loan_file, document_type="service_invoice", name="Credit report invoice"
    )
    await check_document(db_session, document_id=invoice.id)
    # IV-01's item has no checks, so a document arriving by matching leaves it RECEIVED (LP-923 as
    # built: nothing looked at it). Only her link, or her "done", finishes such an item.
    assert _now(item, "status") is ConditionItemStatus.RECEIVED

    await unlink_document(
        db_session, condition=condition, item=item, document_id=invoice.id, actor_user_id=None
    )
    assert await _rows(db_session, item) == []
    assert _now(item, "status") is ConditionItemStatus.OPEN
    facts = list(
        await db_session.scalars(
            select(ConditionItemUnlink).where(ConditionItemUnlink.item_id == item.id)
        )
    )
    assert [f.document_id for f in facts] == [invoice.id]
    assert (
        len(await _events(db_session, condition, ConditionEventKind.CONDITION_EVIDENCE_UNLINKED))
        == 1
    )

    await check_document(db_session, document_id=invoice.id)  # the document is processed again
    assert await _rows(db_session, item) == []

    # Linking it again by hand clears her "no", so it counts again.
    await link_document(
        db_session,
        condition=condition,
        item=item,
        document_id=invoice.id,
        page=None,
        actor_user_id=None,
    )
    assert len(await _rows(db_session, item)) == 1
    assert (
        await db_session.scalar(
            select(ConditionItemUnlink.id).where(ConditionItemUnlink.item_id == item.id)
        )
    ) is None


async def test_unlinking_the_document_that_made_a_condition_ready_puts_it_back_to_to_do(
    db_session: AsyncSession,
) -> None:
    loan_file, conditions = await _planned(db_session)
    condition = conditions["0006"]
    item = await _item(db_session, condition)
    invoice = await _doc(
        db_session, loan_file, document_type="service_invoice", name="Credit report invoice"
    )
    await link_document(
        db_session,
        condition=condition,
        item=item,
        document_id=invoice.id,
        page=None,
        actor_user_id=None,
    )
    assert _now(condition, "prep_status") is ConditionPrepStatus.READY
    await unlink_document(
        db_session, condition=condition, item=item, document_id=invoice.id, actor_user_id=None
    )
    assert _now(condition, "prep_status") is ConditionPrepStatus.TO_DO
    moves = await _events(db_session, condition, ConditionEventKind.CONDITION_PREP_MOVED)
    assert moves[-1].detail["by"] == "unlink"


async def test_change_unlinks_the_old_and_links_the_new(db_session: AsyncSession) -> None:
    loan_file, conditions = await _planned(db_session)
    condition = conditions["0006"]
    item = await _item(db_session, condition)
    wrong = await _doc(db_session, loan_file, document_type="credit_report", name="Credit report")
    right = await _doc(
        db_session, loan_file, document_type="service_invoice", name="Credit report invoice"
    )
    await link_document(
        db_session,
        condition=condition,
        item=item,
        document_id=wrong.id,
        page=None,
        actor_user_id=None,
    )
    await link_document(
        db_session,
        condition=condition,
        item=item,
        document_id=right.id,
        page=None,
        actor_user_id=None,
        replace_document_id=wrong.id,
    )
    assert [r.document_id for r in await _rows(db_session, item)] == [right.id]
    assert _now(item, "status") is ConditionItemStatus.DONE
    linked = await _events(db_session, condition, ConditionEventKind.CONDITION_EVIDENCE_LINKED)
    assert [e.detail["replaced"] for e in linked] == [False, True]


async def test_another_files_document_is_not_found(db_session: AsyncSession) -> None:
    _, conditions = await _planned(db_session)
    company = Company(name="Other", slug=f"other-{uuid4().hex[:6]}")
    db_session.add(company)
    await db_session.flush()
    other_file = await make_loan_file(db_session, company=company)
    stranger = await _doc(
        db_session, other_file, document_type="service_invoice", name="Credit report invoice"
    )
    item = await _item(db_session, conditions["0006"])
    for call in (
        link_document(
            db_session,
            condition=conditions["0006"],
            item=item,
            document_id=stranger.id,
            page=None,
            actor_user_id=None,
        ),
        unlink_document(
            db_session,
            condition=conditions["0006"],
            item=item,
            document_id=stranger.id,
            actor_user_id=None,
        ),
    ):
        with pytest.raises(LinkRefused) as refused:
            await call
        assert refused.value.not_found


async def test_already_in_the_file_by_hand_needs_a_linked_document(
    db_session: AsyncSession,
) -> None:
    loan_file, conditions = await _planned(db_session)
    condition = conditions["0006"]
    item = await _item(db_session, condition)
    from tests.conditions.test_condition_plan import _actor

    actor = await _actor(db_session, loan_file)
    with pytest.raises(PlanRefused):
        await update_item(
            db_session,
            condition=condition,
            item=item,
            option=PlanOption.ALREADY_IN_FILE,
            name=None,
            performers=None,
            due_date=None,
            actor_user_id=actor,
        )
    with pytest.raises(PlanRefused):
        await set_next_step(
            db_session,
            condition=condition,
            next_step=PlanOption.ALREADY_IN_FILE,
            actor_user_id=actor,
        )
    invoice = await _doc(
        db_session, loan_file, document_type="service_invoice", name="Credit report invoice"
    )
    await link_document(
        db_session,
        condition=condition,
        item=item,
        document_id=invoice.id,
        page=1,
        actor_user_id=actor,
    )
    await update_item(
        db_session,
        condition=condition,
        item=item,
        option=PlanOption.ALREADY_IN_FILE,
        name=None,
        performers=None,
        due_date=None,
        actor_user_id=actor,
    )
    assert item.option is PlanOption.ALREADY_IN_FILE


async def test_unlinking_an_already_in_file_pointer_makes_it_her_task_again(
    db_session: AsyncSession,
) -> None:
    """A plan-time match sets only the pointer; unlinking it clears that and its step."""
    loan_file, conditions = await _planned(db_session)
    condition = conditions["0006"]
    item = await _item(db_session, condition)
    invoice = await _doc(
        db_session, loan_file, document_type="service_invoice", name="Credit report invoice"
    )
    item.option, item.document_id, item.status = (
        PlanOption.ALREADY_IN_FILE,
        invoice.id,
        ConditionItemStatus.DONE,
    )
    await db_session.flush()
    await unlink_document(
        db_session, condition=condition, item=item, document_id=invoice.id, actor_user_id=None
    )
    assert item.document_id is None
    assert item.option is PlanOption.I_WILL_DO_IT
    assert _now(item, "status") is ConditionItemStatus.OPEN


# --------------------------------------------------------------------------------------------- #
# The routes and the screen's data
# --------------------------------------------------------------------------------------------- #


async def test_the_link_routes_and_who_linked_it(db_session: AsyncSession) -> None:
    from tests.conditions.test_lender_condition_settings import _clients

    loan_file, conditions = await _planned(db_session)
    condition = conditions["0006"]
    item = await _item(db_session, condition)
    invoice = await _doc(
        db_session, loan_file, document_type="service_invoice", name="Credit report invoice"
    )
    client, _, processor = await _clients(db_session, loan_file)
    base = f"/api/v1/conditions/{condition.id}/items/{item.id}/links"
    async with client:
        linked = await client.post(
            base, json={"document_id": str(invoice.id), "page": 3}, headers=processor
        )
        assert linked.status_code == 200, linked.text
        again = await client.post(base, json={"document_id": str(invoice.id)}, headers=processor)
        assert again.status_code == 409
        rows = [e for e in linked.json()["evidence"] if e["document_id"] == str(invoice.id)]
        assert rows and rows[0]["origin"] == "manual" and rows[0]["page"] == 3
        assert rows[0]["linked_by_name"]

        unlinked = await client.delete(f"{base}/{invoice.id}", headers=processor)
        assert unlinked.status_code == 200
        missing = await client.delete(f"{base}/{invoice.id}", headers=processor)
        assert missing.status_code == 409


async def test_another_files_document_is_404_through_the_route(db_session: AsyncSession) -> None:
    from tests.conditions.test_lender_condition_settings import _clients

    loan_file, conditions = await _planned(db_session)
    company = Company(name="Other", slug=f"other-{uuid4().hex[:6]}")
    db_session.add(company)
    await db_session.flush()
    other_file = await make_loan_file(db_session, company=company)
    stranger = await _doc(
        db_session, other_file, document_type="service_invoice", name="Credit report invoice"
    )
    condition = conditions["0006"]
    item = await _item(db_session, condition)
    client, _, processor = await _clients(db_session, loan_file)
    async with client:
        base = f"/api/v1/conditions/{condition.id}/items/{item.id}/links"
        assert (
            await client.post(base, json={"document_id": str(stranger.id)}, headers=processor)
        ).status_code == 404
        assert (await client.delete(f"{base}/{stranger.id}", headers=processor)).status_code == 404


async def test_upload_here_links_the_upload_and_refuses_another_files_item(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import documents as documents_api
    from tests.conditions.test_lender_condition_settings import _clients

    monkeypatch.setattr(documents_api, "_enqueue_processing", lambda _id: None)
    loan_file, conditions = await _planned(db_session)
    item = await _item(db_session, conditions["0006"])
    company = Company(name="Other", slug=f"other-{uuid4().hex[:6]}")
    db_session.add(company)
    await db_session.flush()
    other_file = await make_loan_file(db_session, company=company)
    client, _, processor = await _clients(db_session, loan_file)
    pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    async with client:
        uploaded = await client.post(
            f"/api/v1/loan-files/{loan_file.id}/documents",
            files={"files": ("invoice.pdf", pdf, "application/pdf")},
            data={"condition_item_id": str(item.id)},
            headers=processor,
        )
        assert uploaded.status_code == 201, uploaded.text
        refused = await client.post(
            f"/api/v1/loan-files/{other_file.id}/documents",
            files={"files": ("invoice.pdf", pdf, "application/pdf")},
            data={"condition_item_id": str(item.id)},
            headers=processor,
        )
        assert refused.status_code in (403, 404)
    [row] = await _rows(db_session, item)
    assert row.origin is EvidenceOrigin.MANUAL
    assert [c["check"] for c in row.checks] == ["document_read"]
