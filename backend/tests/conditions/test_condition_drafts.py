"""LP-922's "Done when": round 1 produces three drafts — borrower, title/attorney, LO — plus the question
on 6178, and marking them sent moves the right conditions to Waiting on ….

The file is fictional (ADR-405): Alex Rivera, Example Title & Escrow, an LO at an example address and
the letter's own underwriter, Lena Brennan (UW II), as a lender contact. The model is mocked.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from app.models.borrower import Borrower
from app.models.communication import Communication, CommunicationStatus
from app.models.condition import Condition, ConditionPrepStatus, OwnerHint
from app.models.condition_draft import ConditionDraft
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_item import ConditionItem
from app.models.condition_round import ConditionRound
from app.models.condition_vocabulary import ConditionItemStatus, PlanOption
from app.models.lender_contact import LenderContact, LenderContactRole
from app.models.loan_file import LoanFile
from app.models.loan_file_participant import LoanFileParticipant, ParticipantRole
from app.models.property import Property
from app.services import condition_drafts, condition_reading
from app.services.condition_drafts import DraftRefused, mark_sent
from app.services.condition_plan import confirm_round_plan, set_next_step, update_item
from app.services.condition_reading import ConfirmedItem, confirm_reading
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.reading_fixture import fake_complete
from tests.conditions.test_condition_plan import _actor, _conditions, _items, _planned_round_one


@pytest.fixture(autouse=True)
def _mocked_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(condition_reading, "complete", fake_complete())


async def _people(db: AsyncSession, loan_file: LoanFile) -> None:
    """The file's people, all fictional."""
    db.add(
        Borrower(
            loan_file_id=loan_file.id,
            first_name="Alex",
            last_name="Rivera",
            email="alex.rivera@example.com",
            is_primary=True,
        )
    )
    db.add(
        LoanFileParticipant(
            loan_file_id=loan_file.id,
            role=ParticipantRole.TITLE,
            name="Example Title & Escrow",
            email="closings@exampletitle.example",
        )
    )
    db.add(
        Property(
            loan_file_id=loan_file.id,
            address_line="100 Example Ln",
            city="Columbia",
            state="SC",
            postal_code="29201",
        )
    )
    loan_file.loan_officer_name = "Jordan Lee"
    loan_file.loan_officer_email = "jordan.lee@lo.example"
    assert loan_file.lender_id is not None
    db.add(
        LenderContact(
            lender_id=loan_file.lender_id,
            name="Lena Brennan",
            email="underwriting@lender.example",
            role=LenderContactRole.UNDERWRITER,
            is_active=True,
        )
    )
    await db.flush()


async def _confirmed(
    db: AsyncSession, *, people: bool = True
) -> tuple[LoanFile, ConditionRound, dict[str, Condition], Any]:
    loan_file, round_ = await _planned_round_one(db)
    if people:
        await _people(db, loan_file)
    actor = await _actor(db, loan_file)
    conditions = await _conditions(db, loan_file)
    await confirm_reading(
        db,
        condition=conditions["0132"],
        items=[
            ConfirmedItem(name=i.name, performers=(i.performer,), key=i.key)
            for i in await _items(db, conditions["0132"])
        ],
        actor_user_id=actor,
    )
    await confirm_round_plan(db, round_=round_, actor_user_id=actor)
    return loan_file, round_, conditions, actor


async def _drafts(
    db: AsyncSession, loan_file: LoanFile
) -> dict[str, tuple[ConditionDraft, Communication]]:
    # ORDERED, AND THE UNSENT ONE WINS (LP-944). Once a recipient has a sent draft AND a new one (a re-ask
    # after the round's email was sent), this dict keeps whichever row comes LAST. Without an ORDER BY
    # that was the planner's choice: a merge join returned the sent draft last, and
    # `test_the_reask_goes_into_a_new_borrower_email` failed in about one full run in three, never
    # alone, because the plan follows table statistics that a long run changes.
    rows = (
        await db.execute(
            select(ConditionDraft, Communication)
            .join(Communication, Communication.id == ConditionDraft.communication_id)
            .where(ConditionDraft.loan_file_id == loan_file.id, Communication.deleted_at.is_(None))
            .order_by(Communication.status == CommunicationStatus.DRAFT, Communication.created_at)
        )
    ).tuples()
    out: dict[str, tuple[ConditionDraft, Communication]] = {}
    for draft, message in rows:
        key = draft.recipient.value
        if draft.condition_id is not None:
            condition = await db.get(Condition, draft.condition_id)
            key = f"question {condition.lender_code if condition else ''}"
        out[key] = (draft, message)
    return out


