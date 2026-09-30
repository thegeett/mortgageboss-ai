"""LP-925's "Done when": the test file's ready conditions produce a package with one named PDF and one
note per condition, and "Mark submitted" moves exactly those conditions to Sent to lender.

Round 1 of the fictional file, with the borrower email sent and both statements accepted:
- 6132 is Ready by its evidence;
- 7086 is Ready once the deposit is explained (its "any other account" item removed);
- 6178 is Ready by her choice through Stage 2's control (LP-934 M2);
- 0006 was Ready at confirm, with the credit invoice already in the file.
6637 still waits on title's receipt, and 0132 on the LO.
"""

from __future__ import annotations

import io
import json
import zipfile
from types import SimpleNamespace
from typing import Any

import pymupdf
import pytest
from app.models.condition import ConditionPrepStatus
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_item import ConditionItem
from app.models.condition_package import PackageStatus
from app.models.document import Document
from app.models.loan_file import LoanFile
from app.schemas.condition import PrepStatusRequest
from app.services import condition_evidence, condition_package
from app.services.condition_evidence import check_document
from app.services.condition_package import PackageRefused
from app.services.condition_plan import remove_item
from app.services.condition_status import move_prep_status
from app.storage import get_storage_backend
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.statement_fixture import add_statement, july_and_august
from tests.conditions.test_condition_evidence import TODAY, _asked, _evidence


def _pdf(pages: int) -> bytes:
    doc = pymupdf.open()
    for number in range(pages):
        doc.new_page().insert_text((72, 72), f"page {number + 1}")
    content = bytes(doc.tobytes())
    doc.close()
    return content


async def _store(document: Document, pages: int) -> None:
    document.storage_path = await get_storage_backend().save(
        company_id=document.loan_file_id,
        file_id=document.loan_file_id,
        document_id=document.id,
        filename=document.original_filename,
        content=_pdf(pages),
    )


async def _ready(db: AsyncSession, *, store: bool = False) -> tuple[LoanFile, dict[str, Any], Any]:
    loan_file, conditions, actor = await _asked(db)
    other = next(
        i
        for i in (
            await db.execute(
                select(ConditionItem).where(ConditionItem.condition_id == conditions["7086"].id)
            )
        ).scalars()
        if i.key == "other_accounts"
    )
    await remove_item(db, condition=conditions["7086"], item=other, actor_user_id=actor)
    both = await add_statement(db, loan_file, july_and_august())
    if store:
        await _store(both, 12)
    await check_document(db, document_id=both.id, today=TODAY)
    (row,) = [e for e in await _evidence(db, conditions["7086"]) if e.findings]
    await condition_evidence.answer_finding(
        db,
        condition=conditions["7086"],
        evidence_id=row.id,
        index=0,
        answer="explained",
        reason="Gift from a relative; gift letter and transfer in the file",
        actor_user_id=actor,
    )
    await move_prep_status(
        db,
        condition=conditions["6178"],
        payload=PrepStatusRequest(to=ConditionPrepStatus.READY),
        actor_user_id=actor,
    )
    return loan_file, conditions, actor


def _model_writes(monkeypatch: pytest.MonkeyPatch, notes: dict[str, str]) -> list[str]:
    from app.ai import client

    sent: list[str] = []

    async def fake(**kwargs: Any) -> Any:
        sent.append(kwargs["messages"][0]["content"])
        return SimpleNamespace(text=json.dumps({"notes": notes}))

    monkeypatch.setattr(client, "complete", fake)
    return sent


