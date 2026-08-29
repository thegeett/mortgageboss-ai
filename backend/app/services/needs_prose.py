"""LP-634 — the composition PASS over the Need List: enrich stored needs, cache, never break one.

Runs AFTER the needs are settled. It reads them, asks a model for the one sentence saying WHY each
document is needed, and writes back only `reasoning`. Nothing else is touched: not the title, not the
type, not the status, not the disposition, not the coverage flag. A total failure of this pass leaves a
correct Need List reading exactly as it reads today.

⚠️ PER NEED, NOT ONE BATCHED CALL — the LP-527 reasoning, unchanged. Batching is cheaper on a cold
cache and worse everywhere else: one changed need would invalidate a whole batch (defeating the cache,
which is the point), one malformed response would cost every need its sentence instead of one, and item
17 of 19 gets less of the model's attention than item 1.

⚠️ THE FLOOR IS THE REASON THIS EXISTS. Its needs are the deterministic ones — the ones we are surest
about — and they store NO reasoning at all, so LF-AWBB showed six titles above six blank spaces. They
are also the easiest to explain, because their triggers are known: `_FLOOR_TRIGGER` gives each one a
plain sentence, which is both the model's input and the fallback if composition fails. Strictly better
than the blank either way.
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


def _trigger(need: NeedsItem) -> str:
    """What produced this need, in whatever register produced it.

    A floor need has no stored reasoning at all, which is the defect; the rest carry text written for
    engineers. Turning either into a processor's sentence is the composer's whole job, so both are
    handed over as-is rather than pre-polished here.

    ⚠️ READS `reasoning`, WRITES `explanation`, and they must stay different columns. The first cut
    wrote the composed sentence back over `reasoning` — which is this function's INPUT, so the cache
    key changed on every run, the model was re-asked every time, and each answer was composed from the
    previous answer rather than from what actually produced the need. Prose drifting a little further
    from the file on every verification, on the page a processor opens first.
    """
    if need.reasoning and need.reasoning.strip():
        return need.reasoning.strip()
    if need.origin is NeedsItemOrigin.FLOOR:
        return _FLOOR_TRIGGER.get(need.needs_type or "", _GENERIC_FLOOR_TRIGGER)
    return _GENERIC_FLOOR_TRIGGER


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


def summarize(need: NeedsItem, file_facts: _FileFacts) -> NeedFacts:
    """One need plus the file's stated data — the ONLY input its reason may draw on."""
    return NeedFacts(
        request=need.title,
        document_kind=document_label(need.needs_type) if need.needs_type else None,
        trigger=_trigger(need),
        loan=dict(file_facts.loan),
        employment=file_facts.employment,
        liabilities=file_facts.liabilities,
        assets=file_facts.assets,
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

    Never raises: a composition pass that fails must not fail the needs update whose LIST is already
    correct. Gated by ``settings.need_prose_enabled``. Uses ``flush``; the caller owns the transaction.
    """
    if not settings.need_prose_enabled:
        return 0
    loan_file = await db.scalar(
        only_active(select(LoanFile).where(LoanFile.id == loan_file_id), LoanFile)
    )
    if loan_file is None:
        return 0
    needs = (
        await db.scalars(
            only_active(select(NeedsItem).where(NeedsItem.loan_file_id == loan_file_id), NeedsItem)
        )
    ).all()
    if not needs:
        return 0

    file_facts = await _file_facts(db, loan_file)
    summaries = {need.id: summarize(need, file_facts) for need in needs}
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

        for need_id, why in await asyncio.gather(*(_one(nid) for nid in misses)):
            if why is None:
                continue
            cache[keys[need_id]] = why
            await _store(db, keys[need_id], why)

    changed = 0
    for need in needs:
        why = cache.get(keys.get(need.id, ""))
        if why is None or need.explanation == why:
            continue  # rejected, failed, or already saying it
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
