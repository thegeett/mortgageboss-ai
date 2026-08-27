"""LP-633 — letting the reasoner withdraw a proposal. The AI is MOCKED.

LP-632's predicate reaches six of staging's 32 open AI-proposed needs. The rest have nothing to join
against: an appraisal and a title report triggered by a MISMO field, six needs with ``needs_type``
null that no document can clear by any route, and the letter-of-explanation / tax-return rows whose
moot-ness is a reading question rather than a lookup. For those the only thing that can judge the need
stale is the thing that wrote it.

The load-bearing property, pinned here in three ways: **silence is not retraction**. The prompt orders
the model to stay quiet about anything already covered, so omission means "I was told not to restate
it" — reading it as withdrawal would delete every correct need on every re-run.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.models.document import DocumentStatus
from app.models.needs_item import (
    NeedsItemDisposition,
    NeedsItemOrigin,
    NeedsItemStatus,
)
from app.services import needs_ai as needs_ai_module
from app.services.needs_ai import apply_ai_needs
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration import factories


def _mock_ai(monkeypatch: pytest.MonkeyPatch, payload: dict) -> AsyncMock:
    mock = AsyncMock(
        return_value=SimpleNamespace(
            text=json.dumps(payload), input_tokens=500, output_tokens=200, model="m"
        )
    )
    monkeypatch.setattr(needs_ai_module, "complete", mock)
    return mock


async def _file(db: AsyncSession):
    company = await factories.make_company(db, slug="acme")
    return company, await factories.make_loan_file(db, company=company)


async def _ai_need(
    db,
    loan_file,
    *,
    needs_type: str | None = "tax_return",
    origin=NeedsItemOrigin.AI_REASONING,
    disposition=NeedsItemDisposition.PROPOSED,
    status=NeedsItemStatus.PENDING,
):
    need = await factories.make_needs_item(db, loan_file=loan_file, title="Two years of returns")
    need.needs_type = needs_type
    need.origin = origin
    need.disposition = disposition
    need.status = status
    need.reasoning = "Self-employment income is stated."
    await db.flush()
    return need


# --------------------------------------------------------------------------- #
# The retraction itself
# --------------------------------------------------------------------------- #


async def test_a_retraction_flags_the_need_with_its_reason(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The model withdraws its own proposal, and the WHY lands where the processor checks it."""
    _company, loan_file = await _file(db_session)
    need = await _ai_need(db_session, loan_file)
    _mock_ai(
        monkeypatch,
        {
            "needs": [],
            "retract": [
                {
                    "need_id": str(need.id),
                    "why": "The employment record states self_employed: false, so no business "
                    "returns apply.",
                }
            ],
        },
    )

    await apply_ai_needs(db_session, loan_file)
    await db_session.refresh(need)
    assert "self_employed: false" in (need.coverage_note or "")
    assert (
        need.covered_by_document_id is None
    )  # a retraction may rest on an argument, not a document