def _text(body: str) -> str:
    """The body as a reader sees it: block tags become spaces, inline tags vanish."""
    spaced = re.sub(r"<(?:/p|br|/li|li|ol|/ol)>", " ", body)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", spaced)).strip()


async def _codes(db: AsyncSession, draft: ConditionDraft) -> list[str]:
    items = (
        await db.execute(select(ConditionItem).where(ConditionItem.draft_id == draft.id))
    ).scalars()
    ids = list(dict.fromkeys(item.condition_id for item in items))
    rows = (await db.execute(select(Condition).where(Condition.id.in_(ids)))).scalars()
    return sorted((c.lender_code or "" for c in rows), key=lambda code: code)


async def test_round_one_makes_three_drafts_and_the_question(db_session: AsyncSession) -> None:
    loan_file, _, _, _ = await _confirmed(db_session)
    drafts = await _drafts(db_session, loan_file)
    assert set(drafts) == {"borrower", "title_attorney", "lo", "question 6178"}
    assert sorted(await _codes(db_session, drafts["borrower"][0])) == ["6132", "6637", "7086"]
    assert sorted(await _codes(db_session, drafts["title_attorney"][0])) == [
        "0132",
        "1947",
        "6378",
        "6637",
    ]
    assert await _codes(db_session, drafts["lo"][0]) == ["0132"]
    for _, message in drafts.values():
        assert message.status is CommunicationStatus.DRAFT
        assert message.party is None  # kept out of Phase 4's party drafts


async def test_the_borrower_email_is_s3_04(db_session: AsyncSession) -> None:
    loan_file, _, _, _ = await _confirmed(db_session)
    _, message = (await _drafts(db_session, loan_file))["borrower"]
    assert message.recipient == "Alex Rivera <alex.rivera@example.com>"
    assert message.subject == "Documents needed for your loan — 2 items"
    text = _text(message.body or "")
    assert text.startswith("Hi Alex,")
    assert "please send the items below by Thursday, September 3." in text
    assert (
        "Your Capital One statements ending 9912 for July and August 2026 — all pages, downloaded "
        "as PDFs from Capital One's website (not screenshots)."
    ) in text
    assert (
        "Why: the lender needs to see enough funds for closing, the next month in a row, and the "
        "$2,850 earnest money check clearing."
    ) in text
    assert (
        "Any other account you plan to use for closing — the two most recent monthly statements, "
        "all pages. Why: closing needs $38,210.40 and $11,062.18 is verified so far."
    ) in text
    assert (
        "Upload them here: Secure upload link for your loan (it lists exactly what we need)."
        in text
    )
    assert message.upload_link_url and message.upload_link_url in (message.body or "")
    assert text.endswith("Thank you, Priya Raman · Reading")


async def test_the_title_email_is_s3_05(db_session: AsyncSession) -> None:
    loan_file, _, _, _ = await _confirmed(db_session)
    _, message = (await _drafts(db_session, loan_file))["title_attorney"]
    assert message.recipient == "Example Title & Escrow <closings@exampletitle.example>"
    assert message.subject == "RIVERA 1226500417 — items for closing"
    text = _text(message.body or "")
    assert (
        "For RIVERA · UWM loan 1226500417 (100 Example Ln, Columbia, SC), the lender needs" in text
    )
    assert (
        "Earnest money receipt — a written statement that you received the $2,850.00 earnest money "
        "deposit, or a copy of the canceled check."
    ) in text
    assert "Wire instructions that match the attorney named on the updated" in text
    assert (
        "Final seller Closing Disclosure with the final closing package (needed before funding)."
        in text
    )
    assert "1226500417" in text and "on all checks sent to lender" in text.lower()


