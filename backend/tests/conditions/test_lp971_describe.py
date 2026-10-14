"""LP-971 — "Describe it": her sentence becomes proposed steps, only from LP-969's building blocks, with
nothing in them that her words or the lender's do not contain. Stores nothing.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from app.ai import condition_describe
from app.ai.client import AIClientError, AICompletion
from app.ai.condition_describe import (
    BLOCKS,
    EMAIL_TO,
    MAX_STEPS,
    REFUSAL_EMPTY,
    REFUSAL_NO_STEPS,
    REFUSAL_UNAVAILABLE,
    REFUSAL_UNREADABLE,
    checked_steps,
    describe_steps,
)
from app.models.condition_item import ConditionItem
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

LENDER = (
    "Final inspection is required to confirm the work was completed per the plans and specs. "
    "(On new construction this condition can be moved to closing at the request of the client.)"
)


def _check(raw: list[dict[str, Any]], words: str = "do it") -> tuple[list[Any], list[str]]:
    return checked_steps(raw, words=words, lender_words=LENDER)


# --------------------------------------------------------------------------------------------- #
# Only the real building blocks
# --------------------------------------------------------------------------------------------- #


def test_every_real_block_is_kept() -> None:
    raw = [
        {"block": "email", "to": "lender", "text": "Order the final inspection"},
        {"block": "upload_ask", "text": "Photos of the finished work"},
        {"block": "upload_mine", "text": "The inspection invoice"},
        {"block": "check", "text": "The completion report"},
        {"block": "underwriter", "text": "Can this move to closing?"},
        {"block": "todo", "text": "Call the builder"},
    ]
    steps, left_out = _check(raw)
    assert [s.block for s in steps] == [r["block"] for r in raw]
    assert steps[0].to == "lender"
    assert left_out == []


def test_a_block_that_is_not_one_is_left_out_and_says_so() -> None:
    steps, left_out = _check([{"block": "fax", "text": "Fax the lender"}])
    assert steps == []
    assert left_out == ["Left out a step we can't do here (fax)."]


def test_a_step_with_no_words_is_left_out() -> None:
    """A task named "" would reach `add_item`, which refuses it, after she pressed Add: say so here."""
    steps, left_out = _check([{"block": "todo", "text": "   "}, {"block": "check"}])
    assert steps == []
    assert left_out == ["Left out a step with no words."] * 2


def test_an_email_goes_only_to_someone_the_screen_can_email() -> None:
    # The appraiser goes through the lender, and she does not email herself.
    for who in ("appraiser", "processor", "nobody"):
        steps, left_out = _check([{"block": "email", "to": who, "text": "Send it"}])
        assert steps == [] and left_out == [f"Left out “Send it”: we can't email {who} from here."]
    # The attorney shares Title's email: it is the same step, not a refusal.
    steps, _ = _check([{"block": "email", "to": "attorney", "text": "Send the CD"}])
    assert steps[0].to == "title"


def test_one_question_to_the_underwriter_at_most() -> None:
    steps, left_out = _check(
        [
            {"block": "underwriter", "text": "Can this move to closing?"},
            {"block": "push_back", "text": "It is new construction"},
        ]
    )
    assert [s.block for s in steps] == ["underwriter"]
    assert left_out == [
        "Left out “It is new construction”: a condition carries one question to the underwriter."
    ]


def test_no_more_than_six_steps() -> None:
    raw = [{"block": "todo", "text": f"Step {n}"} for n in "abcdefgh"]
    steps, left_out = _check(raw)
    assert len(steps) == MAX_STEPS
    assert len(left_out) == 2 and "at most 6 steps" in left_out[0]


# --------------------------------------------------------------------------------------------- #
# Nothing invented
# --------------------------------------------------------------------------------------------- #


def test_an_amount_in_neither_text_is_refused_by_name() -> None:
    steps, left_out = _check([{"block": "email", "to": "lender", "text": "Pay the $450 fee"}])
    assert steps == []
    assert left_out == [
        "Left out “Pay the $450 fee”: it mentions $450, which is not in what you wrote or the "
        "lender's words."
    ]


def test_an_amount_she_wrote_is_allowed() -> None:
    """THE CONTROL: the rule is "in her words or the lender's", not "no amounts"."""
    steps, left_out = _check(
        [{"block": "email", "to": "lender", "text": "Pay the $450 fee"}],
        words="Ask the lender to take the $450 inspection fee",
    )
    assert [s.text for s in steps] == ["Pay the $450 fee"] and left_out == []


def test_a_date_or_day_in_neither_text_is_refused() -> None:
    for text, fact in (("Send it by 10/15/2026", "10/15/2026"), ("Send it by Friday", "Friday")):
        steps, left_out = _check([{"block": "todo", "text": text}])
        assert steps == [] and fact in left_out[0]


def test_a_loan_number_in_neither_text_is_refused() -> None:
    steps, left_out = _check([{"block": "underwriter", "text": "Move loan 4410229 to closing"}])
    assert steps == [] and "4410229" in left_out[0]


# --------------------------------------------------------------------------------------------- #
# The model call
# --------------------------------------------------------------------------------------------- #


def _answer(text: str) -> Any:
    async def _complete(**kwargs: Any) -> AICompletion:
        return AICompletion(
            text=text,
            input_tokens=10,
            output_tokens=10,
            model=kwargs["model"],
            stop_reason="end_turn",
            cache_read_tokens=0,
            cache_write_tokens=0,
        )

    return _complete


async def test_it_proposes_the_steps_the_model_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        condition_describe,
        "complete",
        _answer(
            '{"steps": [{"block": "underwriter", "text": "Can 1228 move to closing? It is new '
            'construction"}], "unclear": null}'
        ),
    )
    proposal = await describe_steps(
        words="Ask the underwriter to move 1228 to closing, it's new construction",
        lender_words=LENDER,
    )
    assert proposal.refusal is None
    assert [(s.block, s.text) for s in proposal.steps] == [
        ("underwriter", "Can 1228 move to closing? It is new construction")
    ]


async def test_a_failure_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _down(**_: Any) -> Any:
        raise AIClientError("the AWS login expired")

    monkeypatch.setattr(condition_describe, "complete", _down)
    assert (await describe_steps(words="x", lender_words=LENDER)).refusal == REFUSAL_UNAVAILABLE
    monkeypatch.setattr(condition_describe, "complete", _answer("not json at all"))
    assert (await describe_steps(words="x", lender_words=LENDER)).refusal == REFUSAL_UNREADABLE
    assert (await describe_steps(words="   ", lender_words=LENDER)).refusal == REFUSAL_EMPTY


async def test_no_steps_says_why_unless_the_why_invents_something(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        condition_describe,
        "complete",
        _answer('{"steps": [], "unclear": "Say who should send the report."}'),
    )
    got = await describe_steps(words="hmm", lender_words=LENDER)
    assert got.refusal == "Say who should send the report."
    # The model's sentence reaches her, so an amount in it that neither text has is not shown.
    monkeypatch.setattr(
        condition_describe,
        "complete",
        _answer('{"steps": [], "unclear": "The $300 fee must be paid first."}'),
    )
    assert (await describe_steps(words="hmm", lender_words=LENDER)).refusal == REFUSAL_NO_STEPS


def test_the_prompt_names_exactly_the_blocks_and_recipients_the_code_accepts() -> None:
    """THE PROMPT IS A SECOND COPY OF TWO LISTS. A block or recipient the code accepts and the prompt
    never offers is dead; one the prompt offers and the code refuses is a step left out every time."""
    prompt = (
        Path(condition_describe.__file__).parent / "prompts" / condition_describe.PROMPT_PATH
    ).read_text()
    offered = set(re.findall(r'^- "([a-z_]+)":', prompt, re.M))
    assert offered == set(BLOCKS)
    line = re.search(r'Needs "to", one of: ([^.]+)\.', prompt.replace("\n  ", " "))
    assert line is not None
    assert {who.strip() for who in line.group(1).split(",")} == set(EMAIL_TO)


# --------------------------------------------------------------------------------------------- #
# The route
# --------------------------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _drop_db_override() -> Any:
    from app.core.database import get_db
    from app.main import app

    yield
    app.dependency_overrides.pop(get_db, None)


async def test_the_route_proposes_and_stores_nothing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import condition_reading
    from tests.conditions.reading_fixture import fake_complete
    from tests.conditions.test_condition_plan import _conditions, _planned_round_one
    from tests.conditions.test_lender_condition_settings import _clients

    monkeypatch.setattr(condition_reading, "complete", fake_complete())
    loan_file, _ = await _planned_round_one(db_session)
    condition = (await _conditions(db_session, loan_file))["1228"]
    monkeypatch.setattr(
        condition_describe,
        "complete",
        _answer('{"steps": [{"block": "todo", "text": "Call the builder"}], "unclear": null}'),
    )
    items_before = await db_session.scalar(
        select(func.count()).where(ConditionItem.condition_id == condition.id)
    )
    client, _, processor = await _clients(db_session, loan_file)
    async with client:
        got = await client.post(
            f"/api/v1/conditions/{condition.id}/plan/describe",
            json={"text": "I'll call the builder"},
            headers=processor,
        )
    assert got.status_code == 200
    assert got.json() == {
        "steps": [{"block": "todo", "text": "Call the builder", "to": None, "document_kinds": []}],
        "left_out": [],
        "refusal": None,
    }
    assert (
        await db_session.scalar(
            select(func.count()).where(ConditionItem.condition_id == condition.id)
        )
        == items_before
    )


def test_the_response_schema_offers_exactly_the_blocks_the_checker_keeps() -> None:
    """THE THIRD COPY OF THE BLOCK LIST: `DescribedStepPublic.block` is a Literal, so a block added to
    `BLOCKS` and not to it would fail validation on the way out, with a 500 instead of a step."""
    from typing import get_args

    from app.schemas.condition import DescribedStepPublic

    assert set(get_args(DescribedStepPublic.model_fields["block"].annotation)) == set(BLOCKS)


# --------------------------------------------------------------------------------------------- #
# The frontend's copies (the LP-971 review: the test_condition_type_mirror.py pattern)
# --------------------------------------------------------------------------------------------- #

_FRONTEND = Path(__file__).resolve().parents[3] / "frontend"
_ADD_STEP = _FRONTEND / "components" / "file" / "conditions" / "plan-add-step.tsx"
_PLAN_WORDS = _FRONTEND / "lib" / "conditions" / "plan-words.ts"
_TYPES = _FRONTEND / "lib" / "types" / "conditions.ts"


def test_the_frontend_files_are_where_these_tests_read_them() -> None:
    """A moved file would make every comparison below pass over nothing."""
    for path in (_ADD_STEP, _PLAN_WORDS, _TYPES):
        assert path.is_file(), path


def _quoted(body: str) -> set[str]:
    return set(re.findall(r'"([a-z_]+)"', body))


def test_the_screen_emails_exactly_who_the_server_lets_a_proposal_email() -> None:
    """THE SAME DERIVATION ON BOTH SIDES. The screen's `EMAIL_WHO` is `PERFORMER_LABEL`'s keys minus
    `NOT_EMAILED`; the server's `EMAIL_TO` is the performers minus its own `NOT_EMAILED`. A recipient on
    one side only is a proposed email the screen cannot show, or a To choice the AI may never propose."""
    labels = re.search(
        r"PERFORMER_LABEL: Record<Performer, string> = \{(.*?)\};", _PLAN_WORDS.read_text(), re.S
    )
    excluded = re.search(
        r"const NOT_EMAILED: readonly Performer\[\] = \[(.*?)\];", _ADD_STEP.read_text(), re.S
    )
    assert labels is not None and excluded is not None, "the frontend shapes these tests parse"
    keys = set(re.findall(r"^\s*([a-z_]+):", labels.group(1), re.M))
    left_out = _quoted(excluded.group(1))
    assert keys and left_out, "parsed something on both"
    assert keys - left_out == set(EMAIL_TO)


def test_the_screens_block_type_is_exactly_the_servers_blocks() -> None:
    match = re.search(r"export type PlanBlock =(.*?);", _TYPES.read_text(), re.S)
    assert match is not None, "PlanBlock is where this test reads it"
    blocks = _quoted(match.group(1))
    assert blocks, "parsed something"
    assert blocks == set(BLOCKS)


def test_a_day_word_she_wrote_is_hers_whatever_the_case() -> None:
    """LP-971 REVIEW — the builder's first question, measured rather than reasoned.

    A natural step repeats a day word she used: she writes "get the monday statement", the model
    answers "Ask the borrower for the Monday statement". That must not be read as an invented date. It
    is not, and the reason is in another module: `email_facts.fact_warnings` searches the BEFORE text
    and the AFTER text for day words with `re.I` on both sides (its `_DATE_WORDS` block). This pins
    that, because nothing here would notice if either flag were dropped, and the first thing to break
    would be a step repeating her own words being refused as invented.
    """
    steps, left_out = checked_steps(
        [{"block": "upload_ask", "text": "Ask the borrower for the Monday statement"}],
        words="get the monday statement from the borrower",
        lender_words="Provide a bank statement.",
    )
    assert [step.text for step in steps] == ["Ask the borrower for the Monday statement"]
    assert left_out == []

    # THE CONTROL: a day word in NEITHER her words nor the lender's is still an invention.
    steps, left_out = checked_steps(
        [{"block": "upload_ask", "text": "Ask the borrower for the Monday statement"}],
        words="get the statement from the borrower",
        lender_words="Provide a bank statement.",
    )
    assert steps == []
    assert left_out == [
        "Left out “Ask the borrower for the Monday statement”: it mentions Monday, which is not in "
        "what you wrote or the lender's words."
    ]


def test_a_performer_sharing_an_email_with_another_is_not_offered_separately() -> None:
    """LP-971 REVIEW — the REASON the attorney is excluded, which neither exclusion list carries.

    The mirror test above pins that the server's `NOT_EMAILED` and the screen's agree. Both could drop
    `attorney` together and stay green — and that is the LP-969 review's defect returning:
    `condition_plan._RECIPIENT` maps `TITLE` and `ATTORNEY` to the same `title_attorney` email, so
    offering both puts two labels on one draft and either choice produces the same email, with nothing
    on the screen saying so.

    So the rule is stated where it can be checked: when two performers share a recipient key, at most
    one of them may be emailed. The builder left this one to the review; this is it.
    """
    from collections import defaultdict

    from app.services.condition_plan import _RECIPIENT

    by_key: dict[str, list[str]] = defaultdict(list)
    for performer, (key, _label) in _RECIPIENT.items():
        by_key[key].append(performer.value)
    shared = {key: names for key, names in by_key.items() if len(names) > 1}
    assert shared, (
        "the premise: some recipient key is shared by two performers (today `title_attorney`), so "
        "this test is comparing something"
    )
    for key, names in shared.items():
        offered = [name for name in names if name in EMAIL_TO]
        assert len(offered) <= 1, (
            f"{sorted(names)} all send to the one “{key}” email, and {sorted(offered)} are offered "
            "separately: picking either writes the same draft, and the screen cannot say which"
        )
