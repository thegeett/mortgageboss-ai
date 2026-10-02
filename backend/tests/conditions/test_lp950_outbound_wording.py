"""LP-950 — outbound wording (items 2 and 3 of the 2026-09-30 staging trial).

- A generic item's line uses the lender's own words, every account number masked to its last four. The
  placeholders (`GENERIC_NAME`, `GENERIC_ACCEPTABLE`) never reach an email: a guard renders EVERY
  template and checks.
- The email TO the lender asks it to act ("Please order the final inspection …"), never "the lender
  needs", and its subject names the request.

The end-to-end case is LF-DH8V's: the UWM sheet on a file with no lender, so every condition is generic.
"""

from __future__ import annotations

import inspect
import re
from typing import Any

import pytest
from app.models.condition import Condition
from app.models.condition_item import ConditionItem
from app.models.condition_vocabulary import Performer, PlanOption
from app.services import condition_drafts, condition_reading
from app.services.condition_drafts import (
    LetterFacts,
    borrower_lines,
    lender_lines,
    mask_accounts,
    party_lines,
    render_borrower,
    render_lender,
    render_party,
    render_question,
)
from app.services.condition_reading import GENERIC_ACCEPTABLE, GENERIC_NAME
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.reading_fixture import fake_complete

LOAN = "1226474352"
PLACEHOLDERS = (GENERIC_NAME, GENERIC_ACCEPTABLE, "what the lender's words describe")


def _letter(**overrides: Any) -> LetterFacts:
    values: dict[str, Any] = {
        "surname": "RIVERA",
        "loan_number": LOAN,
        "lender_short": "UWM",
        "property_line": "100 Example Ln, Columbia, SC",
        "mortgagee_clause": None,
        "must_not_close_before": None,
        "underwriter": None,
    }
    values.update(overrides)
    return LetterFacts(**{k: v for k, v in values.items() if k in LetterFacts.__dataclass_fields__})


def _text(body: str) -> str:
    spaced = re.sub(r"<(?:/p|br|/li|li|ol|/ol)>", " ", body)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", spaced)).strip()


def _generic(
    text: str, performer: Performer = Performer.TITLE, name: str = GENERIC_NAME
) -> tuple[Condition, ConditionItem]:
    condition = Condition(
        verbatim_text=text, lender_code="6378", canonical_type_id=None, reading={}
    )
    item = ConditionItem(
        key="request",
        name=name,
        acceptable=GENERIC_ACCEPTABLE,
        performer=performer,
        performers=[performer.value],
        option=PlanOption.ASK_THIRD_PARTY,
        documents=[],
        specifics={},
    )
    return condition, item


# --------------------------------------------------------------------------------------------- #
# Masking
# --------------------------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "masked"),
    [
        ("Statement for account 123456789 at Chase", "Statement for account ****6789 at Chase"),
        ("acct #00012345.", "acct #****2345."),
        ("SSN 123-45-6789 on file", "SSN ****6789 on file"),
        (f"Loan {LOAN} on every check", f"Loan {LOAN} on every check"),
        ("$2,850.00 and $125000 deposit", "$2,850.00 and $125000 deposit"),
        ("dated 09/30/2026 per B3-4.2-02", "dated 09/30/2026 per B3-4.2-02"),
        ("ending 9912", "ending 9912"),
    ],
)
def test_account_numbers_are_masked_to_their_last_four(text: str, masked: str) -> None:
    assert mask_accounts(text, keep=LOAN) == masked


# --------------------------------------------------------------------------------------------- #
# Generic lines use the lender's words
# --------------------------------------------------------------------------------------------- #


def test_a_generic_item_line_is_the_lenders_words_masked() -> None:
    pair = _generic(
        "TC: Title company to include lender loan number on all checks sent to lender. "
        "Wire from account 4455667788."
    )
    [line] = party_lines([pair], _letter())
    text = _text(line.body)
    assert "Title company to include lender loan number on all checks sent to lender" in text
    assert "****7788" in text and "4455667788" not in text
    assert not any(p.lower() in text.lower() for p in PLACEHOLDERS)


