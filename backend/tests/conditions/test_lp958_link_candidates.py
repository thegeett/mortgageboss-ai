"""LP-958 — the Link dialog's documents, and the generic item's placeholder (item 9 of the trial).

The file is LP-953's: the shipped UWM round-1 sheet, read and planned, so 0006 is the credit report
invoice (IV-01, `service_invoice` whose name says "credit"). The documents are fictional rows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.models import Company
from app.models.condition_item import ConditionItem
from app.services.condition_links import link_candidates, link_document, unlink_document
from app.services.condition_plan import items_public_for_file
from app.services.condition_reading import GENERIC_ACCEPTABLE
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.test_lp953_linking import (  # noqa: F401 — the autouse model stub and override cleanup
    _doc,
    _drop_db_override,
    _item,
    _model,
    _planned,
)
from tests.models.conftest_helpers import make_loan_file


async def test_the_matching_document_comes_first_and_only_it_matches(
    db_session: AsyncSession,
) -> None:
    loan_file, conditions = await _planned(db_session)
    condition = conditions["0006"]
    item = await _item(db_session, condition)
    report = await _doc(db_session, loan_file, document_type="credit_report", name="Credit report")
    processing = await _doc(
        db_session, loan_file, document_type="service_invoice", name="Processing invoice"
    )
    invoice = await _doc(
        db_session, loan_file, document_type="service_invoice", name="Credit report invoice"
    )
    # Created first, so newest-first alone would put it last: only the match rule lifts it.
    invoice.created_at = datetime(2020, 1, 1, tzinfo=UTC)
    await db_session.flush()

    rows = await link_candidates(db_session, condition=condition, item=item)
    ours = [r for r in rows if r["document_id"] in {report.id, processing.id, invoice.id}]
    assert ours[0]["document_id"] == invoice.id
    assert {r["document_id"]: r["matches"] for r in ours} == {
        invoice.id: True,
        report.id: False,
        processing.id: False,
    }
    assert ours[0]["type_label"] and ours[0]["name"] == "Credit report invoice"


async def test_linked_and_unlinked_by_her_are_flagged(db_session: AsyncSession) -> None:
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
    [row] = [
        r
        for r in await link_candidates(db_session, condition=condition, item=item)
        if r["document_id"] == invoice.id
    ]
    assert row["linked"] and row["matches"] and not row["unlinked_by_her"]

    await unlink_document(
        db_session, condition=condition, item=item, document_id=invoice.id, actor_user_id=None
    )
    [row] = [
        r
        for r in await link_candidates(db_session, condition=condition, item=item)
        if r["document_id"] == invoice.id
    ]
    # Her unlink is the matching rule's third clause: the dialog must not call it a match again.
    assert not row["linked"] and not row["matches"] and row["unlinked_by_her"]


async def test_old_versions_and_other_files_are_not_offered(db_session: AsyncSession) -> None:
    loan_file, conditions = await _planned(db_session)
    condition = conditions["0006"]
    item = await _item(db_session, condition)
    old = await _doc(db_session, loan_file, document_type="service_invoice", name="Credit invoice")
    old.is_current = False
    company = Company(name="Other", slug=f"other-{uuid4().hex[:6]}")
    db_session.add(company)
    await db_session.flush()
    other_file = await make_loan_file(db_session, company=company)
    stranger = await _doc(
        db_session, other_file, document_type="service_invoice", name="Credit report invoice"
    )
    current = await _doc(db_session, loan_file, document_type="credit_report", name="Credit report")

    ids = {
        r["document_id"] for r in await link_candidates(db_session, condition=condition, item=item)
    }
    assert current.id in ids  # positive control: the query returns this file's documents
    assert old.id not in ids and stranger.id not in ids


async def test_the_route_and_an_item_of_another_condition(db_session: AsyncSession) -> None:
    from tests.conditions.test_lender_condition_settings import _clients

    loan_file, conditions = await _planned(db_session)
    condition = conditions["0006"]
    item = await _item(db_session, condition)
    elsewhere = await _item(db_session, conditions["1582"])
    invoice = await _doc(
        db_session, loan_file, document_type="service_invoice", name="Credit report invoice"
    )
    client, _, processor = await _clients(db_session, loan_file)
    async with client:
        ok = await client.get(
            f"/api/v1/conditions/{condition.id}/items/{item.id}/link-candidates", headers=processor
        )
        assert ok.status_code == 200, ok.text
        first = ok.json()[0]
        assert first["document_id"] == str(invoice.id) and first["matches"] is True
        assert set(first) == {
            "document_id",
            "name",
            "type_label",
            "created_at",
            "matches",
            "linked",
            "unlinked_by_her",
        }
        crossed = await client.get(
            f"/api/v1/conditions/{condition.id}/items/{elsewhere.id}/link-candidates",
            headers=processor,
        )
        assert crossed.status_code == 404


async def test_generic_is_the_placeholder_acceptable_form_only(db_session: AsyncSession) -> None:
    loan_file, conditions = await _planned(db_session)
    item: ConditionItem = await _item(db_session, conditions["0006"])

    async def generic() -> bool:
        public = await items_public_for_file(db_session, loan_file_id=loan_file.id)
        [row] = [p for p in public[conditions["0006"].id] if p.id == item.id]
        return bool(row.generic)

    assert not await generic()  # a library item: its own acceptable form
    item.acceptable = GENERIC_ACCEPTABLE
    await db_session.flush()
    assert await generic()
    item.acceptable = GENERIC_ACCEPTABLE + "."
    await db_session.flush()
    assert await generic()
    item.acceptable = "The credit vendor's invoice, her words"
    await db_session.flush()
    assert not await generic()
