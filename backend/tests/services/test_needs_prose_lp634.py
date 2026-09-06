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
from dataclasses import replace
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


async def test_a_rejected_floor_reason_falls_back_to_the_stored_floor(db_session, monkeypatch):
    """bug-008 — CONSTRAINT 3, WHICH WAS DOCUMENTED AND NOT BUILT. "It falls back to what is stored,
    which for a floor need is a template floor rather than the blank that ships today" was true of
    nothing: `_FLOOR_TRIGGER` was model INPUT only, so a rejected floor composition left `explanation`
    NULL and the card fell back to `reasoning` — NULL on every floor need, 17 of 17 measured. The
    blank came back on exactly the needs this ticket exists for."""
    from app.core.config import settings

    loan_file, need = await _file_with_need(db_session)
    need.reasoning = "the stored sentence"
    await db_session.flush()
    monkeypatch.setattr(settings, "need_prose_enabled", True)
    _mock_ai(monkeypatch, "Required by verification rule(s) CL-1.")  # machinery — rejected twice

    assert await compose_needs(db_session, loan_file_id=loan_file.id) == 1
    await db_session.refresh(need)
    assert need.explanation is not None
    assert "paid off at closing" in need.explanation, "the payoff floor's own stored clause"
    assert need.explanation[0].isupper() and need.explanation.endswith(".")
    assert need.reasoning == "the stored sentence", "the INPUT is never overwritten"


async def test_a_rejected_reason_on_a_non_floor_need_stays_blank(db_session, monkeypatch) -> None:
    """The fallback is the FLOOR's, because the floor is the only origin whose trigger we know without
    a model. Everywhere else the card falls back to `reasoning`, which those origins do store."""
    from app.core.config import settings

    loan_file, need = await _file_with_need(db_session, origin=NeedsItemOrigin.AI_REASONING)
    need.reasoning = "the stored sentence"
    await db_session.flush()
    monkeypatch.setattr(settings, "need_prose_enabled", True)
    _mock_ai(monkeypatch, "Required by verification rule(s) CL-1.")

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


# --------------------------------------------------------------------------- #
# bug-008 — the containment, the scope, and what a reason may draw on
# --------------------------------------------------------------------------- #


async def test_a_failure_in_the_pass_never_reaches_the_caller(db_session, monkeypatch) -> None:
    """BOTH CALLERS LOSE REAL WORK OTHERWISE. In `verification_run` this runs inside the savepoint
    wrapping the whole needs sync; in `tasks/needs.py` it runs immediately before `db.commit()` under a
    `task_session` that does not commit on an exception — so a raise there discards the LP-68 document
    match and the LP-69 AI needs, retries the task, and on exhaustion shows the processor a terminal
    AI-needs failure. A pass whose contract is "a failure changes a sentence" was able to lose a
    document→need match."""
    from app.core.config import settings

    loan_file, need = await _file_with_need(db_session)
    monkeypatch.setattr(settings, "need_prose_enabled", True)

    async def _boom(*_a, **_k):
        raise RuntimeError("the file facts query fell over")

    monkeypatch.setattr(service, "_file_facts", _boom)

    assert await compose_needs(db_session, loan_file_id=loan_file.id) == 0
    # The session is still usable — the savepoint absorbed it — which is the whole property.
    await db_session.flush()
    await db_session.refresh(need)
    assert need.explanation is None


