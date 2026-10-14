"""LP-971 follow-up — what "Describe it" adds is what she meant, said, and checked (the owner on 0006).

The owner wrote "Send email to credit report vendor, receive an email and attach here" on 0006 (IV-01, the
credit report invoice) and got:
- a second "Credit report invoice" task, the condition's own step 1 again, and what the email already
  brings back;
- an email step whose "We check it" checked nothing: an added step had no document type, so anything
  she linked passed.

Here:
- the model is shown the condition's tasks and told an email includes the reply and the attaching, and
  code leaves out a task of hers that the condition already has (`checked_steps`, `task_words`);
- a step that brings back the condition's own document is checked as it (`same_document`), with the
  library's match words, so an appraisal invoice does not answer the credit invoice's ask;
- the payload says what each task is checked as (`document_kinds`, `has_checks`).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from app.ai import condition_describe
from app.ai.client import AICompletion
from app.ai.condition_describe import _user_content, checked_steps, task_words
from app.conditions.library import load_library
from app.models.condition_item import ConditionItem
from app.models.condition_vocabulary import ConditionItemStatus, Performer, PlanOption
from app.models.document import Document, DocumentStatus, UploadSource
from app.models.loan_file import LoanFile
from app.services import condition_reading
from app.services.condition_plan import add_item, items_public_for_file, same_document
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.reading_fixture import fake_complete
from tests.conditions.test_condition_plan import _actor, _conditions, _planned_round_one

ASK = "Please provide invoice for credit report"


@pytest.fixture(autouse=True)
def _mocked_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(condition_reading, "complete", fake_complete())


@pytest.fixture
def _no_db_override() -> Any:
    from app.core.database import get_db
    from app.main import app

    yield
    app.dependency_overrides.pop(get_db, None)


# --- not a task it already has -----------------------------------------------------------------------


def test_the_same_task_is_the_same_whatever_verb_starts_it() -> None:
    assert task_words("Credit report invoice") == "credit report invoice"
    assert task_words("Upload the credit report invoice.") == "credit report invoice"
    assert task_words("Attach: Credit-report invoice") == "credit report invoice"
    # THE CONTROL: a different task stays different.
    assert task_words("Call the vendor about the credit report invoice") != "credit report invoice"


def test_a_task_of_hers_the_condition_has_is_left_out_saying_so() -> None:
    steps, left_out = checked_steps(
        [
            {"block": "email", "to": "other_party", "text": ASK},
            {"block": "upload_mine", "text": "Credit report invoice"},
        ],
        words="Send email to credit report vendor, receive an email and attach here",
        lender_words="Provide copy of invoice for credit report.",
        existing=["Credit report invoice"],
    )
    assert [(step.block, step.text) for step in steps] == [("email", ASK)]
    assert left_out == ["Left out “Credit report invoice”: this condition already has that task."]


def test_an_ask_for_the_task_and_a_different_task_are_kept() -> None:
    """The controls, ON A CONDITION THAT HAS THE TASK (an empty list would keep everything whatever
    the rule): an email IS how she gets a task's document, and a to-do that only mentions the task is
    another task."""
    steps, left_out = checked_steps(
        [
            {"block": "email", "to": "other_party", "text": "Credit report invoice"},
            {"block": "upload_ask", "text": "Credit report invoice"},
            {"block": "todo", "text": "Call the vendor about the credit report invoice"},
        ],
        words="email the vendor for the credit report invoice, call the vendor about it",
        lender_words="",
        existing=["Credit report invoice"],
    )
    assert [step.block for step in steps] == ["email", "upload_ask", "todo"]
    assert left_out == []


def test_the_model_is_shown_the_tasks_only_when_there_are_some() -> None:
    shown = _user_content("words", "lender", None, ["Credit report invoice", "Payoff letter"])
    assert "TASKS IT ALREADY HAS:\n- Credit report invoice\n- Payoff letter" in shown
    assert "TASKS IT ALREADY HAS" not in _user_content("words", "lender", None, [])


def test_the_prompt_says_an_email_brings_the_reply_back_and_not_to_repeat_a_task() -> None:
    from app.ai.prompt_loader import load_prompt

    prompt = load_prompt(condition_describe.PROMPT_PATH)
    assert condition_describe.PROMPT_PATH == "conditions/describe_v2.txt"
    assert "An email already includes everything after it is sent" in prompt
    assert "Never add a step to receive, attach or upload" in prompt
    assert "Never propose a task that is in TASKS IT ALREADY HAS" in prompt


# --- checked as the condition's own document ---------------------------------------------------------


def test_same_document_is_the_one_task_whose_words_she_used() -> None:
    found = same_document("IV-01", ASK)
    assert found is not None and found.key == "invoice"
    assert list(found.documents) == ["service_invoice"]
    # THE CONTROLS: no task's words, no type.
    assert same_document("IV-01", "Please send the payoff letter") is None
    assert same_document(None, ASK) is None


def test_same_document_will_not_guess_between_two_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    """A type with two tasks whose words both appear: checking her upload against one of them would be a
    guess, so neither. No library type has two worded tasks today (measured: `load_library()`), so the
    type is a stand-in; the first assertion is the guard's positive control."""
    from types import SimpleNamespace

    from app.services import condition_plan

    assert not any(
        sum(1 for each in t.items if each.match_words) >= 2 for t in load_library().types.values()
    ), "if a real type has two worded tasks now, test it here instead of the stand-in"
    two = SimpleNamespace(
        items=[
            SimpleNamespace(key="statement", match_words=("statement",)),
            SimpleNamespace(key="letter", match_words=("letter",)),
        ]
    )
    monkeypatch.setattr(condition_plan, "load_library", lambda: SimpleNamespace(get=lambda _: two))
    assert same_document("XX-01", "the bank statement").key == "statement"  # type: ignore[union-attr]
    assert same_document("XX-01", "the statement and the letter") is None