async def test_a_retraction_is_a_flag_not_a_close(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-388, from the AI side. LP-69's guardrail 2 says the model never self-CONFIRMS a need; the
    closing direction is not safer merely because it removes work rather than creating it."""
    _company, loan_file = await _file(db_session)
    need = await _ai_need(db_session, loan_file)
    _mock_ai(
        monkeypatch,
        {"needs": [], "retract": [{"need_id": str(need.id), "why": "Already documented."}]},
    )

    await apply_ai_needs(db_session, loan_file)
    await db_session.refresh(need)
    assert need.status is NeedsItemStatus.PENDING
    assert need.disposition is NeedsItemDisposition.PROPOSED
    assert need.deleted_at is None


async def test_a_retraction_may_cite_a_document_on_the_file(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Checked against credit-report.pdf" beats an unsourced assertion — which is the whole reason
    LP-633 puts document ids into the context in the first place."""
    company, loan_file = await _file(db_session)
    need = await _ai_need(db_session, loan_file)
    document = await factories.make_document(
        db_session,
        loan_file=loan_file,
        company=company,
        filename="credit-report.pdf",
        document_type="credit_report",
        status=DocumentStatus.COMPLETED,
    )
    _mock_ai(
        monkeypatch,
        {
            "needs": [],
            "retract": [
                {
                    "need_id": str(need.id),
                    "why": "The credit report documents it.",
                    "document_id": str(document.id),
                }
            ],
        },
    )

    await apply_ai_needs(db_session, loan_file)
    await db_session.refresh(need)
    assert need.covered_by_document_id == document.id


async def test_a_document_id_from_another_file_is_not_cited(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wrong id would point the processor's "checked against" line at another file's document. The
    note stands on its own instead — the claim is still visible, its false citation is not."""
    company, loan_file = await _file(db_session)
    other_file = await factories.make_loan_file(db_session, company=company)
    stranger = await factories.make_document(
        db_session, loan_file=other_file, company=company, filename="elsewhere.pdf"
    )
    need = await _ai_need(db_session, loan_file)
    _mock_ai(
        monkeypatch,
        {
            "needs": [],
            "retract": [
                {
                    "need_id": str(need.id),
                    "why": "Covered.",
                    "document_id": str(stranger.id),
                }
            ],
        },
    )

    await apply_ai_needs(db_session, loan_file)
    await db_session.refresh(need)
    assert need.coverage_note == "Covered."
    assert need.covered_by_document_id is None


# --------------------------------------------------------------------------- #
# Silence is not retraction
# --------------------------------------------------------------------------- #


async def test_omitting_a_need_never_withdraws_it(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE LOAD-BEARING PROPERTY. The prompt ORDERS silence about anything already covered, so a
    missing need means "I was told not to restate it" — never "it is no longer needed"."""
    _company, loan_file = await _file(db_session)
    need = await _ai_need(db_session, loan_file)
    _mock_ai(monkeypatch, {"needs": []})  # says nothing at all about the existing need

    await apply_ai_needs(db_session, loan_file)
    await db_session.refresh(need)
    assert need.coverage_note is None
    assert need.status is NeedsItemStatus.PENDING


async def test_a_response_with_no_retract_key_behaves_exactly_as_before(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A model that ignores the new instruction produces the pre-LP-633 behaviour, which is the
    failure mode this feature is designed to have."""
    _company, loan_file = await _file(db_session)
    need = await _ai_need(db_session, loan_file, needs_type="gift_letter")
    _mock_ai(
        monkeypatch,
        {
            "needs": [
                {
                    "need_description": "Purchase agreement",
                    "need_type": "purchase_agreement",
                    "reasoning": "The loan purpose is Purchase.",
                }
            ]
        },
    )

    created = await apply_ai_needs(db_session, loan_file)
    assert [n.needs_type for n in created] == ["purchase_agreement"]
    await db_session.refresh(need)
    assert need.coverage_note is None


async def test_a_retraction_without_a_reason_is_dropped(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mirror of guardrail 1: an unexplained withdrawal cannot be checked, and this flag exists
    to be checked."""
    _company, loan_file = await _file(db_session)
    need = await _ai_need(db_session, loan_file)
    _mock_ai(monkeypatch, {"needs": [], "retract": [{"need_id": str(need.id), "why": "   "}]})

    await apply_ai_needs(db_session, loan_file)
    await db_session.refresh(need)
    assert need.coverage_note is None


async def test_a_retraction_naming_an_unknown_id_is_ignored(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The model is answering about a list it was given; a hallucinated id is not worth failing a
    needs update over."""
    _company, loan_file = await _file(db_session)
    need = await _ai_need(db_session, loan_file)
    _mock_ai(
        monkeypatch,
        {"needs": [], "retract": [{"need_id": str(uuid4()), "why": "Covered elsewhere."}]},
    )

    await apply_ai_needs(db_session, loan_file)
    await db_session.refresh(need)
    assert need.coverage_note is None


# --------------------------------------------------------------------------- #
# Whose row it is
# --------------------------------------------------------------------------- #


async def test_a_confirmed_need_cannot_be_retracted(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A processor confirmed it. A later model run has no business overturning the judgement they
    acted on — the same boundary LP-625 drew for refreshing reasoning."""
    _company, loan_file = await _file(db_session)
    need = await _ai_need(db_session, loan_file, disposition=NeedsItemDisposition.CONFIRMED)
    _mock_ai(
        monkeypatch,
        {"needs": [], "retract": [{"need_id": str(need.id), "why": "I changed my mind."}]},
    )

    await apply_ai_needs(db_session, loan_file)
    await db_session.refresh(need)
    assert need.coverage_note is None


async def test_a_floor_need_cannot_be_retracted(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The floor is deterministic and near-certain. The model does not get to withdraw a requirement
    it did not raise."""
    _company, loan_file = await _file(db_session)
    need = await _ai_need(db_session, loan_file, origin=NeedsItemOrigin.FLOOR)
    _mock_ai(
        monkeypatch,
        {"needs": [], "retract": [{"need_id": str(need.id), "why": "Not needed."}]},
    )

    await apply_ai_needs(db_session, loan_file)
    await db_session.refresh(need)
    assert need.coverage_note is None


async def test_a_need_with_a_document_attached_cannot_be_retracted(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RECEIVED means the borrower already sent something. Withdrawing it mid-review would tell the
    processor to drop a requirement whose evidence is sitting in the file."""
    _company, loan_file = await _file(db_session)
    need = await _ai_need(db_session, loan_file, status=NeedsItemStatus.RECEIVED)
    _mock_ai(
        monkeypatch,
        {"needs": [], "retract": [{"need_id": str(need.id), "why": "Covered."}]},
    )

    await apply_ai_needs(db_session, loan_file)
    await db_session.refresh(need)
    assert need.coverage_note is None


# --------------------------------------------------------------------------- #
# The self-contradiction case
# --------------------------------------------------------------------------- #


async def test_retracting_and_re_proposing_the_same_need_keeps_the_ask(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A model contradicting itself in one response resolves toward KEEPING the need, because that is
    the direction that cannot lose a document.

    The flag must not land at all. Leaving it would put "the file may already answer this" on a row the
    SAME run argued for — two opposite things said at once, and the processor left to guess which the
    system meant."""
    _company, loan_file = await _file(db_session)
    need = await _ai_need(db_session, loan_file, needs_type="tax_return")
    _mock_ai(
        monkeypatch,
        {
            "needs": [
                {
                    "need_description": "Two years of tax returns",
                    "need_type": "tax_return",
                    "reasoning": "Self-employment income is stated on the application.",
                }
            ],
            "retract": [{"need_id": str(need.id), "why": "Actually covered."}],
        },
    )

    await apply_ai_needs(db_session, loan_file)
    await db_session.refresh(need)
    assert need.status is NeedsItemStatus.PENDING
    assert need.coverage_note is None, "the ask wins; no contradictory flag is left behind"
    assert "Self-employment income is stated" in (need.reasoning or "")


# --------------------------------------------------------------------------- #
# The context the model needs to judge
# --------------------------------------------------------------------------- #


async def test_the_context_carries_what_a_withdrawal_rests_on(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A model cannot sensibly judge whether to withdraw a claim it cannot read. The context sends the
    id it must name, the reasoning it would be overturning, and whose row it is."""
    from app.services.needs_ai import assemble_file_context

    company, loan_file = await _file(db_session)
    need = await _ai_need(db_session, loan_file)
    document = await factories.make_document(
        db_session, loan_file=loan_file, company=company, document_type="w2"
    )

    context = await assemble_file_context(db_session, loan_file)
    entry = next(e for e in context.existing_needs if e["id"] == str(need.id))
    assert entry["origin"] == "ai_reasoning"
    assert entry["disposition"] == "proposed"
    assert "Self-employment income is stated" in entry["reasoning"]
    assert any(d["id"] == str(document.id) for d in context.documents_present)


async def test_an_untyped_need_re_proposed_by_wording_is_not_retracted(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An untyped need collides with a proposal only by wording — the six untyped rows on staging are
    exactly the population LP-633 exists for, so the contradiction guard has to reach them too."""
    _company, loan_file = await _file(db_session)
    need = await _ai_need(db_session, loan_file, needs_type=None)
    _mock_ai(
        monkeypatch,
        {
            "needs": [
                {
                    "need_description": "Two years of returns",  # the need's own title
                    "need_type": None,
                    "reasoning": "Self-employment income is stated on the application.",
                }
            ],
            "retract": [{"need_id": str(need.id), "why": "Actually covered."}],
        },
    )

    await apply_ai_needs(db_session, loan_file)
    await db_session.refresh(need)
    assert need.coverage_note is None


async def test_an_aliased_re_proposal_still_blocks_its_retraction(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REVIEW REGRESSION. The STORED type is canonical — `apply_ai_needs` writes
    `canonical_need_type(p.need_type) or p.need_type` — so comparing it against the model's RAW string
    missed every aliased pair. A response proposing `verification_of_employment` while retracting the
    need it created (stored as `voe`) read as no contradiction, and the flag landed on the row that
    same response argued for."""
    _company, loan_file = await _file(db_session)
    need = await _ai_need(db_session, loan_file, needs_type="voe")
    _mock_ai(
        monkeypatch,
        {
            "needs": [
                {
                    "need_description": "A verification of employment",
                    "need_type": "verification_of_employment",  # aliases to the stored `voe`
                    "reasoning": "The borrower's current employment needs verifying.",
                }
            ],
            "retract": [{"need_id": str(need.id), "why": "Actually covered."}],
        },
    )

    await apply_ai_needs(db_session, loan_file)
    await db_session.refresh(need)
    assert need.coverage_note is None, "the ask wins; no contradictory flag is left behind"