def test_a_named_generic_item_keeps_its_name_and_quotes_the_lender() -> None:
    pair = _generic(
        "Title to provide final Seller Closing Disclosure with final closing package.",
        name="Final Seller Closing Disclosure",
    )
    [line] = party_lines([pair], _letter())
    assert _text(line.body) == (
        "Final Seller Closing Disclosure — as the lender wrote it: “Title to provide final Seller "
        "Closing Disclosure with final closing package”."
    )


def test_an_item_with_its_own_acceptable_form_keeps_it() -> None:
    """The positive control: only the placeholder is replaced, not a real acceptable form."""
    condition, item = _generic("Provide the HOA questionnaire.", name="HOA questionnaire")
    item.acceptable = "Completed by the HOA, signed and dated"
    [line] = party_lines([(condition, item)], _letter())
    assert _text(line.body) == "HOA questionnaire — completed by the HOA, signed and dated."


# --------------------------------------------------------------------------------------------- #
# The lender email asks
# --------------------------------------------------------------------------------------------- #


def test_the_lender_email_orders_the_appraisers_item_and_names_it_in_the_subject() -> None:
    from app.conditions.library import load_library

    condition = Condition(
        verbatim_text="Final inspection is required to confirm completion per plans and specs.",
        lender_code="1228",
        canonical_type_id="PA-03",
        reading={},
    )
    library_type = load_library().get("PA-03")
    assert library_type is not None
    library_item = library_type.items[0]
    item = ConditionItem(
        key=library_item.key,
        name=library_item.name,
        acceptable=library_item.acceptable,
        performer=Performer.APPRAISER,
        performers=["appraiser"],
        option=PlanOption.ASK_THIRD_PARTY,
        documents=[],
        specifics={},
    )
    lines = lender_lines([(condition, item)], _letter())
    subject, body = render_lender(
        greeting_name="Dana",
        lines=lines,
        letter=_letter(),
        signer="Geet",
        company="MortgageBoss",
        request="final inspection",
    )
    text = _text(body)
    assert subject == f"RIVERA {LOAN} — final inspection request"
    assert "Please order the final inspection — completion report (1004D)" in text
    assert "lender needs" not in text.lower()


def test_a_lender_email_with_several_requests_counts_them() -> None:
    one = _generic("Provide the desk review.", performer=Performer.LENDER)
    two = _generic("Provide the CoC approval.", performer=Performer.LENDER)
    lines = lender_lines([one, two], _letter())
    subject, body = render_lender(
        greeting_name=None, lines=lines, letter=_letter(), signer="S", company="C", request=None
    )
    assert subject == f"RIVERA {LOAN} — 2 requests"
    text = _text(body)
    assert "Please provide — “Provide the desk review”" in text
    assert "lender needs" not in text.lower()


# --------------------------------------------------------------------------------------------- #
# The guard: no placeholder in ANY template
# --------------------------------------------------------------------------------------------- #

#: Every email template in `condition_drafts`. A new `render_*` fails the first test until it is added
#: here AND rendered below: the guard cannot silently cover less than every template.
TEMPLATES = {"render_borrower", "render_party", "render_lender", "render_question"}


def test_the_guard_knows_every_template() -> None:
    found = {
        name
        for name, value in vars(condition_drafts).items()
        if name.startswith("render_") and inspect.isfunction(value)
    }
    assert found == TEMPLATES


def _rendered_with_generic_items() -> dict[str, str]:
    letter = _letter()
    title = _generic("TC: Title to put loan number on every check. Account 99887766.")
    borrower = _generic("Provide a letter explaining the deposit.", performer=Performer.BORROWER)
    lender = _generic("Lender to order the desk review.", performer=Performer.LENDER)
    question_condition, _ = _generic("Possibly a Change of Circumstance is needed.")
    question_condition.reading = {"summary": "Change of circumstance for account 123456789"}
    out: dict[str, str] = {}
    _, out["render_borrower"] = render_borrower(
        first_name="Alex",
        lines=borrower_lines([borrower], letter),
        due=None,
        upload_url=None,
        signer="S",
        company="C",
    )
    _, out["render_party"] = render_party(
        greeting_name=None,
        lines=party_lines([title], letter),
        letter=letter,
        signer="S",
        company="C",
    )
    _, out["render_lender"] = render_lender(
        greeting_name=None,
        lines=lender_lines([lender], letter),
        letter=letter,
        signer="S",
        company="C",
        request=None,
    )
    _, out["render_question"] = render_question(
        condition=question_condition,
        short="",
        greeting_name=None,
        letter=letter,
        signer="S",
        company="C",
    )
    return out