async def test_the_question_is_s3_06(db_session: AsyncSession) -> None:
    loan_file, _, _, _ = await _confirmed(db_session)
    _, message = (await _drafts(db_session, loan_file))["question 6178"]
    assert message.recipient == "Lena Brennan (UW II) <underwriting@lender.example>"
    assert message.subject == "RIVERA 1226500417 — condition 6178"
    text = _text(message.body or "")
    assert text.startswith("Hi Lena,")
    assert "Question on RIVERA · 1226500417, condition 6178 (updated HOI declarations)." in text
    assert (
        "The approval shows Must Not Close Before 09/30/2026, and the HOI policy provided is "
        "effective 09/30/2026."
    ) in text
    assert "Could you clear 6178, or let me know what else you need?" in text


async def test_no_body_carries_more_than_the_last_four(db_session: AsyncSession) -> None:
    loan_file, _, _, _ = await _confirmed(db_session)
    for _, message in (await _drafts(db_session, loan_file)).values():
        body = _text(message.body or "")
        body = body.replace("1226500417", "")  # the lender's loan number, which the letter prints
        assert not re.search(r"\d{3}-?\d{2}-?\d{4}", body), "an SSN-shaped run"
        assert not re.search(r"\d{5,}", body), "a long digit run"


async def test_marking_sent_moves_the_right_conditions(db_session: AsyncSession) -> None:
    loan_file, _, conditions, actor = await _confirmed(db_session)
    drafts = await _drafts(db_session, loan_file)
    for key in ("borrower", "title_attorney", "lo", "question 6178"):
        await mark_sent(db_session, loan_file=loan_file, draft=drafts[key][0], actor_user_id=actor)
    expected = {
        "7086": OwnerHint.BORROWER,
        "6132": OwnerHint.BORROWER,
        "6637": OwnerHint.BORROWER,  # the borrower email went first; the title send leaves it
        "6178": OwnerHint.LENDER,
        # S3-12: "Waiting on LO". The disclosure (the LO's) is 0132's first item, so it waits on the
        # LO even though the title email, carrying its wire instructions, was marked sent first.
        "0132": OwnerHint.BROKER,
        "1947": OwnerHint.TITLE,
        "6378": OwnerHint.TITLE,
    }
    for code, owner in expected.items():
        assert conditions[code].prep_status is ConditionPrepStatus.WAITING, code
        assert conditions[code].waiting_on is owner, code
    for code in ("1582", "0007", "1228"):
        assert conditions[code].prep_status is ConditionPrepStatus.TO_DO, code
    assert conditions["0006"].prep_status is ConditionPrepStatus.READY
    # The lender's track never moves.
    assert {c.lender_status.value for c in conditions.values()} == {"open"}
    for _, message in (await _drafts(db_session, loan_file)).values():
        assert message.status is CommunicationStatus.SENT
    asked = (
        await db_session.execute(
            select(ConditionItem).where(ConditionItem.condition_id == conditions["7086"].id)
        )
    ).scalars()
    assert {item.status for item in asked} == {ConditionItemStatus.REQUESTED}
    moves = (
        await db_session.execute(
            select(ConditionEvent).where(
                ConditionEvent.loan_file_id == loan_file.id,
                ConditionEvent.kind == ConditionEventKind.CONDITION_PREP_MOVED,
            )
        )
    ).scalars()
    by_email = [e for e in moves if e.detail.get("by") == "email"]
    # Seven moves to Waiting, and 0132's owner following from Title to the LO when the LO's went.
    assert len(by_email) == 8


async def test_each_drafted_condition_has_an_event(db_session: AsyncSession) -> None:
    loan_file, _, conditions, _ = await _confirmed(db_session)
    rows = set(
        (
            await db_session.execute(
                select(ConditionEvent.condition_id).where(
                    ConditionEvent.loan_file_id == loan_file.id,
                    ConditionEvent.kind == ConditionEventKind.CONDITION_DRAFTED,
                )
            )
        ).scalars()
    )
    drafted = {c.lender_code for c in conditions.values() if c.id in rows}
    assert drafted == {"7086", "6132", "6637", "6178", "0132", "1947", "6378"}