async def test_one_needs_failure_does_not_cancel_the_others(db_session, monkeypatch) -> None:
    """`asyncio.gather` without `return_exceptions` propagates the FIRST raise and cancels every other
    call in flight, turning a per-need pass into an all-or-nothing one."""
    from app.core.config import settings

    company = await factories.make_company(db_session, slug="acme")
    loan_file = await factories.make_loan_file(db_session, company=company)
    needs = []
    for i, kind in enumerate(("payoff_statement", "pay_stub", "government_id")):
        need = await factories.make_needs_item(db_session, loan_file=loan_file, title=f"N{i}")
        need.origin, need.needs_type, need.reasoning = NeedsItemOrigin.FLOOR, kind, None
        needs.append(need)
    await db_session.flush()
    monkeypatch.setattr(settings, "need_prose_enabled", True)

    calls = {"n": 0}

    async def _one_explodes(facts, **_kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("this one blew up")
        return "The application states employment income, so recent earnings must be evidenced."

    monkeypatch.setattr(service, "compose", _one_explodes)

    changed = await compose_needs(db_session, loan_file_id=loan_file.id)
    assert changed == 3, "two composed; the third fell back to its stored floor sentence"
    assert calls["n"] == 3, "every need was still attempted"


async def test_only_open_needs_are_composed(db_session, monkeypatch) -> None:
    """The docstring said "every open need" and the query said every need. A VERIFIED or WAIVED need
    cost a model call on every document arrival and every verification run, to reword a sentence under
    a row nobody is being asked to act on."""
    from app.core.config import settings
    from app.models.needs_item import NeedsItemStatus

    company = await factories.make_company(db_session, slug="acme")
    loan_file = await factories.make_loan_file(db_session, company=company)
    open_need = await factories.make_needs_item(db_session, loan_file=loan_file, title="Open")
    closed = await factories.make_needs_item(db_session, loan_file=loan_file, title="Closed")
    for need in (open_need, closed):
        need.origin, need.needs_type, need.reasoning = NeedsItemOrigin.FLOOR, "pay_stub", None
    open_need.status = NeedsItemStatus.PENDING
    closed.status = NeedsItemStatus.VERIFIED
    await db_session.flush()
    monkeypatch.setattr(settings, "need_prose_enabled", True)
    mock = _mock_ai(
        monkeypatch, "The application states employment income from the stated employer."
    )

    assert await compose_needs(db_session, loan_file_id=loan_file.id) == 1
    assert mock.await_count == 1, "the verified need was never sent"
    await db_session.refresh(closed)
    assert closed.explanation is None


async def test_a_need_with_no_recorded_reason_is_skipped(db_session, monkeypatch) -> None:
    """A FABRICATED JUSTIFICATION IS WORSE THAN A BLANK. The generic floor line — "this document is
    required on every file of this kind" — was handed to the model as ground truth for ANY need with
    no stored reasoning, floor or not. A processor's own one-off ask ("send me the divorce decree")
    would come back explained as a universal requirement, stated confidently."""
    from app.core.config import settings

    loan_file, need = await _file_with_need(
        db_session, origin=NeedsItemOrigin.MANUAL, needs_type="divorce_decree"
    )
    monkeypatch.setattr(settings, "need_prose_enabled", True)
    mock = _mock_ai(monkeypatch, "anything at all")

    assert await compose_needs(db_session, loan_file_id=loan_file.id) == 0
    assert mock.await_count == 0, "nothing recorded a reason, so nothing was asked"
    await db_session.refresh(need)
    assert need.explanation is None


def test_a_reason_draws_only_on_the_facts_its_document_kind_concerns() -> None:
    """bug-008 — the cache key is the hash of what the model was GIVEN, which is right; the defect was
    that every need was given the whole file, so any edit anywhere re-composed all nineteen needs at
    once and could reword all nineteen. `_run_needs_update` runs on every document arrival, so that is
    the common case."""
    facts = service._FileFacts(
        loan={"purpose": "refinance"},
        employment=("Amazon Com Services LLC — W-2 employee",),
        income_types=("Base",),
        liabilities=("UNITED WHOLESALE MORTGAGE — $3,907/month",),
        assets=("checking",),
        documents_on_file=("pay stub",),
    )
    need = SimpleNamespace(
        title="Pay stub", needs_type="pay_stub", origin=NeedsItemOrigin.FLOOR, reasoning=None
    )

    summary = service.summarize(need, facts)  # type: ignore[arg-type]
    assert summary is not None
    assert summary.employment and summary.income_types, "an income document's own families"
    assert summary.liabilities == () and summary.assets == ()
    assert summary.loan and summary.documents_on_file, "always: they frame every request"

    # An edit to a family this need cannot draw on leaves its cached sentence alone.
    moved = service.summarize(need, replace(facts, liabilities=("A DIFFERENT CREDITOR",)))  # type: ignore[arg-type]
    assert moved is not None and moved.cache_key() == summary.cache_key()


def test_an_unknown_document_kind_still_gets_everything() -> None:
    """A custom or free-form need has no kind to reason from, and the safe default there is the input
    this pass shipped with rather than a guess at relevance."""
    facts = service._FileFacts(
        loan={"purpose": "purchase"},
        employment=("Acme",),
        income_types=("Base",),
        liabilities=("A creditor",),
        assets=("checking",),
        documents_on_file=(),
    )
    need = SimpleNamespace(
        title="Something unusual",
        needs_type="custom",
        origin=NeedsItemOrigin.AI_REASONING,
        reasoning="the model's own earlier prose",
    )

    summary = service.summarize(need, facts)  # type: ignore[arg-type]
    assert summary is not None
    assert summary.employment and summary.liabilities and summary.assets and summary.income_types


# --------------------------------------------------------------------------- #
# bug-008 — the guards rejected sentences a processor wants, and licensed ones they must not read
# --------------------------------------------------------------------------- #


def test_a_policy_form_code_is_not_a_rule_id() -> None:
    """`[A-Z]{2}-\\d{1,3}` matched mortgage form names as well as rule ids. `HO-6` is a unit owner's
    walls-in policy (`specs/IH-7.yaml`, `classification_prompt.py`) and `HO-3` a homeowner's, so the
    one sentence a condo hazard-insurance need most wants to say was rejected as machinery talk,
    retried, rejected again, and dropped — leaving the need blank."""
    assert not machinery_talk_in(
        "The project's master policy does not cover the unit interior; an HO-6 walls-in policy does."
    )
    assert machinery_talk_in("Required by verification rule(s) CL-1."), "a real rule id still is"
    assert machinery_talk_in("IH-7 asked for this."), "and so is one with no lead-in"


def test_two_ordinary_nouns_are_not_machinery() -> None:
    """`origin` and `confidence` were banned as BARE WORDS. "A letter explaining the origin of the
    deposit" is the exact sentence a source-of-funds need wants; it was rejected twice and dropped.
    The finding composer's equivalent list is documented as "NARROW ON PURPOSE — only phrases that
    name the SOFTWARE AS AN ACTOR", and two English nouns are not that."""
    assert not machinery_talk_in("A letter explaining the origin of the deposit.")
    assert not machinery_talk_in("The appraisal states the value with confidence.")
    assert machinery_talk_in("The model returned a low confidence score.")
    assert machinery_talk_in("The need origin is a floor rule.")


def test_a_numeric_document_label_does_not_license_its_digits() -> None:
    """LP-613, BY THE SAME ROUTE, REOPENED BY SHARING THE HELPER. `documents_on_file` holds catalog
    labels and several ARE numbers — `document_label("1099")` is `"1099"` — so a file holding one
    licensed the literal token anywhere in the reason. The finding composer subtracts exactly this
    field and the shared helper dropped the subtraction."""
    holds_one = _facts(documents_on_file=("1099", "pay stub"))
    assert rejection_reason(holds_one, "The borrower has 1099 months of reserves.").startswith(
        "unsupported_numbers"
    )

    # The need whose own document kind IS the 1099 may still name it: `document_kind` is not one of
    # the withdrawn fields, because there the digits are the subject of the sentence.
    asks_for_one = _facts(document_kind="1099", documents_on_file=("pay stub",))
    assert rejection_reason(asks_for_one, "The 1099 shows the non-employee pay stated.") is None


def test_a_rule_id_in_the_trigger_does_not_license_its_number() -> None:
    """A finding-derived need's trigger opens "Required by verification rule(s) CR-13", and those
    numerals rode straight into the allow-list. Only the rule ids are withdrawn, not the whole
    trigger: an AI-reasoned need's trigger carries real amounts, and those are what the reason should
    quote."""
    machinery = _facts(trigger="Required by verification rule(s) CR-13, IN-4.")
    assert rejection_reason(machinery, "The file needs 13 months of statements.").startswith(
        "unsupported_numbers"
    )

    real = _facts(trigger="an unsourced $12,000 deposit landed on 2026-04-02")
    assert rejection_reason(real, "A letter must explain the $12,000 deposit.") is None
