"""LP-634 — the composition PASS over the Need List: enrich stored needs, cache, never break one.

Runs AFTER the needs are settled. It reads them, asks a model for the one sentence saying WHY each
document is needed, and writes that sentence to `explanation`. Nothing else is touched: not
`reasoning` (which is this pass's own INPUT), not the title, not the type, not the status, not the
disposition, not the coverage flag. A total failure of this pass leaves a correct Need List reading
exactly as it reads today.

PER NEED, NOT ONE BATCHED CALL — the LP-527 reasoning, unchanged. Batching is cheaper on a cold cache
and worse everywhere else: one changed need would invalidate a whole batch (defeating the cache, which
is the point), one malformed response would cost every need its sentence instead of one, and item 17
of 19 gets less of the model's attention than item 1.

THE FLOOR IS THE REASON THIS EXISTS. Its needs are the deterministic ones — the ones we are surest
about — and they store NO reasoning at all, so LF-AWBB showed six titles above six blank spaces. They
are also the easiest to explain, because their triggers are known: `_FLOOR_TRIGGER` gives each one a
plain sentence, which is both the model's input and the fallback if composition fails. Strictly better
than the blank either way.

bug-008 — AND THE PASS ITSELF CANNOT RAISE, because both of its callers would lose real work if it
did. In `verification_run` it runs inside the savepoint that wraps the whole needs sync, so a raise
discards the floor seed, the re-match, the finding seed, the repair and the coverage flag; in
`tasks/needs.py` it runs immediately before `db.commit()` under a `task_session` that does not commit
on an exception, so a raise discards the LP-68 document match and the LP-69 AI needs, retries the whole
task, and on exhaustion shows the processor a terminal AI-needs failure. The docstring below has always
promised "never raises" — it is now enforced, in a savepoint of its own, the way `compose_findings` is.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.needs_prose import NeedFacts, compose, rejection_reason
from app.core.config import settings
from app.core.logging import get_logger
from app.models.borrower import Borrower
from app.models.document import Document
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.models.needs_item import NeedsItem, NeedsItemOrigin
from app.models.needs_prose import NeedProse
from app.models.property import Property
from app.models.stated_financials import (
    StatedAsset,
    StatedEmployer,
    StatedIncomeItem,
    StatedLiability,
)
from app.services.needs_engine import OPEN_STATES
from app.verification.rule_engine.reasons import document_label

logger = get_logger(__name__)

# The same bound the finding composer uses: short enough to keep the pass quick, low enough that a
# large file cannot burst into a hundred simultaneous calls and trip a rate limit.
_MAX_CONCURRENT = 8

#: What a FLOOR need is FOR, in one plain clause. The floor is deterministic — each need has a known
#: trigger — so this is derivable without a model, and it is the fallback when composition fails.
#: Keyed on `needs_type`, and it covers the seven `seed_floor_needs` can mint — measured across
#: LF-AWBB, LF-BVFU and LF-ZE9N, where 17 of 17 floor needs store no reasoning at all. An unmapped
#: type falls back to the generic line below, which is still better than the blank shipping today.
_FLOOR_TRIGGER: dict[str, str] = {
    "pay_stub": "the application states employment income, and pay stubs evidence current earnings",
    "w2": "the application states employment income, and the W-2 evidences the prior year of it",
    "bank_statement": (
        "the application states assets for closing costs and reserves, and statements evidence the "
        "balances and where the money came from"
    ),
    "government_id": (
        "every borrower on the loan must present an unexpired government photo ID before closing"
    ),
    "existing_mortgage_statement": (
        "the loan purpose is a refinance, so the file needs the statement for the mortgage being "
        "replaced"
    ),
    "purchase_agreement": (
        "the loan purpose is a purchase, and the sales contract states the price the loan and the "
        "appraisal are measured against"
    ),
    "payoff_statement": (
        "the loan purpose is a refinance, so the existing mortgage is paid off at closing and the file "
        "needs the exact amount due on the closing date"
    ),
}
_GENERIC_FLOOR_TRIGGER = "this document is required on every file of this kind"


def _money(value: Decimal | None) -> str | None:
    return f"${value:,.0f}" if value is not None else None


def _floor_trigger(need: NeedsItem) -> str:
    """The known trigger for a FLOOR need, as a clause. Only ever called for a floor need."""
    return _FLOOR_TRIGGER.get(need.needs_type or "", _GENERIC_FLOOR_TRIGGER)


def _floor_fallback(need: NeedsItem) -> str | None:
    """The stored floor sentence a failed composition falls back to, or None for any other origin.

    bug-008 — CONSTRAINT 3 OF THE COMPOSER'S OWN CONTRACT, which was documented and not built. "It
    falls back to what is stored, which for a floor need is a template floor rather than the blank
    that ships today" was true of nothing: `_FLOOR_TRIGGER` was model INPUT only, so a rejected or
    failed floor composition left `explanation` NULL and the card fell back to `reasoning`, which is
    NULL on every floor need (17 of 17 measured across LF-AWBB, LF-BVFU and LF-ZE9N). The blank this
    ticket exists to remove came back on exactly the needs it exists for.
    """
    if need.origin is not NeedsItemOrigin.FLOOR:
        return None
    clause = _floor_trigger(need)
    return f"{clause[0].upper()}{clause[1:]}."


def _trigger(need: NeedsItem) -> str | None:
    """What produced this need, in whatever register produced it, or None if nothing did.

    A floor need has no stored reasoning at all, which is the defect; the rest carry text written for
    engineers. Turning either into a processor's sentence is the composer's whole job, so both are
    handed over as-is rather than pre-polished here.

    bug-008 — NONE IS AN ANSWER, and the generic floor line is not. It fell through to "this document
    is required on every file of this kind" for ANY need with no stored reasoning, floor or not — so a
    processor-added manual need ("send me the divorce decree") and a `suggestion` need with a null
    reasoning were both handed a fabricated justification as ground truth, and the prompt instructs the
    model to write it confidently. A need nothing recorded a reason for gets no composed reason.

    READS `reasoning`, WRITES `explanation`, and they must stay different columns. The first cut wrote
    the composed sentence back over `reasoning` — which is this function's INPUT, so the cache key
    changed on every run, the model was re-asked every time, and each answer was composed from the
    previous answer rather than from what actually produced the need. Prose drifting a little further
    from the file on every verification, on the page a processor opens first.
    """
    if need.reasoning and need.reasoning.strip():
        return need.reasoning.strip()
    if need.origin is NeedsItemOrigin.FLOOR:
        return _floor_trigger(need)
    return None


@dataclass(frozen=True)
class _FileFacts:
    """The application's stated data, shared by every need's summary on one file."""

    loan: dict[str, str]
    employment: tuple[str, ...]
    income_types: tuple[str, ...]
    liabilities: tuple[str, ...]
    assets: tuple[str, ...]
    documents_on_file: tuple[str, ...]


async def _file_facts(db: AsyncSession, loan_file: LoanFile) -> _FileFacts:
    """The application's own data, in a processor's vocabulary rather than MISMO's.

    This is the half that makes a reason CHECKABLE. "The application states a $438/month lease with
    Ally Financial" can be verified in one glance at the 1003; `Revolving liability` cannot, which is
    why LP-110's source block asked a reader to audit the pipeline instead of the file.
    """
    prop = await db.scalar(
        only_active(select(Property).where(Property.loan_file_id == loan_file.id), Property)
    )
    employers = (
        await db.scalars(
            only_active(
                select(StatedEmployer)
                .join(Borrower, StatedEmployer.borrower_id == Borrower.id)
                .where(Borrower.loan_file_id == loan_file.id),
                StatedEmployer,
            )
        )
    ).all()
    incomes = (
        await db.scalars(
            only_active(
                select(StatedIncomeItem)
                .join(Borrower, StatedIncomeItem.borrower_id == Borrower.id)
                .where(Borrower.loan_file_id == loan_file.id),
                StatedIncomeItem,
            )
        )
    ).all()
    liabilities = (
        await db.scalars(
            only_active(
                select(StatedLiability).where(StatedLiability.loan_file_id == loan_file.id),
                StatedLiability,
            )
        )
    ).all()
    assets = (
        await db.scalars(
            only_active(
                select(StatedAsset).where(StatedAsset.loan_file_id == loan_file.id),
                StatedAsset,
            )
        )
    ).all()
    documents = (
        await db.scalars(
            only_active(select(Document).where(Document.loan_file_id == loan_file.id), Document)
        )
    ).all()

    loan: dict[str, str] = {}
    if loan_file.loan_purpose:
        loan["purpose"] = loan_file.loan_purpose.value.replace("_", " ")
    if loan_file.refinance_type:
        loan["refinance type"] = loan_file.refinance_type.value.replace("_", " ")
    if loan_file.loan_program:
        loan["program"] = loan_file.loan_program.value
    if amount := _money(loan_file.loan_amount):
        loan["loan amount"] = amount
    if prop is not None:
        if prop.occupancy_type:
            loan["occupancy"] = prop.occupancy_type.value.replace("_", " ")
        if value := _money(prop.estimated_value):
            loan["stated property value"] = value

    return _FileFacts(
        loan=loan,
        employment=tuple(
            " — ".join(
                part
                for part in (
                    e.employer_name,
                    "self-employed" if e.self_employed else "W-2 employee",
                    f"since {e.start_date:%B %Y}" if e.start_date else None,
                    "current" if e.is_current else "previous",
                )
                if part
            )
            for e in employers
            if e.employer_name
        ),
        income_types=tuple(sorted({i.income_type for i in incomes if i.income_type})),
        liabilities=tuple(
            " — ".join(
                part
                for part in (
                    liability.holder_name,
                    f"{_money(liability.monthly_payment)}/month"
                    if liability.monthly_payment
                    else None,
                    f"{_money(liability.unpaid_balance)} balance"
                    if liability.unpaid_balance
                    else None,
                    "paid off at closing" if liability.paid_off_at_closing else None,
                )
                if part
            )
            for liability in liabilities
            if liability.holder_name
        ),
        assets=tuple(sorted({a.asset_type for a in assets if a.asset_type})),
        documents_on_file=tuple(
            sorted({document_label(d.document_type) for d in documents if d.document_type})
        ),
    )


# bug-008 — WHICH FACT FAMILIES A NEED'S REASON CAN DRAW ON, by the kind of document it asks for.
#
# The cache key is the hash of what the model was GIVEN, which is right — the same input must return
# the same sentence. The defect was that every need was given the whole file, so any change anywhere
# (a liability edited, a document of a new kind uploaded) re-composed all nineteen needs at once and
# could reword all nineteen. `_run_needs_update` runs on every document arrival, so that is the common
# case, not the rare one, and "a processor re-reading the list sees movement where nothing moved" is
# precisely what the cache is documented to prevent.
#
# Narrowing the KEY alone would be a bug (same key, different input, wrong sentence served), so this
# narrows the INPUT and the key follows. `loan` and `documents_on_file` stay on every need: the purpose
# and program frame every request, and knowing what the file already holds is what stops a reason
# inventing a corpus (LP-597) or asking for something already there.
#
# AN UNKNOWN KIND GETS EVERYTHING. A custom or free-form need has no document kind to reason from, and
# the safe default there is the input this pass shipped with rather than a guess at relevance.
_INCOME_KINDS = frozenset(
    {
        "pay_stub", "w2", "1099", "transcripts_of_1099", "voe", "verbal_voe", "tax_return",
        "business_tax_return", "tax_transcript", "form_1040_personal_tax_transcripts",
        "form_1065_partnership_tax_transcripts", "form_1120_corporate_tax_transcripts",
        "profit_and_loss", "k1_statement", "commission_income_statement", "compensation_statement",
        "employment_offer_letter", "letter_of_explanation_income", "social_security_award_letter",
        "pension_statement", "retirement_income_letter", "retirement_pension_award_letter",
        "disability_award_letter", "disability_income_letter", "child_support_income",
        "alimony_income", "unemployment_income_letter", "rental_income_schedule", "lease_agreement",
        "military_leave_and_earning_statement_les", "cpa_letter", "financial_statements",
    }
)  # fmt: skip
_ASSET_KINDS = frozenset(
    {
        "bank_statement", "brokerage_statement", "gift_letter", "gift_donor_bank_statement",
        "verification_of_deposit", "verification_of_assets", "investment_account",
        "retirement_account", "ira_401k", "money_market_statement", "certificate_of_deposit",
        "crypto_account_statement", "earnest_money_receipt", "emd_withdrawal_proof",
        "sale_of_asset_proof", "letter_of_explanation_asset", "bank_deposit_slip",
    }
)  # fmt: skip
_LIABILITY_KINDS = frozenset(
    {
        "mortgage_statement", "existing_mortgage_statement", "payoff_statement",
        "debt_payoff_statement", "student_loan_statement", "installment_loan_statement",
        "hoa_statement", "verification_of_mortgage", "verification_of_rent",
        "collection_account_letter", "judgment_documentation", "other_property_note",
        "subject_property_note", "credit_report", "credit_supplement", "property_tax_bill",
    }
)  # fmt: skip
_KIND_SCOPED = _INCOME_KINDS | _ASSET_KINDS | _LIABILITY_KINDS


def summarize(need: NeedsItem, file_facts: _FileFacts) -> NeedFacts | None:
    """One need plus the file data its reason may draw on, or None if nothing recorded a reason.

    None is how a need with no trigger is SKIPPED rather than explained from a fabricated one — see
    `_trigger`.
    """
    trigger = _trigger(need)
    if trigger is None:
        return None
    kind = need.needs_type or ""
    unscoped = kind not in _KIND_SCOPED
    return NeedFacts(
        request=need.title,
        document_kind=document_label(need.needs_type) if need.needs_type else None,
        trigger=trigger,
        loan=dict(file_facts.loan),
        employment=file_facts.employment if unscoped or kind in _INCOME_KINDS else (),
        income_types=file_facts.income_types if unscoped or kind in _INCOME_KINDS else (),
        liabilities=file_facts.liabilities if unscoped or kind in _LIABILITY_KINDS else (),
        assets=file_facts.assets if unscoped or kind in _ASSET_KINDS else (),
        documents_on_file=file_facts.documents_on_file,
    )


async def _cached(db: AsyncSession, keys: list[str]) -> dict[str, str]:
    if not keys:
        return {}
    rows = (
        (await db.execute(select(NeedProse).where(NeedProse.fact_hash.in_(keys)))).scalars().all()
    )
    return {row.fact_hash: row.why for row in rows}


async def _store(db: AsyncSession, key: str, why: str) -> None:
    await db.execute(insert(NeedProse).values(fact_hash=key, why=why).on_conflict_do_nothing())


async def compose_needs(db: AsyncSession, *, loan_file_id: UUID) -> int:
    """Write a processor-facing reason onto every open need. Returns how many changed.

    Never raises, and bug-008 made that true rather than merely written down: the body runs in a
    SAVEPOINT of its own, so a DB error inside it rolls back this pass alone instead of poisoning the
    session its callers commit. Both of them lose real work otherwise — the module docstring has the
    two paths. Gated by ``settings.need_prose_enabled``. Uses ``flush``; the caller owns the outer
    transaction.
    """
    if not settings.need_prose_enabled:
        return 0
    try:
        async with db.begin_nested():
            return await _compose_needs(db, loan_file_id=loan_file_id)
    except Exception as exc:
        logger.warning("need_prose_pass_failed", error=type(exc).__name__, detail=str(exc))
        return 0


async def _compose_needs(db: AsyncSession, *, loan_file_id: UUID) -> int:
    """The pass itself. Free to raise; `compose_needs` owns the containment."""
    loan_file = await db.scalar(
        only_active(select(LoanFile).where(LoanFile.id == loan_file_id), LoanFile)
    )
    if loan_file is None:
        return 0
    # bug-008 — OPEN NEEDS ONLY, which is what the docstring above always said. Unfiltered, this
    # loaded every non-deleted need including VERIFIED, WAIVED and RECEIVED ones, so every closed need
    # on a mature file cost a model call on every document arrival and every verification run — to
    # rewrite a sentence under a row nobody is being asked to act on. `needs_engine` scopes its
    # matcher with the same tuple and `flag_covered_needs` filters with `is_flaggable`.
    needs = (
        await db.scalars(
            only_active(
                select(NeedsItem).where(
                    NeedsItem.loan_file_id == loan_file_id,
                    NeedsItem.status.in_(OPEN_STATES),
                ),
                NeedsItem,
            )
        )
    ).all()
    if not needs:
        return 0

    file_facts = await _file_facts(db, loan_file)
    # A need with no recorded trigger is skipped rather than explained from a generic one.
    summaries = {
        need.id: facts for need in needs if (facts := summarize(need, file_facts)) is not None
    }
    keys = {need_id: facts.cache_key() for need_id, facts in summaries.items()}
    cache = await _cached(db, list(dict.fromkeys(keys.values())))

    # A CACHED REASON IS RE-CHECKED — LP-601's lesson. `compose` runs only on a MISS, so a reason
    # stored before a guard existed would be served forever and that guard would never see it.
    for need_id, key in keys.items():
        stored = cache.get(key)
        if stored is not None and (reason := rejection_reason(summaries[need_id], stored)):
            logger.warning("need_prose_cached_rejected", reason=reason)
            cache.pop(key, None)

    misses = [nid for nid, key in keys.items() if key not in cache]
    if misses:
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT)

        async def _one(need_id: UUID) -> tuple[UUID, str | None]:
            async with semaphore:
                return need_id, await compose(summaries[need_id])

        # bug-008 — ONE NEED'S FAILURE COSTS ONE NEED ITS SENTENCE. Without `return_exceptions` the
        # first raise propagates out of the gather AND cancels every other call in flight, so a single
        # unexpected error turned a per-need pass into an all-or-nothing one. `compose` already
        # absorbs `AIClientError`; this is for everything else.
        composed = await asyncio.gather(*(_one(nid) for nid in misses), return_exceptions=True)
        for outcome in composed:
            if isinstance(outcome, BaseException):
                logger.warning("need_prose_compose_failed", error=type(outcome).__name__)
                continue
            need_id, why = outcome
            if why is None:
                continue
            cache[keys[need_id]] = why
            await _store(db, keys[need_id], why)

    changed = 0
    for need in needs:
        # A failed or rejected composition falls back to the stored floor sentence rather than to the
        # blank — constraint 3 of the composer's contract (see `_floor_fallback`).
        why = cache.get(keys.get(need.id, "")) or _floor_fallback(need)
        if why is None or need.explanation == why:
            continue  # rejected, failed with no floor to fall back to, or already saying it
        need.explanation = why
        changed += 1
    if changed:
        await db.flush()
    logger.info(
        "need_prose_pass_done",
        loan_file_id=str(loan_file_id),
        needs=len(needs),
        composed=changed,
        cache_hits=len(summaries) - len(misses),
    )
    return changed


__all__ = ["compose_needs", "summarize"]