async def _added(
    db: AsyncSession, *, name: str, brings_document: bool
) -> tuple[LoanFile, Any, ConditionItem]:
    loan_file, _ = await _planned_round_one(db)
    condition = (await _conditions(db, loan_file))["0006"]
    actor = await _actor(db, loan_file)
    item = await add_item(
        db,
        condition=condition,
        name=name,
        performers=[Performer.OTHER_PARTY],
        option=PlanOption.ASK_THIRD_PARTY,
        actor_user_id=actor,
        brings_document=brings_document,
    )
    await db.flush()
    return loan_file, condition, item


async def test_an_added_ask_for_the_invoice_is_checked_as_the_invoice(
    db_session: AsyncSession,
) -> None:
    _, _, item = await _added(db_session, name=ASK, brings_document=True)
    assert item.key.startswith("invoice.added")
    assert item.documents == ["service_invoice"]
    assert item.acceptable == "The credit vendor's invoice for this file"


async def test_a_step_that_brings_nothing_is_not(db_session: AsyncSession) -> None:
    """THE CONTROL: the same words on a step that brings no document (a to-do, a call) take nothing."""
    _, _, item = await _added(db_session, name=ASK, brings_document=False)
    assert item.key.startswith("manual_")
    assert item.documents == []


async def _arrives(db: AsyncSession, loan_file: LoanFile, name: str) -> Document:
    from app.services.condition_evidence import check_document

    doc = Document(
        loan_file_id=loan_file.id,
        original_filename=f"{uuid4().hex[:6]}.pdf",
        mime_type="application/pdf",
        file_size_bytes=10,
        storage_path=f"{loan_file.id}/{uuid4().hex}.pdf",
        document_type="service_invoice",
        document_name=name,
        status=DocumentStatus.COMPLETED,
        upload_source=UploadSource.USER_UPLOAD,
    )
    db.add(doc)
    await db.flush()
    await check_document(db, document_id=doc.id)
    await db.flush()
    return doc


async def test_the_credit_invoice_answers_it_and_another_invoice_does_not(
    db_session: AsyncSession,
) -> None:
    """WHY THE KEY CARRIES THE LIBRARY'S: its match words. With the type alone, every service invoice
    on the file (the final inspection's, 0007's) would link to the credit invoice's ask and pass."""
    loan_file, _, item = await _added(db_session, name=ASK, brings_document=True)
    await _arrives(db_session, loan_file, "Final inspection invoice")
    await db_session.refresh(item)
    assert item.status is ConditionItemStatus.OPEN, "another invoice is not the credit invoice"
    await _arrives(db_session, loan_file, "Credit report invoice 08/01")
    await db_session.refresh(item)
    # Linked by matching, and RECEIVED, not done: nothing has read it yet, so she accepts it (LP-953),
    # exactly as on the condition's own invoice task.
    assert item.status is ConditionItemStatus.RECEIVED


async def test_the_email_still_names_it_in_her_words(db_session: AsyncSession) -> None:
    """The library key is for checking; the email and the side column keep what she wrote."""
    from app.services.condition_drafts import item_words

    _, condition, item = await _added(db_session, name=ASK, brings_document=True)
    assert item_words(condition, item) == "please provide invoice for credit report"