def test_no_template_carries_a_placeholder_or_a_long_digit_run() -> None:
    rendered = _rendered_with_generic_items()
    assert set(rendered) == TEMPLATES
    for name, body in rendered.items():
        text = _text(body).lower()
        for placeholder in PLACEHOLDERS:
            assert placeholder.lower() not in text, (name, placeholder)
        assert not re.search(r"\d{5,}", text.replace(LOAN, "")), (name, text)


def test_the_guard_would_catch_the_placeholder() -> None:
    """The positive control for the guard: the build's own line carried the placeholder."""
    body = "<p>1. <strong>Final inspection</strong> — what the lender's words describe.</p>"
    assert any(p.lower() in _text(body).lower() for p in PLACEHOLDERS)


# --------------------------------------------------------------------------------------------- #
# LF-DH8V end to end: no lender, so every condition is generic
# --------------------------------------------------------------------------------------------- #


async def test_lf_dh8v_drafts_carry_the_lenders_words_and_ask_the_lender(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.models.communication import Communication
    from app.models.condition_draft import ConditionDraft, DraftRecipient
    from app.services.condition_plan import build_plan, confirm_round_plan, round_plan_blockers
    from app.services.condition_reading import ConfirmedItem, confirm_reading, read_round
    from sqlalchemy import select
    from tests.conditions.test_condition_plan import _actor
    from tests.conditions.test_lp949_lender_on_the_file import _by_code, _file_without_lender

    monkeypatch.setattr(condition_reading, "complete", fake_complete())
    loan_file, round_ = await _file_without_lender(db_session)
    await read_round(db_session, round_id=round_.id)
    await build_plan(db_session, round_id=round_.id)
    actor = await _actor(db_session, loan_file)
    conditions = await _by_code(db_session, loan_file)
    for code in await round_plan_blockers(db_session, round_=round_):
        condition = conditions[code]
        items = (condition.reading or {}).get("items") or []
        await confirm_reading(
            db_session,
            condition=condition,
            items=[
                ConfirmedItem(
                    name=str(i.get("name") or "Request"),
                    performers=tuple(Performer(p) for p in i.get("performers") or ["borrower"]),
                )
                for i in items
            ]
            or [ConfirmedItem(name="Request", performers=(Performer.BORROWER,))],
            actor_user_id=actor,
        )
    await confirm_round_plan(db_session, round_=round_, actor_user_id=actor)

    rows = (
        await db_session.execute(
            select(ConditionDraft, Communication)
            .join(Communication, Communication.id == ConditionDraft.communication_id)
            .where(ConditionDraft.loan_file_id == loan_file.id)
        )
    ).tuples()
    bodies = {
        draft.recipient: (message.subject or "", _text(message.body or ""))
        for draft, message in rows
    }
    assert set(bodies) == {
        DraftRecipient.LENDER,
        DraftRecipient.BORROWER,
        DraftRecipient.TITLE_ATTORNEY,
        DraftRecipient.LO,
        DraftRecipient.UNDERWRITER,
    }
    for recipient, (_, text) in bodies.items():
        for placeholder in PLACEHOLDERS:
            assert placeholder.lower() not in text.lower(), (recipient, placeholder)
        assert not re.search(r"\d{5,}", text.replace("1226500417", "")), (recipient, text)
    # 6378's instruction reaches the title company in the lender's words (the trial's item 2).
    assert "loan number on all checks" in bodies[DraftRecipient.TITLE_ATTORNEY][1]
    # The lender is asked, and the subject says how many requests (item 3).
    subject, text = bodies[DraftRecipient.LENDER]
    assert subject.endswith("— 1 request")
    assert "Please order" in text and "lender needs" not in text.lower()
    # 7086's two generic items quote one paragraph: it appears once, not twice.
    assert bodies[DraftRecipient.BORROWER][1].count("Short funds to close") == 1