async def test_a_changed_step_follows_into_the_drafts(db_session: AsyncSession) -> None:
    loan_file, _, conditions, actor = await _confirmed(db_session)
    # 6378 is now "I'll do it": it leaves the title email.
    (item,) = await _items(db_session, conditions["6378"])
    await update_item(
        db_session,
        condition=conditions["6378"],
        item=item,
        option=PlanOption.I_WILL_DO_IT,
        name=None,
        performers=None,
        due_date=None,
        actor_user_id=actor,
    )
    drafts = await _drafts(db_session, loan_file)
    assert "6378" not in await _codes(db_session, drafts["title_attorney"][0])
    assert "on all checks" not in _text(drafts["title_attorney"][1].body or "").lower()
    # 6178's push-back withdrawn: its question is deleted, not left behind.
    await set_next_step(
        db_session, condition=conditions["6178"], next_step=None, actor_user_id=actor
    )
    assert "question 6178" not in await _drafts(db_session, loan_file)


async def test_a_second_round_adds_to_the_unsent_title_email(db_session: AsyncSession) -> None:
    loan_file, round_, _, actor = await _confirmed(db_session)
    before = await _drafts(db_session, loan_file)
    await condition_drafts.sync_round_drafts(db_session, round_=round_, actor_user_id=actor)
    after = await _drafts(db_session, loan_file)
    # Idempotent: syncing again makes no second draft to anyone.
    assert {k: d.id for k, (d, _) in before.items()} == {k: d.id for k, (d, _) in after.items()}


async def test_a_missing_address_is_asked_once_and_remembered(db_session: AsyncSession) -> None:
    loan_file, _, _, actor = await _confirmed(db_session, people=False)
    draft, message = (await _drafts(db_session, loan_file))["title_attorney"]
    assert message.recipient == ""
    with pytest.raises(DraftRefused, match="Add an email address"):
        await mark_sent(db_session, loan_file=loan_file, draft=draft, actor_user_id=actor)
    await condition_drafts.set_address(
        db_session,
        loan_file=loan_file,
        draft=draft,
        email="closings@exampletitle.example",
        name="Example Title & Escrow",
        actor_user_id=actor,
    )
    assert message.recipient == "Example Title & Escrow <closings@exampletitle.example>"
    remembered = (
        await db_session.execute(
            select(LoanFileParticipant).where(
                LoanFileParticipant.loan_file_id == loan_file.id,
                LoanFileParticipant.role == ParticipantRole.TITLE,
            )
        )
    ).scalar_one()
    assert remembered.email == "closings@exampletitle.example"


async def test_deleting_a_draft_frees_its_items_and_moves_nothing(db_session: AsyncSession) -> None:
    loan_file, _, conditions, _ = await _confirmed(db_session)
    draft, message = (await _drafts(db_session, loan_file))["borrower"]
    await condition_drafts.delete(db_session, loan_file=loan_file, draft=draft)
    assert message.deleted_at is not None
    items = (
        await db_session.execute(
            select(ConditionItem).where(ConditionItem.condition_id == conditions["7086"].id)
        )
    ).scalars()
    assert all(item.draft_id is None for item in items)
    assert conditions["7086"].prep_status is ConditionPrepStatus.TO_DO


@pytest.fixture
def _drop_db_override() -> Any:
    from app.core.database import get_db
    from app.main import app

    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.usefixtures("_drop_db_override")
