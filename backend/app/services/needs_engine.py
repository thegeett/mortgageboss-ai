"""Needs-list engine (LP-68) — the DETERMINISTIC backbone of the needs list.

This is the deterministic part (NO AI — the case-by-case intelligence is LP-69). It
provides:

  * **State transitions** — the five-state arrival lifecycle (Pending → Received →
    Verified | Rejected; any → Waived), guarded by a valid-transition map.
  * **Satisfaction-matching** — when a document is processed, advance a matching
    pending need (TYPE-LEVEL: a need for ``needs_type == document_type``). Runs
    **serialized per loan file** (the Celery task in :mod:`app.tasks.needs` wraps
    this with :func:`loan_file_needs_lock`).
  * **The thin deterministic floor** — a small set of near-certain needs seeded from
    the stated MISMO data (employment income → pay stubs + W-2s; a purchase →
    purchase agreement; stated assets → a bank statement). The reliable baseline
    LP-69's AI augments.
  * **Source-agnostic ingestion** — a need carries its ``origin`` (floor / suggestion
    / ai_reasoning). :func:`ingest_suggested_need` turns an LP-67 ``SuggestedNeed``
    into a need (carrying the reasoning + source-finding link); LP-69 proposals
    ingest the same way.

Quantity/recency-granular matching ("2 pay stubs", "within 30 days") is a documented
future refinement; matching is type-level now.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Literal
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis_client
from app.models.base import utcnow
from app.models.borrower import Borrower
from app.models.document import Document, DocumentCategory, DocumentStatus
from app.models.helpers import only_active
from app.models.loan_file import LoanFile, LoanPurpose
from app.models.needs_item import (
    NeedsItem,
    NeedsItemDisposition,
    NeedsItemOrigin,
    NeedsItemStatus,
)
from app.models.stated_financials import StatedAsset, StatedIncomeItem
from app.services.needs_items import create_needs_item

if TYPE_CHECKING:
    from app.services.implications import SuggestedNeed

logger = structlog.get_logger(__name__)


# --------------------------------------------------------------------------- #
# State transitions (deterministic; guarded)
# --------------------------------------------------------------------------- #

# The locked arrival lifecycle + the orthogonal REQUESTED (LP-19). "any → WAIVED",
# plus sensible re-open paths (a rejected need can re-receive; a waived/verified can
# re-open to pending if a processor reverts).
_VALID_TRANSITIONS: dict[NeedsItemStatus, set[NeedsItemStatus]] = {
    NeedsItemStatus.PENDING: {
        NeedsItemStatus.REQUESTED,
        NeedsItemStatus.RECEIVED,
        NeedsItemStatus.WAIVED,
    },
    NeedsItemStatus.REQUESTED: {
        NeedsItemStatus.PENDING,
        NeedsItemStatus.RECEIVED,
        NeedsItemStatus.WAIVED,
    },
    NeedsItemStatus.RECEIVED: {
        NeedsItemStatus.VERIFIED,
        NeedsItemStatus.REJECTED,
        NeedsItemStatus.WAIVED,
    },
    NeedsItemStatus.VERIFIED: {NeedsItemStatus.PENDING, NeedsItemStatus.WAIVED},
    NeedsItemStatus.REJECTED: {
        NeedsItemStatus.PENDING,
        NeedsItemStatus.RECEIVED,
        NeedsItemStatus.WAIVED,
    },
    NeedsItemStatus.WAIVED: {NeedsItemStatus.PENDING},
}


class InvalidNeedTransition(ValueError):
    """Raised when a needs-item state transition is not allowed (guarded)."""


async def transition_need(
    db: AsyncSession,
    *,
    need: NeedsItem,
    to_state: NeedsItemStatus,
    document_id: UUID | None = None,
    reason: str | None = None,
) -> NeedsItem:
    """Move a need to ``to_state`` if the transition is valid (else raise).

    Side effects per target state: RECEIVED links the arriving document; VERIFIED
    stamps ``satisfied_at``; REJECTED/WAIVED record the ``reason`` (WAIVED also sets
    the disposition). Deterministic. Uses ``flush`` (the caller owns the transaction).
    """
    if to_state != need.status and to_state not in _VALID_TRANSITIONS.get(need.status, set()):
        raise InvalidNeedTransition(f"{need.status} -> {to_state} is not a valid transition")

    need.status = to_state
    if to_state is NeedsItemStatus.RECEIVED and document_id is not None:
        need.satisfied_by_document_id = document_id
    if to_state is NeedsItemStatus.VERIFIED:
        need.satisfied_at = utcnow()
    if to_state is NeedsItemStatus.REJECTED:
        need.reason = reason
    if to_state is NeedsItemStatus.WAIVED:
        need.reason = reason
        need.disposition = NeedsItemDisposition.WAIVED
    await db.flush()
    return need


async def waive_need(db: AsyncSession, *, need: NeedsItem, reason: str | None = None) -> NeedsItem:
    """Processor action: waive a need (any state → WAIVED), with a reason."""
    return await transition_need(db, need=need, to_state=NeedsItemStatus.WAIVED, reason=reason)


async def record_need_correction(
    db: AsyncSession,
    *,
    need: NeedsItem,
    action: Literal["confirm", "dismiss", "adjust"],
    note: str | None = None,
) -> NeedsItem:
    """Capture a processor's disposition of an (AI-)proposed need — the LP-69 signal.

    The disposition is recorded **on the need** (the captured signal): ``confirm`` /
    ``adjust`` → ``CONFIRMED`` (a real need); ``dismiss`` → ``DISMISSED`` + the need is
    waived (not a real need). The simple V1 *use* of this signal: the AI reasoning
    folds existing needs (incl. dismissed) into "already covered", so a dismissed
    proposal is not re-proposed. A richer corrections store + a full learning loop is
    a documented future evolution. The processor's confirm/adjust/dismiss UI is LP-70;
    this is the capture it calls. Uses ``flush``.
    """
    if action == "dismiss":
        # Dismissed = not a real need for this file → take it out of the open set,
        # then mark the disposition DISMISSED (more specific than the WAIVED the
        # transition sets).
        if need.status is not NeedsItemStatus.WAIVED:
            await transition_need(db, need=need, to_state=NeedsItemStatus.WAIVED, reason=note)
        need.disposition = NeedsItemDisposition.DISMISSED
    else:  # confirm / adjust — the processor kept it
        need.disposition = NeedsItemDisposition.CONFIRMED
    if note is not None:
        need.notes = note
    await db.flush()
    logger.info(
        "needs_item_correction",
        need_id=str(need.id),
        action=action,  # a category, not PII
        origin=need.origin,
    )
    return need


# --------------------------------------------------------------------------- #
# Satisfaction-matching (deterministic, type-level)
# --------------------------------------------------------------------------- #

# A need awaiting a document is in one of these (the orthogonal REQUESTED counts).
_OPEN_STATES = (NeedsItemStatus.PENDING, NeedsItemStatus.REQUESTED)

# HONEST SATISFACTION (LP-108). The matcher can only verify "a document of the right kind is
# present" — NOT that a graded requirement (N accounts / M months / M years) is fully met. So a
# matched document auto-VERIFIES a need ONLY when the need is genuinely satisfied by ONE document
# (SIMPLE-PRESENCE); a GRADED need instead stops at RECEIVED = "documents attached — confirm
# coverage", and the processor confirms the coverage the system cannot yet verify. This prevents a
# DANGEROUS FALSE-GREEN (a 2-month / all-accounts need reading "satisfied" on a single statement).
#
# SIMPLE-PRESENCE = the deliverable is inherently ONE document. GROUNDED STARTER — validate with
# Priya (she confirms which needs are truly one-document-satisfiable). SAFE DEFAULT: anything NOT on
# this list (incl. every AI-proposed need and any unknown type) is treated as GRADED — under-claiming
# (an extra confirm click) is a mild annoyance; over-claiming (a false-green) is the dangerous failure.
_SIMPLE_PRESENCE_NEEDS_TYPES: frozenset[str] = frozenset(
    {
        "drivers_license",
        "purchase_agreement",
        "gift_letter",
        "letter_of_explanation",
        "homeowners_insurance",
        "title_commitment",
        "appraisal",
        "verification_of_employment",
        "payoff_statement",
        "existing_mortgage_statement",
    }
)

# Umbrella / semantic need types (typically AI-proposed) that name a CATEGORY of documents rather
# than one concrete document type — so they can't match a document by ``needs_type == document_type``.
# They match any document in the mapped category instead (a coarse, category-level match — NOT the
# account-level coverage matching of the V2 "Option A"). GROUNDED STARTER — validate with Priya.
_UMBRELLA_NEED_CATEGORY: dict[str, DocumentCategory] = {
    "asset_statement": DocumentCategory.ASSETS,
    "income_document": DocumentCategory.INCOME_EMPLOYMENT,
}


def is_simple_presence_need(need: NeedsItem) -> bool:
    """Whether ONE document is the whole requirement (LP-108). Safe default: graded (False)."""
    return (need.needs_type or "") in _SIMPLE_PRESENCE_NEEDS_TYPES


def needs_coverage_confirmation(need: NeedsItem) -> bool:
    """Whether the need is GRADED — a matched document is "attached, confirm coverage", not verified."""
    return not is_simple_presence_need(need)


def documents_matching_need(need: NeedsItem, documents: list[Document]) -> list[Document]:
    """All COMPLETED documents on the file that match a need's criteria (LP-109, derive-on-read).

    Reuses the SAME trivial-equality criteria the matcher uses (``document_type == needs_type``, or
    the umbrella need's category == the document's category) — computed at DISPLAY time over the
    documents already stored, with NO schema/matcher change. Delivers LP-108's "show the matched
    documents": a graded need shows the full evidence set (not just the single stored trigger), so
    the processor can confirm coverage against it.

    The set is intentionally COARSE / over-inclusive for umbrella needs (e.g. an ``asset_statement``
    need includes every ASSETS-category document, even an earnest-money withdrawal) — that is exactly
    the "confirm coverage" honesty level: the system surfaces every candidate; the processor curates
    which actually count. Precise, curated, persisted per-need sets are the V2 coverage grid (Option A).
    """
    needs_type = need.needs_type or ""
    umbrella_category = _UMBRELLA_NEED_CATEGORY.get(needs_type)
    return [
        d
        for d in documents
        if d.status is DocumentStatus.COMPLETED
        and (
            d.document_type == needs_type
            or (umbrella_category is not None and d.category is umbrella_category)
        )
    ]


async def apply_document_to_needs(db: AsyncSession, document: Document) -> NeedsItem | None:
    """Advance the matching pending need for a just-processed document (LP-68).

    TYPE-LEVEL: finds the oldest open need on the document's loan file whose
    ``needs_type`` equals the document's ``document_type``, and advances it
    Received → Verified (the document passed — terminal ``COMPLETED``) | Rejected
    (it failed — ``NEEDS_REVIEW`` / ``FAILED``). Deterministic; no AI. No matching
    need (or no type) → no-op. **Runs serialized per loan file** (see
    :mod:`app.tasks.needs`), so concurrent arrivals never race on the shared state.
    """
    if not document.document_type:
        return None
    # Match by needs_type == document_type (the concrete case), OR — for an umbrella need naming a
    # CATEGORY of documents (e.g. "asset_statement") — by the document's category. Coarse, not
    # account-level (LP-108).
    umbrella_types = [t for t, c in _UMBRELLA_NEED_CATEGORY.items() if c == document.category]
    stmt = (
        select(NeedsItem)
        .where(
            NeedsItem.loan_file_id == document.loan_file_id,
            NeedsItem.needs_type.in_([document.document_type, *umbrella_types]),
            NeedsItem.status.in_(_OPEN_STATES),
        )
        .order_by(NeedsItem.created_at)
        .limit(1)
    )
    need = await db.scalar(only_active(stmt, NeedsItem))
    if need is None:
        return None

    await transition_need(db, need=need, to_state=NeedsItemStatus.RECEIVED, document_id=document.id)
    if document.status is not DocumentStatus.COMPLETED:
        # NEEDS_REVIEW / FAILED — a document arrived but did not pass.
        await transition_need(
            db,
            need=need,
            to_state=NeedsItemStatus.REJECTED,
            reason=f"A document arrived but did not pass processing ({document.status.value}).",
        )
    elif is_simple_presence_need(need):
        # SIMPLE-PRESENCE (LP-108): one document IS the requirement → the match is the verification.
        await transition_need(db, need=need, to_state=NeedsItemStatus.VERIFIED)
    else:
        # GRADED (LP-108): stop at RECEIVED = "documents attached — confirm coverage". The system
        # verified a document is present, NOT that the full requirement (all accounts/months/years)
        # is met — the processor confirms that coverage (never a false-green). Stays RECEIVED.
        logger.info("needs_item_attached_confirm_coverage", need_id=str(need.id))
    logger.info(
        "needs_item_advanced",
        need_id=str(need.id),
        document_id=str(document.id),
        new_status=need.status,
    )
    return need


async def confirm_need_coverage(db: AsyncSession, *, need: NeedsItem) -> NeedsItem:
    """The processor confirms a graded need's coverage (LP-108): RECEIVED → VERIFIED.

    The honest counterpart to auto-verify: a matched document put the need in RECEIVED ("documents
    attached — confirm coverage"); the processor, having judged the full coverage the system cannot
    (all accounts / months / years present), confirms it. Uses the guarded transition (a no-op-safe
    move only from RECEIVED). Uses ``flush``; the caller owns the transaction.
    """
    return await transition_need(db, need=need, to_state=NeedsItemStatus.VERIFIED)


async def reopen_needs_satisfied_by(db: AsyncSession, *, document_id: UUID) -> list[NeedsItem]:
    """Re-open any needs a (now-superseded) document had satisfied (LP-71 replace).

    When a document is explicitly replaced, the need it fulfilled must re-evaluate
    against the CURRENT version: this resets such needs to ``PENDING`` and clears the
    satisfying link, so when the replacement document finishes processing,
    :func:`apply_document_to_needs` re-satisfies the need with the new current document.
    Sets the fields directly (a deliberate reset, not a guarded lifecycle move). Uses
    ``flush``; the caller owns the transaction (and re-evaluation is serialized per
    file via the replacement document's pipeline).
    """
    stmt = select(NeedsItem).where(NeedsItem.satisfied_by_document_id == document_id)
    needs = list((await db.scalars(only_active(stmt, NeedsItem))).all())
    for need in needs:
        need.status = NeedsItemStatus.PENDING
        need.satisfied_by_document_id = None
        need.satisfied_at = None
    if needs:
        await db.flush()
    return needs


# --------------------------------------------------------------------------- #
# The thin deterministic floor (from the stated MISMO data)
# --------------------------------------------------------------------------- #


async def _has_stated_employment_income(db: AsyncSession, loan_file_id: UUID) -> bool:
    """Any borrower on the file with a stated employment-income item."""
    stmt = (
        select(StatedIncomeItem.id)
        .join(Borrower, StatedIncomeItem.borrower_id == Borrower.id)
        .where(Borrower.loan_file_id == loan_file_id, StatedIncomeItem.employment_income.is_(True))
        .limit(1)
    )
    return await db.scalar(only_active(only_active(stmt, StatedIncomeItem), Borrower)) is not None


async def _has_stated_assets(db: AsyncSession, loan_file_id: UUID) -> bool:
    stmt = select(StatedAsset.id).where(StatedAsset.loan_file_id == loan_file_id).limit(1)
    return await db.scalar(only_active(stmt, StatedAsset)) is not None


async def _active_borrowers(db: AsyncSession, loan_file_id: UUID) -> list[Borrower]:
    """The file's active borrowers, ordered (primary first by position).

    Queried (not via ``loan_file.borrowers``) so it's safe in the async import path
    where the relationship isn't eager-loaded; the rows are visible post-flush (LP-71.5).
    """
    stmt = (
        select(Borrower)
        .where(Borrower.loan_file_id == loan_file_id)
        .order_by(Borrower.borrower_position)
    )
    return list((await db.scalars(only_active(stmt, Borrower))).all())


# Universal floor needs — required on EVERY file regardless of the borrower's
# situation (so they belong in the deterministic floor, NOT LP-69's situation-specific
# reasoning, which may under-propose an "obvious" universal need). Each entry is
# (needs_type, title, category). **Refine the full list with Priya** — the borrower ID
# is the first/clearest universal need; she'll likely confirm others. To extend:
#   * a PER-BORROWER universal need (one per borrower) → add to ``_PER_BORROWER_UNIVERSAL``
#   * a PER-FILE universal need (one per file) → add to ``_PER_FILE_UNIVERSAL``
# (e.g. a credit authorization or certain initial disclosures, pending Priya's input).
_PER_BORROWER_UNIVERSAL: list[tuple[str, str, DocumentCategory]] = [
    ("drivers_license", "Government ID", DocumentCategory.BORROWER_INFO),
]
_PER_FILE_UNIVERSAL: list[tuple[str, str, DocumentCategory]] = []


async def seed_floor_needs(db: AsyncSession, loan_file: LoanFile) -> list[NeedsItem]:
    """Seed the THIN deterministic floor of near-certain needs.

    Two parts: **universal needs** (always required on every file — a Government ID
    per borrower; refine the full list with Priya, see ``_PER_BORROWER_UNIVERSAL`` /
    ``_PER_FILE_UNIVERSAL``) and **conditional rules** from the stated data
    (employment income → pay stubs + W-2; a purchase → purchase agreement; stated
    assets → bank statements). Universal needs live in the floor — NOT LP-69's AI
    reasoning — precisely because they're not distinctive: the AI surfaces what's
    *special* about a file, so it may under-propose an obvious always-true need.

    Idempotent: if the file already has floor needs, this is a no-op (re-importing a
    MISMO file won't duplicate). The floor is intentionally thin — the bulk of the
    intelligence is LP-69's AI reasoning, which augments this baseline. Floor needs
    are ``origin=FLOOR`` and ``disposition=CONFIRMED`` (near-certain). Uses ``flush``.

    Flushes FIRST so the stated-data rules see the caller's just-added rows: the
    session runs ``autoflush=False`` (ADR), so ``StatedIncomeItem`` / ``StatedAsset``
    rows that a caller ``db.add``-ed but hasn't flushed are invisible to the SELECTs
    in :func:`_has_stated_employment_income` / :func:`_has_stated_assets`. Without
    this flush the employment (→ pay stubs + W-2) and asset (→ bank statements) rules
    silently miss the data and only the purchase rule (in-memory ``loan_purpose``)
    fires (LP-71.5).
    """
    await db.flush()
    existing = await db.scalar(
        only_active(
            select(NeedsItem.id)
            .where(
                NeedsItem.loan_file_id == loan_file.id,
                NeedsItem.origin == NeedsItemOrigin.FLOOR,
            )
            .limit(1),
            NeedsItem,
        )
    )
    if existing is not None:
        return []  # already seeded

    created: list[NeedsItem] = []

    # --- UNIVERSAL NEEDS (always required, every file — deterministic, NOT AI) ----
    # Per-borrower universals (a Government ID for EACH borrower — co-borrowers each
    # need their own), then per-file universals. See ``_PER_BORROWER_UNIVERSAL`` /
    # ``_PER_FILE_UNIVERSAL`` above (extensible; refine the full list with Priya).
    for borrower in await _active_borrowers(db, loan_file.id):
        # Identify which borrower each ID is for (name in the title + the borrower link).
        name = borrower.full_name.strip() or f"Borrower {borrower.borrower_position}"
        for needs_type, title, category in _PER_BORROWER_UNIVERSAL:
            created.append(
                await create_needs_item(
                    db,
                    loan_file_id=loan_file.id,
                    title=f"{title} — {name}",
                    needs_type=needs_type,
                    category=category,
                    borrower_id=borrower.id,
                    origin=NeedsItemOrigin.FLOOR,
                    disposition=NeedsItemDisposition.CONFIRMED,
                    # LP-110: the deterministic source — the rule + the borrower it fired on.
                    source_facts=[
                        {
                            "kind": "rule",
                            "label": f"Every borrower must provide a government ID — {name}",
                        }
                    ],
                )
            )
    for needs_type, title, category in _PER_FILE_UNIVERSAL:
        created.append(
            await create_needs_item(
                db,
                loan_file_id=loan_file.id,
                title=title,
                needs_type=needs_type,
                category=category,
                origin=NeedsItemOrigin.FLOOR,
                disposition=NeedsItemDisposition.CONFIRMED,
                source_facts=[{"kind": "rule", "label": "Required on every loan file"}],
            )
        )

    # --- CONDITIONAL FLOOR RULES (situation-dependent, but still deterministic) ---
    # Each spec carries its DETERMINISTIC source (LP-110): the exact stated data the rule fired on,
    # so the need reads "Required because — {data}" (certain), grounded to the imported record.
    specs: list[tuple[str, str, DocumentCategory, list[dict[str, str]]]] = []
    if await _has_stated_employment_income(db, loan_file.id):
        income_src = [{"kind": "income", "label": "Employment income is stated on the application"}]
        specs.append(
            ("pay_stub", "Recent pay stubs", DocumentCategory.INCOME_EMPLOYMENT, income_src)
        )
        specs.append(
            ("w2", "W-2 (most recent year)", DocumentCategory.INCOME_EMPLOYMENT, income_src)
        )
    if loan_file.loan_purpose is LoanPurpose.PURCHASE:
        specs.append(
            (
                "purchase_agreement",
                "Purchase agreement",
                DocumentCategory.PROPERTY,
                [{"kind": "mismo_field", "label": "Loan purpose is Purchase"}],
            )
        )
    elif loan_file.loan_purpose is LoanPurpose.REFINANCE:
        # The refi analog of the purchase agreement (LP-100): a refinance needs the existing
        # mortgage statement + a payoff statement (the current lien being refinanced). GROUNDED
        # STARTER — validate-with-Priya (the exact refi need-set; subordination for a 2nd lien is
        # a possible add, flagged not built here).
        refi_src = [{"kind": "mismo_field", "label": "Loan purpose is Refinance"}]
        specs.append(
            (
                "existing_mortgage_statement",
                "Existing mortgage statement",
                DocumentCategory.PROPERTY,
                refi_src,
            )
        )
        specs.append(("payoff_statement", "Payoff statement", DocumentCategory.PROPERTY, refi_src))
    if await _has_stated_assets(db, loan_file.id):
        specs.append(
            (
                "bank_statement",
                "Bank statements",
                DocumentCategory.ASSETS,
                [{"kind": "asset", "label": "Assets are stated on the application"}],
            )
        )

    for needs_type, title, category, source_facts in specs:
        created.append(
            await create_needs_item(
                db,
                loan_file_id=loan_file.id,
                title=title,
                needs_type=needs_type,
                category=category,
                origin=NeedsItemOrigin.FLOOR,
                disposition=NeedsItemDisposition.CONFIRMED,
                source_facts=list(source_facts),
            )
        )

    if created:
        logger.info("needs_floor_seeded", loan_file_id=str(loan_file.id), count=len(created))
    return created


# --------------------------------------------------------------------------- #
# Source-agnostic ingestion (LP-67 suggestions; LP-69 proposals ingest the same way)
# --------------------------------------------------------------------------- #


async def ingest_suggested_need(
    db: AsyncSession, *, loan_file_id: UUID, suggested: "SuggestedNeed"
) -> NeedsItem | None:
    """Turn an LP-67 ``SuggestedNeed`` into a needs item (source-agnostic, LP-68).

    Carries the reasoning + the source-finding link (traceable). ``origin=SUGGESTION``,
    ``disposition=PROPOSED`` (the processor confirms in LP-70). Idempotent per source
    finding: re-ingesting the same finding's suggestion is a no-op. Uses ``flush``.
    """
    if suggested.source_finding_id is not None:
        already = await db.scalar(
            only_active(
                select(NeedsItem.id)
                .where(
                    NeedsItem.loan_file_id == loan_file_id,
                    NeedsItem.source_finding_id == suggested.source_finding_id,
                )
                .limit(1),
                NeedsItem,
            )
        )
        if already is not None:
            return None
    return await create_needs_item(
        db,
        loan_file_id=loan_file_id,
        title=suggested.need_description,
        needs_type=suggested.need_type,
        origin=NeedsItemOrigin.SUGGESTION,
        disposition=NeedsItemDisposition.PROPOSED,
        reasoning=suggested.reasoning,
        source_finding_id=suggested.source_finding_id,
    )


# --------------------------------------------------------------------------- #
# Per-file serialization — the race fix (Redis lock, keyed on the loan file)
# --------------------------------------------------------------------------- #


@asynccontextmanager
async def loan_file_needs_lock(
    loan_file_id: UUID | str, *, timeout: int = 30, blocking_timeout: int = 30
) -> AsyncIterator[bool]:
    """A Redis lock keyed on the loan file — serializes needs updates PER FILE.

    Concurrent document arrivals for the SAME file acquire this one at a time (no
    race on the shared needs state); DIFFERENT files use different keys → parallel.
    Yields whether the lock was acquired (the caller proceeds either way — a missed
    lock just means another worker is applying, and a re-run is safe). ``timeout``
    auto-expires a held lock so a crashed worker never deadlocks the file.
    """
    client = get_redis_client()
    lock = client.lock(
        f"needs-lock:{loan_file_id}", timeout=timeout, blocking_timeout=blocking_timeout
    )
    acquired = await lock.acquire()
    try:
        yield bool(acquired)
    finally:
        if acquired:
            try:
                await lock.release()
            except Exception:  # the lock may have expired (timeout) — never crash on release
                logger.warning("needs_lock_release_failed", loan_file_id=str(loan_file_id))