async def test_the_package_has_one_named_pdf_and_one_note_per_ready_condition(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _model_writes(monkeypatch, {})
    loan_file, conditions, actor = await _ready(db_session)
    package = await condition_package.build(db_session, loan_file=loan_file, actor_user_id=actor)
    rows = {r["code"]: r for r in package.rows}
    # Sheet order; exactly the Ready ones — 0006 too, a READY prior-to-funding condition.
    assert [r["code"] for r in package.rows] == ["7086", "6132", "6178", "0006"]
    assert rows["7086"]["file_name"] == "7086 - Assets.pdf"
    assert rows["6132"]["file_name"] == "6132 - Assets.pdf"
    assert rows["0006"]["file_name"] == "0006 - Invoice.pdf"
    assert rows["7086"]["pages"] == 12
    # A push-back has no document, and its note says why.
    assert rows["6178"]["file_name"] is None and rows["6178"]["document_ids"] == []
    assert rows["6178"]["note"] == (
        "No document — the lender's letter shows Must Not Close Before 09/30/2026, "
        "the policy's start date."
    )
    assert rows["7086"]["note"] == (
        "Capital One ··9912 Jul and Aug statements, all 12 pages; $41,914.42 verified against "
        "$38,210.40 required; 08/21 deposit sourced."
    )
    assert all(r["note"] and r["note_source"] == "code" for r in package.rows)

    view = await condition_package.view(db_session, loan_file=loan_file)
    assert view is not None
    # 1228 (lender doing it), 6637 and 0132 are prior to docs and still open.
    assert [(w["code"], w["text"]) for w in view.warnings if w["kind"] == "open_prior_to_docs"] == [
        ("1228", "the final inspection is ordered through the lender and not back yet"),
        ("6637", "we are still waiting for it"),
        ("0132", "nothing has been asked for yet")
        if conditions["0132"].prep_status is ConditionPrepStatus.TO_DO
        else ("0132", "we are still waiting for it"),
    ]
    assert view.later_codes == ["1947", "1582", "0007", "6378"]
    assert (view.cutoff, view.cutoff_tz, view.lender_short) == ("20:00", "America/New_York", "UWM")


async def test_the_ai_words_the_notes_and_code_checks_their_numbers(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _model_writes(
        monkeypatch,
        {
            "6132": "August statement ··9912, consecutive to July, all 12 pages.",
            # An invented figure: code keeps its own note for 7086.
            "7086": "Statements show $45,000.00 on hand.",
        },
    )
    loan_file, _, actor = await _ready(db_session)
    package = await condition_package.build(db_session, loan_file=loan_file, actor_user_id=actor)
    rows = {r["code"]: r for r in package.rows}
    assert rows["6132"]["note_source"] == "ai"
    assert rows["7086"]["note_source"] == "code"
    assert "45,000" not in rows["7086"]["note"]
    # Only the rows' facts went to the model — no loan snapshot, no full account number.
    (payload,) = sent
    assert {r["code"] for r in json.loads(payload)} == {"7086", "6132", "6178", "0006"}
    assert "9912" in payload and "ssn" not in payload.lower()


async def test_a_note_may_restate_the_amount_the_condition_asks_about(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 6637's summary says "$2,850" and its reading's items say "$2,850.00". The check compares
    # tokens, so without the reading's amounts in the facts the lender's own figure was refused.
    _model_writes(
        monkeypatch,
        {
            "6637": "Earnest money $2,850.00: title's receipt, and the check cleared.",
            "6132": "Earnest money $2,950.00 as well.",
        },
    )
    loan_file, conditions, actor = await _ready(db_session)
    await move_prep_status(
        db_session,
        condition=conditions["6637"],
        payload=PrepStatusRequest(to=ConditionPrepStatus.READY),
        actor_user_id=actor,
    )
    package = await condition_package.build(db_session, loan_file=loan_file, actor_user_id=actor)
    rows = {r["code"]: r for r in package.rows}
    assert rows["6637"]["note_source"] == "ai"
    assert rows["6637"]["note"].startswith("Earnest money $2,850.00")
    # Another condition's amount is not licensed by 6637's.
    assert rows["6132"]["note_source"] == "code"


async def test_an_information_only_condition_is_not_packaged(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Nothing is uploaded for a condition the lender printed for information, even one at Ready.
    _model_writes(monkeypatch, {})
    loan_file, conditions, actor = await _ready(db_session)
    assert conditions["6132"].prep_status is ConditionPrepStatus.READY  # the positive control
    conditions["6132"].info_only = True
    await db_session.flush()
    package = await condition_package.build(db_session, loan_file=loan_file, actor_user_id=actor)
    assert [r["code"] for r in package.rows] == ["7086", "6178", "0006"]


async def test_her_note_is_kept_through_a_rebuild(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _model_writes(monkeypatch, {})
    loan_file, conditions, actor = await _ready(db_session)
    package = await condition_package.build(db_session, loan_file=loan_file, actor_user_id=actor)
    await condition_package.update_row(
        db_session,
        package=package,
        condition_id=conditions["6132"].id,
        note="August statement, all pages.",
        included=None,
        fields=None,
    )
    again = await condition_package.build(db_session, loan_file=loan_file, actor_user_id=actor)
    row = next(r for r in again.rows if r["code"] == "6132")
    assert (row["note"], row["note_source"]) == ("August statement, all pages.", "edited")


async def test_mark_submitted_moves_exactly_those_to_sent_to_lender(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _model_writes(monkeypatch, {})
    loan_file, conditions, actor = await _ready(db_session)
    package = await condition_package.build(db_session, loan_file=loan_file, actor_user_id=actor)
    # She leaves 0006 out of this upload.
    await condition_package.update_row(
        db_session,
        package=package,
        condition_id=conditions["0006"].id,
        note=None,
        included=False,
        fields=None,
    )
    moved = await condition_package.submit(
        db_session, loan_file=loan_file, package=package, actor_user_id=actor
    )
    assert moved == ["7086", "6132", "6178"]
    for code in moved:
        assert conditions[code].prep_status is ConditionPrepStatus.WITH_UNDERWRITER, code
        assert conditions[code].sent_at is not None
    assert conditions["0006"].prep_status is ConditionPrepStatus.READY
    assert {c.lender_status.value for c in conditions.values()} == {"open"}
    assert package.status is PackageStatus.SUBMITTED and package.submitted_at is not None
    events = (
        await db_session.execute(
            select(ConditionEvent.condition_id).where(
                ConditionEvent.loan_file_id == loan_file.id,
                ConditionEvent.kind == ConditionEventKind.CONDITION_PREP_MOVED,
            )
        )
    ).scalars()
    assert {conditions[c].id for c in moved} <= set(events)
    # The record stands: no second submit, no edits.
    with pytest.raises(PackageRefused, match="already submitted"):
        await condition_package.submit(
            db_session, loan_file=loan_file, package=package, actor_user_id=actor
        )
    with pytest.raises(PackageRefused, match="record of what was sent"):
        await condition_package.update_row(
            db_session,
            package=package,
            condition_id=conditions["7086"].id,
            note="x",
            included=None,
            fields=None,
        )


async def test_the_download_is_one_merged_pdf_per_condition_and_the_notes(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _model_writes(monkeypatch, {})
    loan_file, _, actor = await _ready(db_session, store=True)
    package = await condition_package.build(db_session, loan_file=loan_file, actor_user_id=actor)
    content, missing = await condition_package.download(db_session, package=package)
    archive = zipfile.ZipFile(io.BytesIO(content))
    names = set(archive.namelist())
    assert {"7086 - Assets.pdf", "6132 - Assets.pdf", "notes.txt"} <= names
    with pymupdf.open(stream=archive.read("7086 - Assets.pdf"), filetype="pdf") as merged:
        assert merged.page_count == 12
    notes = archive.read("notes.txt").decode()
    assert notes.splitlines()[0].startswith("7086 — Capital One ··9912")
    # The credit invoice fixture has no stored bytes: named as missing, never silently dropped.
    assert missing == ["0006: invoice.pdf"]


async def test_a_package_warns_of_a_du_rerun_until_marked_done(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import figures_check

    _model_writes(monkeypatch, {})
    loan_file, _, actor = await _ready(db_session)

    async def rerun(*_: Any, **__: Any) -> Any:
        return figures_check.FiguresCheck(du_rerun=True, du_reasons=["the DTI rises above 45%"])

    monkeypatch.setattr(figures_check, "figures_check", rerun)
    package = await condition_package.build(db_session, loan_file=loan_file, actor_user_id=actor)
    view = await condition_package.view(db_session, loan_file=loan_file)
    assert view is not None and view.du_rerun_open
    assert any(w["kind"] == "du_rerun" for w in view.warnings)
    await condition_package.mark_du_rerun_done(db_session, package=package)
    view = await condition_package.view(db_session, loan_file=loan_file)
    assert view is not None and not view.du_rerun_open


@pytest.fixture
def _drop_db_override() -> Any:
    from app.core.database import get_db
    from app.main import app

    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.usefixtures("_drop_db_override")
async def test_the_routes(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.conditions.test_condition_reading import _client_for

    _model_writes(monkeypatch, {})
    loan_file, _, _ = await _ready(db_session)
    client, headers = await _client_for(db_session, loan_file)
    base = f"/api/v1/loan-files/{loan_file.id}/condition-package"
    async with client:
        before = (await client.get(base, headers=headers)).json()
        assert before["status"] is None and before["ready_count"] == 4
        built = (await client.post(f"{base}/build", headers=headers)).json()
        assert [r["code"] for r in built["rows"]] == ["7086", "6132", "6178", "0006"]
        submitted = await client.post(f"{base}/submit", headers=headers)
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["status"] == "submitted"
        zipped = await client.get(f"{base}/download", headers=headers)
        assert zipped.headers["content-type"] == "application/zip"


async def test_separate_monthly_statements_are_both_packaged_and_a_rejected_one_is_not(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """July alone falls short of the $38,210.40 ("covers required funds" fails on its own row), and is
    still July's evidence. The package used to take only rows with every check passed, so 7086 went
    to the lender with August alone. A 5-page August (rejected) never goes in."""
    from app.services.condition_plan import remove_item
    from tests.conditions.statement_fixture import august, july

    _model_writes(monkeypatch, {})
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
    first = await add_statement(db_session, loan_file, july(), name="july.pdf")
    short = await add_statement(db_session, loan_file, august(pages_present=5), name="aug-5.pdf")
    second = await add_statement(db_session, loan_file, august(), name="august.pdf")
    for document in (first, short, second):
        await check_document(db_session, document_id=document.id, today=TODAY)
    rows = {e.document_id: e for e in await _evidence(db_session, conditions["7086"])}
    # The positive control: July's own row fails only the sum.
    assert [c["check"] for c in rows[first.id].checks if c["result"] == "failed"] == [
        "covers_required_funds"
    ]
    await condition_evidence.answer_finding(
        db_session,
        condition=conditions["7086"],
        evidence_id=rows[second.id].id,
        index=0,
        answer="explained",
        reason="Gift from a relative",
        actor_user_id=actor,
    )
    assert conditions["7086"].prep_status is ConditionPrepStatus.READY
    package = await condition_package.build(db_session, loan_file=loan_file, actor_user_id=actor)
    row = next(r for r in package.rows if r["code"] == "7086")
    assert row["document_ids"] == [str(first.id), str(second.id)]
    # One line for the deposit, though the rejected August carries the same one.
    assert row["note"].count("deposit sourced") == 1


async def test_a_deposit_explained_only_on_a_rejected_statement_is_not_in_the_note(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another account's statement (rejected on "right account") has its own 08/19 $3,500.00 deposit,
    and she explains it anyway. That statement is not submitted, so the note must not say "sourced"."""
    from datetime import date

    from app.services.condition_plan import remove_item
    from tests.conditions.statement_fixture import AUGUST, _tx, august

    _model_writes(monkeypatch, {})
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
    other_account = august(
        last4="4471",
        transactions=[_tx(date(2026, 8, 19), "Transfer In", "3500.00", "deposit"), *AUGUST[:1]],
    )
    wrong = await add_statement(db_session, loan_file, other_account, name="other.pdf")
    await check_document(db_session, document_id=wrong.id, today=TODAY)
    both = await add_statement(db_session, loan_file, july_and_august())
    await check_document(db_session, document_id=both.id, today=TODAY)
    rows = {e.document_id: e for e in await _evidence(db_session, conditions["7086"])}
    index = next(i for i, f in enumerate(rows[wrong.id].findings) if f["date"] == "2026-08-19")
    for evidence_id, at, reason in (
        (rows[wrong.id].id, index, "Transfer between her own accounts"),
        (rows[both.id].id, 0, "Gift from a relative"),
    ):
        await condition_evidence.answer_finding(
            db_session,
            condition=conditions["7086"],
            evidence_id=evidence_id,
            index=at,
            answer="explained",
            reason=reason,
            actor_user_id=actor,
        )
    assert rows[wrong.id].findings[index]["status"] == "explained"  # the positive control
    assert conditions["7086"].prep_status is ConditionPrepStatus.READY
    package = await condition_package.build(db_session, loan_file=loan_file, actor_user_id=actor)
    note = next(r for r in package.rows if r["code"] == "7086")["note"]
    assert "08/19" not in note
    assert note.count("deposit sourced") == 1


async def test_a_note_names_a_document_by_its_display_name(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LP-943: with no name of its own, a document is named in the note by its display name
    ("Service invoice attached"), never by its classifier slug."""
    _model_writes(monkeypatch, {})
    loan_file, _, actor = await _ready(db_session)
    invoice = (
        await db_session.execute(
            select(Document).where(
                Document.loan_file_id == loan_file.id, Document.original_filename == "invoice.pdf"
            )
        )
    ).scalar_one()
    invoice.document_name = None
    package = await condition_package.build(db_session, loan_file=loan_file, actor_user_id=actor)
    note = next(r for r in package.rows if r["code"] == "0006")["note"]
    assert note == "Service invoice attached."