async def test_the_dialog_reads_what_the_screens_show(db_session: AsyncSession) -> None:
    from tests.conditions.test_condition_reading import _client_for

    loan_file, _, _, _ = await _confirmed(db_session)
    client, headers = await _client_for(db_session, loan_file)
    base = f"/api/v1/loan-files/{loan_file.id}/condition-drafts"
    async with client:
        listed = (await client.get(base, headers=headers)).json()
        by_label = {row["label"]: row for row in listed}
        assert set(by_label) == {"Borrower", "Title/attorney", "LO", "Question 6178"}
        assert by_label["Borrower"]["codes"] == ["7086", "6132", "6637"]

        borrower = (
            await client.get(f"{base}/{by_label['Borrower']['id']}", headers=headers)
        ).json()
        assert borrower["title"] == "Email to the borrower · round 1"
        assert [(c["code"], c["label"]) for c in borrower["in_this_email"]] == [
            ("7086", "More assets for closing"),
            ("6132", "One more consecutive month"),
            ("6637", "Earnest money: source and clearance"),
        ]
        assert borrower["asked_once"] == [
            {"what": "July and August statements", "codes": ["7086", "6132", "6637"]}
        ]
        assert borrower["becomes"] == "Waiting on Borrower"

        title = (
            await client.get(f"{base}/{by_label['Title/attorney']['id']}", headers=headers)
        ).json()
        assert title["title"] == "Email to the title company / attorney · round 1"
        assert [(c["code"], c["label"]) for c in title["in_this_email"]] == [
            ("6637", "Earnest money receipt"),
            ("0132", "Matching wire instructions"),
            ("1947", "Final seller CD (prior to funding)"),
            ("6378", "Instruction to title"),
        ]
        assert title["mortgagee_clause"] == (
            "United Wholesale Mortgage ISAOA, ATIMA PO BOX 202175 FLORENCE, SC 29502 "
            "Phone: (800) 981-8898"
        )
        # The round's other EMAILS — the question to the underwriter is not one of them (S3-05).
        assert [o["label"] for o in title["other_drafts"]] == [
            "Borrower",
            "LO (Priya → loan officer)",
        ]
        assert title["other_drafts"][0]["summary"] == "3 conditions"
        assert title["other_drafts"][1]["summary"] == "0132 disclosure"

        question = (
            await client.get(f"{base}/{by_label['Question 6178']['id']}", headers=headers)
        ).json()
        assert question["title"] == "Question to the underwriter · 6178"
        assert question["why_facts"] == [
            {"label": "Letter, round 1:", "value": "Must Not Close Before 09/30/2026"},
            {"label": "Condition text: policy", "value": "not effective until 09/30/2026"},
        ]
        assert question["becomes"] == "Waiting on Lender"

        sent = await client.post(
            f"{base}/{by_label['Question 6178']['id']}/mark-sent", headers=headers
        )
        assert sent.status_code == 200, sent.text
        assert sent.json()["status"] == "sent"
        again = await client.post(
            f"{base}/{by_label['Question 6178']['id']}/mark-sent", headers=headers
        )
        assert again.status_code == 409

        rows = (
            await client.get(f"/api/v1/loan-files/{loan_file.id}/conditions", headers=headers)
        ).json()
        by_code = {row["lender_code"]: row for row in rows}
        assert by_code["6178"]["prep_status"] == "waiting"
        assert by_code["6178"]["question_draft"]["status"] == "sent"
        assert by_code["7086"]["items"][0]["draft"]["status"] == "draft"


@pytest.mark.usefixtures("_drop_db_override")
async def test_another_companys_draft_is_not_found(db_session: AsyncSession) -> None:
    from tests.conditions.test_condition_reading import _client_for

    loan_file, _, _, _ = await _confirmed(db_session)
    draft, _ = (await _drafts(db_session, loan_file))["borrower"]
    other_file, _ = await _planned_round_one(db_session)
    client, headers = await _client_for(db_session, other_file)
    async with client:
        # Their file id with our draft id, and our file id from their session: both refused.
        mine = f"/api/v1/loan-files/{other_file.id}/condition-drafts/{draft.id}"
        assert (await client.get(mine, headers=headers)).status_code == 404
        assert (await client.post(f"{mine}/mark-sent", headers=headers)).status_code == 404
        theirs = f"/api/v1/loan-files/{loan_file.id}/condition-drafts"
        assert (await client.get(theirs, headers=headers)).status_code == 404


