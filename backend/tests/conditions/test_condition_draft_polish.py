"""LP-922 follow-up: "Polish with AI" on a condition draft (STOP AND ASK 1, answered 2026-09-29).

The product owner's answers: a proposal (nothing stored until "Use this"); a changed or dropped fact
is shown with a warning, not refused; every draft; always on. The model is mocked: each test states
the polished text the model "returned", and code decides what changed.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from app.ai import condition_polish
from app.conditions.email_facts import FactWarning, fact_warnings
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_vocabulary import PlanOption
from app.services import condition_drafts
from app.services.condition_drafts import DraftRefused, mark_sent
from app.services.condition_plan import set_next_step, update_item
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.test_condition_drafts import _confirmed, _drafts, _items


@pytest.fixture(autouse=True)
def _mocked_reading(monkeypatch: pytest.MonkeyPatch) -> None:
    """The READING's model is mocked as in every condition test; the polish's is mocked per test."""
    from app.services import condition_reading
    from tests.conditions.reading_fixture import fake_complete

    monkeypatch.setattr(condition_reading, "complete", fake_complete())


BEFORE = (
    "<p>Hi Alex,</p><p>Please send the items below by <strong>Thursday, September 3</strong>.</p>"
    "<ol><li><strong>Your Capital One statements ending 9912 for July and August 2026</strong> — all "
    "pages.<br><em>Why: the $2,850 earnest money check clearing.</em></li>"
    "<li><strong>Any other account</strong> — closing needs $38,210.40.</li></ol>"
    '<p>Upload them here: <a href="https://app.example/upload/abc">Secure upload link</a>.</p>'
    "<p>Thank you,<br>Priya Raman · Northstar Home Loans</p>"
)


# --- the fact check: code, not a model ------------------------------------------------------- #


def test_a_rewording_that_keeps_every_fact_has_no_warning() -> None:
    after = BEFORE.replace("Hi Alex,", "Hello Alex,").replace("Please send", "Could you send")
    assert fact_warnings(BEFORE, after) == []


def test_the_same_amount_written_two_ways_is_one_fact() -> None:
    assert fact_warnings(BEFORE, BEFORE.replace("$2,850 ", "$2,850.00 ")) == []


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (
            ("$38,210.40", "$38,210"),
            [FactWarning("dropped", "$38,210.40"), FactWarning("added", "$38,210")],
        ),
        (
            ("ending 9912", "ending 9913"),
            [FactWarning("dropped", "9912"), FactWarning("added", "9913")],
        ),
        (("Thursday, September 3", "Friday, September 4"), None),
        (
            ("by <strong>Thursday, September 3</strong>", "soon"),
            [FactWarning("dropped", "Thursday, September 3")],
        ),
        (
            ('<a href="https://app.example/upload/abc">Secure upload link</a>', "the portal"),
            [FactWarning("dropped", "the upload link")],
        ),
    ],
)
def test_each_changed_fact_is_named(
    change: tuple[str, str], expected: list[FactWarning] | None
) -> None:
    warnings = fact_warnings(BEFORE, BEFORE.replace(*change))
    if expected is None:
        sentences = {w.sentence for w in warnings}
        assert "Dropped: Thursday, September 3" in sentences
        assert "Added: Friday, September 4" in sentences
    else:
        assert warnings == expected


def test_a_new_deadline_with_no_digits_is_named() -> None:
    after = BEFORE.replace("Thank you,", "Please reply by Monday. Thank you,")
    assert [w.sentence for w in fact_warnings(BEFORE, after)] == ["Added: Monday"]


def test_a_merged_item_is_named() -> None:
    after = BEFORE.replace("</li><li>", " and ")
    assert fact_warnings(BEFORE, after)[-1].sentence == "The list had 2 items; the AI's has 1."


# --- the button, through the routes ----------------------------------------------------------- #


def _model_returns(monkeypatch: pytest.MonkeyPatch, transform: Any) -> list[str]:
    """Mock the one call: the 'model' returns `transform(what it was sent)`. Records what it was sent."""
    sent: list[str] = []

    async def fake_complete(**kwargs: Any) -> Any:
        body = kwargs["messages"][0]["content"]
        sent.append(body)
        return SimpleNamespace(text=transform(body))

    monkeypatch.setattr(condition_polish, "complete", fake_complete)
    return sent


@pytest.fixture
def _drop_db_override() -> Any:
    from app.core.database import get_db
    from app.main import app

    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.usefixtures("_drop_db_override")
async def test_polish_proposes_then_she_uses_it(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.conditions.test_condition_reading import _client_for

    sent = _model_returns(
        monkeypatch, lambda body: "```html\n" + body.replace("Hi Alex,", "Hello Alex,") + "\n```"
    )
    loan_file, _, conditions, _ = await _confirmed(db_session)
    draft, message = (await _drafts(db_session, loan_file))["borrower"]
    original = message.body
    client, headers = await _client_for(db_session, loan_file)
    url = f"/api/v1/loan-files/{loan_file.id}/condition-drafts/{draft.id}"
    async with client:
        proposal = (await client.post(f"{url}/polish", headers=headers)).json()
        # ONLY THE BODY WENT TO THE MODEL — never the loan snapshot.
        assert sent == [original]
        assert proposal["refusal"] is None and proposal["warnings"] == []
        assert "Hello Alex," in proposal["polished_html"]
        # The model's code fence is not part of the email.
        assert "```" not in proposal["polished_html"]
        # A PROPOSAL STORES NOTHING.
        await db_session.refresh(message)
        assert message.body == original

        used = await client.put(
            f"{url}/body",
            json={"body_html": proposal["polished_html"], "warnings_accepted": 0},
            headers=headers,
        )
        assert used.status_code == 200, used.text
        assert used.json()["polished_at"] is not None
        assert "Hello Alex," in used.json()["body_html"]
    events = set(
        (
            await db_session.execute(
                select(ConditionEvent.condition_id).where(
                    ConditionEvent.kind == ConditionEventKind.CONDITION_DRAFT_POLISHED
                )
            )
        ).scalars()
    )
    assert events == {conditions[code].id for code in ("7086", "6132", "6637")}


@pytest.mark.usefixtures("_drop_db_override")
async def test_a_dropped_fact_is_shown_with_a_warning_not_refused(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.conditions.test_condition_reading import _client_for

    _model_returns(monkeypatch, lambda body: body.replace("$38,210.40", "the full amount"))
    loan_file, _, _, _ = await _confirmed(db_session)
    draft, _ = (await _drafts(db_session, loan_file))["borrower"]
    client, headers = await _client_for(db_session, loan_file)
    async with client:
        proposal = (
            await client.post(
                f"/api/v1/loan-files/{loan_file.id}/condition-drafts/{draft.id}/polish",
                headers=headers,
            )
        ).json()
    assert proposal["polished_html"] is not None
    assert [w["sentence"] for w in proposal["warnings"]] == ["Dropped: $38,210.40"]


async def test_every_draft_can_be_polished_and_a_failure_is_said(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    loan_file, _, _, _ = await _confirmed(db_session)
    drafts = await _drafts(db_session, loan_file)
    _model_returns(monkeypatch, lambda body: body)
    for draft, _ in drafts.values():
        proposal = await condition_drafts.propose_polish(
            db_session, loan_file=loan_file, draft=draft
        )
        assert proposal.html and proposal.warnings == []

    async def down(**_: Any) -> Any:
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(condition_polish, "complete", down)
    proposal = await condition_drafts.propose_polish(
        db_session, loan_file=loan_file, draft=drafts["question 6178"][0]
    )
    assert proposal.html is None
    assert proposal.refusal == condition_polish.REFUSAL_UNAVAILABLE


async def test_a_sent_email_is_neither_polished_nor_changed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _model_returns(monkeypatch, lambda body: body)
    loan_file, _, _, actor = await _confirmed(db_session)
    draft, _ = (await _drafts(db_session, loan_file))["lo"]
    await mark_sent(db_session, loan_file=loan_file, draft=draft, actor_user_id=actor)
    with pytest.raises(DraftRefused, match="cannot be polished"):
        await condition_drafts.propose_polish(db_session, loan_file=loan_file, draft=draft)
    with pytest.raises(DraftRefused, match="cannot be changed"):
        await condition_drafts.use_polish(
            db_session,
            loan_file=loan_file,
            draft=draft,
            body_html="<p>x</p>",
            warnings_accepted=0,
            actor_user_id=actor,
        )


async def test_the_used_body_is_sanitised(db_session: AsyncSession) -> None:
    loan_file, _, _, actor = await _confirmed(db_session)
    draft, message = (await _drafts(db_session, loan_file))["borrower"]
    await condition_drafts.use_polish(
        db_session,
        loan_file=loan_file,
        draft=draft,
        body_html='<p onclick="x()">Hi</p><script>alert(1)</script>',
        warnings_accepted=0,
        actor_user_id=actor,
    )
    assert "<script" not in (message.body or "") and "onclick" not in (message.body or "")


async def test_her_polish_survives_an_unrelated_edit_but_not_a_change_to_its_items(
    db_session: AsyncSession,
) -> None:
    loan_file, _, conditions, actor = await _confirmed(db_session)
    draft, message = (await _drafts(db_session, loan_file))["borrower"]
    polished = "<p>Hello Alex, polished.</p><ol><li>one</li><li>two</li></ol>"
    await condition_drafts.use_polish(
        db_session,
        loan_file=loan_file,
        draft=draft,
        body_html=polished,
        warnings_accepted=0,
        actor_user_id=actor,
    )
    # An edit that does not touch the borrower email leaves her words and the mark.
    from tests.conditions.test_next_steps import point_items_at_a_document

    await point_items_at_a_document(db_session, conditions["1582"])
    await set_next_step(
        db_session,
        condition=conditions["1582"],
        next_step=PlanOption.ALREADY_IN_FILE,
        actor_user_id=actor,
    )
    assert message.body == polished and draft.polished_at is not None
    # One that moves an item out of it rebuilds the email from the library, and the mark clears.
    other = (await _items(db_session, conditions["7086"]))[1]
    await update_item(
        db_session,
        condition=conditions["7086"],
        item=other,
        option=PlanOption.I_WILL_DO_IT,
        name=None,
        performers=None,
        due_date=None,
        actor_user_id=actor,
    )
    assert draft.polished_at is None
    assert message.subject == "Documents needed for your loan — 1 item"
