"""LP-634 — the Need List says what to get and not why. The AI is MOCKED.

THE PAGE THIS IS ABOUT. On staging's LF-AWBB the list carried 19 needs and explained almost none of
them: the six FLOOR needs — the deterministic ones, the ones we are surest about — stored no reasoning
at all, the finding-derived ones read "Required by verification rule(s) CL-1, CR-13, DT-7, ID-5, IH-2,
IH-3, PR-6", and the AI ones carried prose followed by a line telling the reader it might be wrong.

These cover the MECHANISM and the guards. Whether a given sentence is a GOOD explanation is a
real-file question, judged by reading the list, not asserted here.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.ai.needs_prose import NeedFacts, machinery_talk_in, rejection_reason
from app.models.needs_item import NeedsItemOrigin
from app.services import needs_prose as service
from app.services.needs_prose import compose_needs
from tests.integration import factories


def _facts(**over) -> NeedFacts:
    base = {
        "request": "Payoff statement",
        "document_kind": "payoff statement",
        "trigger": "the loan purpose is a refinance",
        "loan": {"purpose": "refinance", "loan amount": "$590,000"},
        "liabilities": ("UNITED WHOLESALE MORTGAGE — $3,907/month — $588,224 balance",),
    }
    base.update(over)
    return NeedFacts(**base)  # type: ignore[arg-type]


def _mock_ai(monkeypatch: pytest.MonkeyPatch, why: str) -> AsyncMock:
    mock = AsyncMock(
        return_value=SimpleNamespace(
            text=json.dumps({"why": why}), input_tokens=200, output_tokens=40, model="m"
        )
    )
    monkeypatch.setattr("app.ai.needs_prose.complete", mock)
    return mock


# --------------------------------------------------------------------------- #
# The guards — what may never reach a processor
# --------------------------------------------------------------------------- #


def test_a_rule_id_is_machinery() -> None:
    """ "Required by verification rule(s) CL-1, CR-13, DT-7, ID-5, IH-2, IH-3, PR-6" is what one of
    LF-AWBB's needs says today. A processor does not know what CL-1 is."""
    assert machinery_talk_in("Required by verification rule(s) CL-1, IN-4.")
    assert machinery_talk_in("The system could not verify this.")
    assert machinery_talk_in("The AI identified an undisclosed debt.")
    assert not machinery_talk_in(
        "This refinance pays off the United Wholesale Mortgage loan at closing."
    )


def test_an_invented_number_is_rejected() -> None:
    """The hallucination check, shared with the finding composer rather than re-derived."""
    facts = _facts()
    assert rejection_reason(facts, "The payoff is $588,224 as stated.") is None
    assert rejection_reason(facts, "The borrower earns $84,000 a year.").startswith(
        "unsupported_numbers"
    )


def test_a_long_answer_is_rejected() -> None:
    assert rejection_reason(_facts(), " ".join(["word"] * 61)) == "too_long"


def test_an_identifier_is_rejected() -> None:
    assert (
        rejection_reason(_facts(), "See document 70f2f69d-238e-460e-9243-576db98ba86d.")
        == "identifier"
    )


# --------------------------------------------------------------------------- #
# The pass
# --------------------------------------------------------------------------- #


async def _file_with_need(db, *, origin=NeedsItemOrigin.FLOOR, needs_type="payoff_statement"):
    company = await factories.make_company(db, slug="acme")
    loan_file = await factories.make_loan_file(db, company=company)
    need = await factories.make_needs_item(db, loan_file=loan_file, title="Payoff statement")
    need.origin = origin
    need.needs_type = needs_type
    need.reasoning = None
    await db.flush()
    return loan_file, need


async def test_a_floor_need_stops_showing_a_blank(db_session, monkeypatch) -> None:
    """THE REPORTED DEFECT. The floor needs are the ones we are surest about and they explained
    nothing — six titles above six blank spaces on the page a processor opens first."""
    from app.core.config import settings

    loan_file, need = await _file_with_need(db_session)
    monkeypatch.setattr(settings, "need_prose_enabled", True)
    _mock_ai(
        monkeypatch,
        "This refinance pays off the existing mortgage at closing. The payoff statement gives the "
        "exact amount due on the closing date.",
    )

    assert await compose_needs(db_session, loan_file_id=loan_file.id) == 1
    await db_session.refresh(need)
    assert need.explanation is not None
    assert "payoff statement gives the exact amount" in need.explanation
    assert need.reasoning is None, "the origin's own record is the INPUT and is never overwritten"


async def test_a_rejected_reason_leaves_what_was_stored(db_session, monkeypatch) -> None:
    """Constraint 3 — it falls back rather than blanking. A failure changes prose and nothing else."""
    from app.core.config import settings

    loan_file, need = await _file_with_need(db_session)
    need.reasoning = "the stored sentence"
    await db_session.flush()
    monkeypatch.setattr(settings, "need_prose_enabled", True)
    _mock_ai(monkeypatch, "Required by verification rule(s) CL-1.")  # machinery — rejected twice

    assert await compose_needs(db_session, loan_file_id=loan_file.id) == 0
    await db_session.refresh(need)
    assert need.explanation is None, "nothing to show is better than machinery talk"
    assert need.reasoning == "the stored sentence"


async def test_identical_facts_reuse_the_stored_sentence(db_session, monkeypatch) -> None:
    """Determinism first: without the cache an unchanged need is worded differently every run, and a
    processor re-reading the list sees movement where nothing moved."""
    from app.core.config import settings

    loan_file, need = await _file_with_need(db_session)
    monkeypatch.setattr(settings, "need_prose_enabled", True)
    mock = _mock_ai(monkeypatch, "This refinance pays off the existing mortgage at closing.")

    await compose_needs(db_session, loan_file_id=loan_file.id)
    calls_after_first = mock.await_count
    await db_session.refresh(need)
    first = need.explanation

    assert await compose_needs(db_session, loan_file_id=loan_file.id) == 0  # nothing changed
    assert mock.await_count == calls_after_first, (
        "a second run must not re-ask the model — and it did when the composed sentence was written "
        "back over `reasoning`, the composer's own input, moving the cache key every run"
    )
    await db_session.refresh(need)
    assert need.explanation == first


async def test_the_pass_can_be_turned_off(db_session, monkeypatch) -> None:
    from app.core.config import settings

    loan_file, need = await _file_with_need(db_session)
    monkeypatch.setattr(settings, "need_prose_enabled", False)
    assert await compose_needs(db_session, loan_file_id=loan_file.id) == 0
    await db_session.refresh(need)
    assert need.explanation is None


async def test_the_summary_carries_the_stated_facts(db_session) -> None:
    """The half that makes a reason CHECKABLE. "The application states a $438/month lease with Ally
    Financial" can be verified in one glance at the 1003; `Revolving liability` cannot, which is why
    LP-110's source block asked a reader to audit the pipeline instead of the file."""
    from decimal import Decimal

    from app.models.stated_financials import StatedLiability

    loan_file, _need = await _file_with_need(db_session)
    db_session.add(
        StatedLiability(
            loan_file_id=loan_file.id,
            liability_type="LeasePayment",
            holder_name="ALLY FINANCIAL",
            monthly_payment=Decimal("438"),
        )
    )
    await db_session.flush()

    facts = await service._file_facts(db_session, loan_file)
    assert any("ALLY FINANCIAL" in row and "$438/month" in row for row in facts.liabilities)