async def test_a_send_never_overrides_her_own_move(db_session: AsyncSession) -> None:
    from app.schemas.condition import PrepStatusRequest
    from app.services.condition_status import move_prep_status

    loan_file, _, conditions, actor = await _confirmed(db_session)
    await move_prep_status(
        db_session,
        condition=conditions["0132"],
        payload=PrepStatusRequest(to=ConditionPrepStatus.WAITING, waiting_on=OwnerHint.TITLE),
        actor_user_id=actor,
    )
    drafts = await _drafts(db_session, loan_file)
    await mark_sent(db_session, loan_file=loan_file, draft=drafts["lo"][0], actor_user_id=actor)
    assert conditions["0132"].waiting_on is OwnerHint.TITLE


async def test_the_activity_names_each_send(db_session: AsyncSession) -> None:
    from app.models.activity_log import ActivityLog, ActivityType

    loan_file, _, _, actor = await _confirmed(db_session)
    drafts = await _drafts(db_session, loan_file)
    for key in ("borrower", "question 6178"):
        await mark_sent(db_session, loan_file=loan_file, draft=drafts[key][0], actor_user_id=actor)
    summaries = set(
        (
            await db_session.execute(
                select(ActivityLog.summary).where(
                    ActivityLog.loan_file_id == loan_file.id,
                    ActivityLog.activity_type == ActivityType.COMMUNICATION_SENT,
                )
            )
        ).scalars()
    )
    assert summaries == {"Borrower email marked sent", "Question on 6178 marked sent"}


def test_a_template_with_a_missing_fact_is_not_filled() -> None:
    """A hole is never printed: a placeholder with no value makes the template decline, and the line
    falls back to the item's own name and acceptable form."""
    assert condition_drafts.fill("closing needs {required}.", {"required": None}) is None
    assert condition_drafts.fill("closing needs {required}.", {}) is None
    assert (
        condition_drafts.fill("**Receipt** of {amount}", {"amount": "$2,850.00"})
        == "<strong>Receipt</strong> of $2,850.00"
    )
    # The lender's words are escaped, never markup.
    assert (
        condition_drafts.fill("{instruction}", {"instruction": "<b>x</b>"})
        == "&lt;b&gt;x&lt;/b&gt;"
    )


async def test_the_lenders_words_cannot_put_markup_in_a_body(db_session: AsyncSession) -> None:
    """The one place the lender's text reaches a body (TI-04's instruction) is escaped, then the body
    goes through Phase 4's allow-list — the frontend's `draft.body_html` sink rests on both."""
    loan_file, round_, conditions, actor = await _confirmed(db_session)
    conditions["6378"].verbatim_text = "TC: <img src=x onerror=alert(1)> on every check."
    await condition_drafts.sync_round_drafts(db_session, round_=round_, actor_user_id=actor)
    _, message = (await _drafts(db_session, loan_file))["title_attorney"]
    assert "<img" not in (message.body or "")
    assert "&lt;img src=x onerror=alert(1)&gt;" in (message.body or "")


@pytest.mark.usefixtures("_drop_db_override")
async def test_the_due_date_is_editable_in_the_draft(db_session: AsyncSession) -> None:
    from tests.conditions.test_condition_reading import _client_for

    loan_file, _, _, _ = await _confirmed(db_session)
    draft, message = (await _drafts(db_session, loan_file))["borrower"]
    client, headers = await _client_for(db_session, loan_file)
    async with client:
        url = f"/api/v1/loan-files/{loan_file.id}/condition-drafts/{draft.id}"
        assert (await client.get(url, headers=headers)).json()["due_date"] == "2026-09-03"
        response = await client.put(
            f"{url}/due-date", json={"due_date": "2026-09-04"}, headers=headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["due_date"] == "2026-09-04"
    assert "by Friday, September 4." in _text(message.body or "")
    items = (
        await db_session.execute(select(ConditionItem).where(ConditionItem.draft_id == draft.id))
    ).scalars()
    assert {item.due_date.isoformat() for item in items if item.due_date} == {"2026-09-04"}