# --- what the screen is told --------------------------------------------------------------------------


async def test_the_payload_says_what_each_task_is_checked_as(db_session: AsyncSession) -> None:
    loan_file, condition, added = await _added(db_session, name=ASK, brings_document=True)
    actor = await _actor(db_session, loan_file)
    bare = await add_item(
        db_session,
        condition=condition,
        name="Call the vendor",
        performers=[Performer.PROCESSOR],
        option=PlanOption.I_WILL_DO_IT,
        actor_user_id=actor,
    )
    await db_session.flush()
    rows = {
        row.id: row
        for row in (await items_public_for_file(db_session, loan_file_id=loan_file.id))[
            condition.id
        ]
    }
    own = next(row for row in rows.values() if row.key == "invoice")
    assert (own.document_kinds, own.has_checks) == (["service invoice"], False)
    assert rows[added.id].document_kinds == ["service invoice"]
    assert (rows[bare.id].document_kinds, rows[bare.id].has_checks) == ([], False)


async def test_a_task_with_checks_says_so(db_session: AsyncSession) -> None:
    """THE CONTROL for `has_checks`: a library task with checks beyond its type (7086's statements)."""
    loan_file, _ = await _planned_round_one(db_session)
    condition = (await _conditions(db_session, loan_file))["7086"]
    items = (await items_public_for_file(db_session, loan_file_id=loan_file.id))[condition.id]
    assert any(row.has_checks for row in items)


async def test_the_door_carries_brings_document(
    db_session: AsyncSession, _no_db_override: Any
) -> None:
    from tests.conditions.test_lender_condition_settings import _clients

    loan_file, _ = await _planned_round_one(db_session)
    condition = (await _conditions(db_session, loan_file))["0006"]
    client, _, processor = await _clients(db_session, loan_file)
    async with client:
        got = await client.post(
            f"/api/v1/conditions/{condition.id}/items",
            json={
                "name": ASK,
                "performers": ["other_party"],
                "option": "ask_third_party",
                "brings_document": True,
            },
            headers=processor,
        )
    assert got.status_code in (200, 201), got.text
    added = next(row for row in got.json()["items"] if row["name"] == ASK)
    assert added["key"].startswith("invoice.added")
    assert added["document_kinds"] == ["service invoice"]


async def test_describe_shows_the_tasks_leaves_out_the_repeat_and_names_the_check(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, _no_db_override: Any
) -> None:
    from tests.conditions.test_lender_condition_settings import _clients

    loan_file, _ = await _planned_round_one(db_session)
    condition = (await _conditions(db_session, loan_file))["0006"]
    seen: list[str] = []

    async def _complete(**kwargs: Any) -> AICompletion:
        seen.append(kwargs["messages"][0]["content"])
        return AICompletion(
            text='{"steps": [{"block": "email", "to": "other_party", "text": "'
            + ASK
            + '"}, {"block": "upload_mine", "text": "Credit report invoice"}, '
            + '{"block": "todo", "text": "Call the credit vendor"}], "unclear": null}',
            input_tokens=10,
            output_tokens=10,
            model=kwargs["model"],
            stop_reason="end_turn",
            cache_read_tokens=0,
            cache_write_tokens=0,
        )

    monkeypatch.setattr(condition_describe, "complete", _complete)
    client, _, processor = await _clients(db_session, loan_file)
    async with client:
        got = await client.post(
            f"/api/v1/conditions/{condition.id}/plan/describe",
            json={"text": "Send email to credit report vendor, receive an email and attach here"},
            headers=processor,
        )
    assert got.status_code == 200, got.text
    body = got.json()
    assert "TASKS IT ALREADY HAS:\n- Credit report invoice" in seen[0]
    assert body["steps"] == [
        {"block": "email", "to": "other_party", "text": ASK, "document_kinds": ["service invoice"]},
        # A to-do names the credit vendor and brings nothing back, so nothing is checked as the invoice.
        {"block": "todo", "to": None, "text": "Call the credit vendor", "document_kinds": []},
    ]
    assert body["left_out"] == [
        "Left out “Credit report invoice”: this condition already has that task."
    ]
    # Nothing stored: a proposal is not a plan.
    count = await db_session.scalar(
        select(ConditionItem.id).where(
            ConditionItem.condition_id == condition.id, ConditionItem.name == ASK
        )
    )
    assert count is None
