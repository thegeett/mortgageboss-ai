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
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis_client
from app.documents.catalog import CATALOG
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
from app.models.property import OccupancyType, Property
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
    # LP-623 — THE REASON DESCRIBES THE STATE, so leaving it is a lie once the state moves on. It was
    # written on REJECTED/WAIVED and never cleared, so on LF-ABRS a RECEIVED W-2 need read "a w2 is in
    # the file but could not be processed" and a VERIFIED ID need read "a document arrived but did not
    # pass processing" — both beside the good document that had just satisfied them. Cleared on the
    # states that mean the earlier failure no longer holds; REJECTED and WAIVED set it below.
    if to_state in (
        NeedsItemStatus.PENDING,
        NeedsItemStatus.REQUESTED,
        NeedsItemStatus.RECEIVED,
        NeedsItemStatus.VERIFIED,
    ):
        need.reason = None
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

# A need awaiting a document is in one of these (the orthogonal REQUESTED counts). Public because
# the prose pass (LP-634) scopes to the same set: what "open" means is one decision, not two.
#
# LP-623 — REJECTED IS OPEN. It was not, and that stranded a need beside the document that satisfies
# it: LF-ABRS carried two W-2s, one COMPLETED and one NEEDS_REVIEW, and whichever was processed first
# claimed the need. The bad one landed on it, the need went REJECTED, and the good W-2 that followed
# matched nothing — so the list reported "did not pass processing" next to a perfectly usable
# document, and a processor would re-ask the borrower for what they already had.
#
# `_VALID_TRANSITIONS` has always permitted REJECTED -> RECEIVED ("a rejected need can re-receive").
# Only the matcher's own query disagreed.
OPEN_STATES = (
    NeedsItemStatus.PENDING,
    NeedsItemStatus.REQUESTED,
    NeedsItemStatus.REJECTED,
)

# Preference when several needs of one type are open: an UNFILLED need before one a bad document
# already landed on. Without this the plain `created_at` ordering could hand a good document to the
# rejected need and leave a pending one still waiting.
_MATCH_PRIORITY = case(
    (NeedsItem.status == NeedsItemStatus.REJECTED, 1),
    else_=0,
)

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
        "government_id",  # LP-623 — one ID is the whole requirement, whichever kind it is
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

# LP-623 — A NEED ANY ONE OF SEVERAL DOCUMENTS SATISFIES.
#
# "Government ID" is not a driver's licence. LF-ABRS's borrower holds a PERMANENT RESIDENT CARD — an
# unexpired government-issued photo ID — and the need, typed `drivers_license` because that is the one
# slug the floor happened to name, sat REJECTED beside it. The processor is told to chase an ID that
# is already in the file.
#
# NOT AN UMBRELLA CATEGORY, which is the mechanism that already existed and is wrong here: the
# BORROWER_INFO category also holds divorce decrees, marriage certificates, trust agreements and eight
# kinds of letter of explanation, any of which would then "satisfy" an identity requirement. These are
# named ALTERNATIVES — the same shape a rule spec's `requires_documents` group uses, and deliberately
# the same membership as ID-5's, which asks the identity question on the rules side.
_GOVERNMENT_ID_DOCUMENTS = frozenset(
    {
        "drivers_license",
        "passport",
        "government_issued_id",
        "military_id",
        "permanent_resident_card",
    }
)

#: bug-009 REVIEW — the catalog carries TWO interchangeable names for each of these documents, and
#: the classifier's own indicators describe the same paper:
#:
#:   investment_account   "a BROKERAGE or investment account statement showing securities holdings"
#:   brokerage_statement  "a securities BROKERAGE statement listing stocks, bonds, or funds"
#:
#:   retirement_account   "a retirement account statement (401(k), IRA, 403(b))"
#:   ira_401k             "an IRA or 401(k) retirement-account statement — OVERLAPS the generic
#:                         retirement_account" (its own indicator says so)
#:
#: So aliasing the invented name to ONE of each pair clears the need only when the classifier
#: happened to pick that label rather than its twin — a coin flip, failing silently in the
#: direction where a processor chases a document already in the file. That is the LF-ABRS harm
#: `_NEED_ALTERNATIVES` was created for, so it is the mechanism these want, not an alias.
_INVESTMENT_ACCOUNT_DOCUMENTS: frozenset[str] = frozenset(
    {"investment_account", "brokerage_statement"}
)
_RETIREMENT_ACCOUNT_DOCUMENTS: frozenset[str] = frozenset({"retirement_account", "ira_401k"})
#: `pension_statement` is deliberately NOT here: it is INCOME_EMPLOYMENT, an income stream, not an
#: account balance — a different ask that happens to share the word "retirement".

_NEED_ALTERNATIVES: dict[str, frozenset[str]] = {
    "government_id": _GOVERNMENT_ID_DOCUMENTS,
    # The PRE-LP-623 name for the same need. Every ID need already raised is stored under it, and a
    # stored row cannot be renamed retroactively without touching live files — so the old name keeps
    # working and accepts the same alternatives. New needs are minted as `government_id`.
    "drivers_license": _GOVERNMENT_ID_DOCUMENTS,
    # The invented names, as heads rather than aliases (see above). Stored under their own slug and
    # satisfied by either member, so the need clears whichever of the twin labels the classifier
    # chose.
    "investment_statement": _INVESTMENT_ACCOUNT_DOCUMENTS,
    "retirement_statement": _RETIREMENT_ACCOUNT_DOCUMENTS,
}


# bug-001 — NEED TYPES THAT NAME A DOCUMENT NOBODY CAN UPLOAD.
#
# Satisfaction matches `needs_type == document_type`. These two are declared simple-presence needs —
# ONE document is the whole requirement — but neither string is a document type the classifier can
# produce, and neither is an umbrella. So the need was raised, the processor uploaded exactly the
# right document, and the need stayed pending forever with no way to clear it.
#
# Both were pending on a real file WHILE THE DOCUMENT SAT IN IT: `existing_mortgage_statement` beside
# an extracted `mortgage_statement`, and `verification_of_employment` beside the `voe` slug it means.
#
# ALIASED RATHER THAN RENAMED, deliberately. The needs_type is stored on every row already raised, so
# renaming the constant would leave those rows naming a type nothing matches — the same defect, moved.
# An alias fixes the rows that exist and the ones still to come, and costs one lookup.
_NEED_TYPE_ALIASES: dict[str, str] = {
    "existing_mortgage_statement": "mortgage_statement",
    "verification_of_employment": "voe",
    # bug-009 — LP-69 proposes "title_report"; the catalog carries `title_commitment` and
    # `preliminary_title_report` and not that. So the proposal failed canonicalisation, was stored
    # raw, and could be cleared by no upload — while ID-7 separately raised a `title_commitment`
    # need for the SAME document. LF-AWBB carried both: one row a processor could satisfy and one
    # they could not, for one title search.
    #
    # Aliased to `title_commitment` rather than `preliminary_title_report` because that is what
    # ID-7's own `requires_documents` group names FIRST, and a group's first member is the thing
    # the file asks for.
    "title_report": "title_commitment",
    # bug-009 — the rest of the same family, found by auditing every need type actually on staging
    # against what a document can satisfy rather than waiting for each to be reported. All six were
    # AI-proposed and all six were open, so eight rows across the environment named a document no
    # upload could ever clear. Each maps to the catalog's own name for the SAME document:
    "credit_authorization": "authorization_to_run_credit",
    "installment_statement": "installment_loan_statement",
    "property_tax_statement": "property_tax_bill",
}


#: Need types that are the SAME NEED under different names, mapped to one representative. Distinct
#: from `_NEED_TYPE_ALIASES` (need type -> DOCUMENT type, for matching): this answers "is this need
#: already on the list", which is a different question and was answered wrongly.
_EQUIVALENT_NEED_TYPES: dict[str, str] = {
    "drivers_license": "government_id",
    # bug-009 — the alias above stops the pair FORMING; this collapses the ones already on a file.
    # Both are needed and they answer different questions: `_NEED_TYPE_ALIASES` decides what a new
    # proposal is STORED as, and a stored row cannot be renamed retroactively without touching live
    # files (LP-623's reasoning, unchanged). This map is what `repair_needs_for_file` groups on, so
    # it is what merges LF-AWBB's existing pair. Preventing a defect does not undo it.
    "title_report": "title_commitment",
    # The same six, for the same two reasons: the alias above stops the pair forming, this collapses
    # a pair already on a file.
    "credit_authorization": "authorization_to_run_credit",
    "installment_statement": "installment_loan_statement",
    "investment_statement": "investment_account",
    "retirement_statement": "retirement_account",
    "property_tax_statement": "property_tax_bill",
}


def equivalent_need_type(needs_type: str | None) -> str | None:
    """The one name under which a need is counted as already present (LP-623).

    WHY THIS EXISTS, on a real file. LP-623 renamed the ID need `drivers_license` -> `government_id`
    and kept the old name matchable, which is not the same as keeping it RECOGNISED: `seed_floor_needs`
    compared raw types, found no `government_id`, and minted a SECOND ID need beside the one already
    there. LF-ABRS then showed two rows titled "Government ID — Vidulasrri Muruganandam", one verified
    against the borrower's green card and one rejected against their unreadable licence.

    The same collision was caught on the seeding path before deploy (`verification_of_employment` vs
    `voe`) and fixed there with `canonical_need_type`. The floor asks the same question and was left
    asking it raw.
    """
    if needs_type is None:
        return None
    slug = needs_type.strip().lower()
    return _EQUIVALENT_NEED_TYPES.get(slug, slug)


def satisfiable_need_types() -> list[str]:
    """Every need type an uploaded document can actually satisfy, sorted (bug-009).

    THE ROOT CAUSE THE ALIASES ONLY PATCH. The reasoning prompt used to say "use a concise lowercase
    snake_case need_type when an obvious document type fits" and give four examples, so the model
    invented plausible names for types that do not exist — `title_report`, `credit_card_statement`,
    `investment_statement`, `retirement_statement`, `property_tax_statement`, `credit_authorization`.
    Satisfaction matches ``needs_type == document_type``, so each became a row on a real file that no
    upload could ever clear, and each was found one at a time by someone noticing it.

    The classifier already solved this: its type list is RENDERED FROM THE CATALOG
    (`app.ai.classification_prompt`), so the prompt and the catalog cannot drift. This is the same
    move for the reasoner.

    The four sources are the same four `canonical_need_type` resolves through, in the same order, so
    a type this function offers is a type that function accepts.
    """
    return sorted(
        set(CATALOG)
        | set(_UMBRELLA_NEED_CATEGORY)
        | set(_NEED_ALTERNATIVES)
        | set(_NEED_TYPE_ALIASES)
    )


def _is_unactionable_alias(needs_type: str | None) -> bool:
    """A STORED type that no document can ever match, reachable only through an alias (bug-009).

    Satisfaction matches ``needs_type == document_type`` on the row as stored, so a type the catalog
    does not carry can never be cleared by any upload no matter what the alias map later says —
    aliasing changes what a NEW proposal is stored as, and does not rewrite a row already on a file.

    ``title_report`` is the case: LP-69 proposes it, the catalog defines ``title_commitment`` and
    ``preliminary_title_report`` and not that, so the row sits on the list forever.

    This is the second proof of redundancy the merge can use, alongside "the floor minted it". A row
    that CANNOT be satisfied is not a requirement anyone can act on, so collapsing it into an
    equivalent row that can be is not taking anything away from a processor.
    """
    if not needs_type:
        return False
    slug = needs_type.strip().lower()
    if slug in CATALOG or slug in _UMBRELLA_NEED_CATEGORY or slug in _NEED_ALTERNATIVES:
        return False  # a document can match it directly — not our case
    return slug in _NEED_TYPE_ALIASES


def canonical_need_type(proposed: str | None) -> str | None:
    """A proposed need type resolved to a CATALOGED document type, or None (LP-623).

    Lives HERE, beside ``_NEED_TYPE_ALIASES``, because it is the same question the matcher asks and
    must not be answered twice: a type the catalog does not carry can never match a document, and a
    near-miss the matcher already forgives (``verification_of_employment`` -> ``voe``) should be
    STORED under the name the documents use rather than forgiven again on every read.

    "REACHABLE" IS WIDER THAN THE CATALOG (LP-624). The matcher also reaches the UMBRELLA types
    (`asset_statement`, `income_document` — any document of the right category answers them) and the
    ALTERNATIVE heads (`government_id` — any of a set of equivalents answers it). Neither is in
    `CATALOG`, so both were reported as unreachable: an AI proposal typed `asset_statement` was logged
    as `ai_need_without_matchable_type`, "a need the matcher can never reach", when it matches fine —
    and was left with `category=None`, ungroupable in the list, which is the other half of the defect
    this function was written to close.

    Returns None for an unknown type — never a guess. The caller decides what to do with a need the
    matcher cannot reach; dropping it would lose a real ask.
    """
    if not proposed:
        return None
    slug = proposed.strip().lower()
    if slug in CATALOG or slug in _UMBRELLA_NEED_CATEGORY or slug in _NEED_ALTERNATIVES:
        return slug
    aliased = _NEED_TYPE_ALIASES.get(slug)
    if aliased is None:
        return None
    reachable = aliased in CATALOG or aliased in _UMBRELLA_NEED_CATEGORY
    return aliased if reachable or aliased in _NEED_ALTERNATIVES else None


def category_for_need_type(needs_type: str | None) -> DocumentCategory | None:
    """The category for a need type — None when unknown, never a guess (LP-623).

    LP-624 — an UMBRELLA type is answered here too. `asset_statement` has no catalog entry (it is not
    a document type; it is "any document of this category"), so it returned None and the need was left
    ungroupable in the list — the second half of what `canonical_need_type` was reporting as
    unreachable. `_UMBRELLA_NEED_CATEGORY` is exactly this mapping and was already in the file.
    """
    slug = needs_type or ""
    entry = CATALOG.get(slug)
    if entry is not None:
        return entry[1]
    return _UMBRELLA_NEED_CATEGORY.get(slug)


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
    # LP-623 — the matcher accepts alternatives, so the display must show them. A card listing the
    # documents that satisfy a need while the matcher counts a different set is the same defect in
    # reverse: the processor sees nothing and re-requests what is already there.
    alternatives = _NEED_ALTERNATIVES.get(needs_type, frozenset())
    return [
        d
        for d in documents
        if d.status is DocumentStatus.COMPLETED
        and (
            d.document_type == needs_type
            or d.document_type in alternatives
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
    # bug-001 — a need whose type names this document under another name (see _NEED_TYPE_ALIASES).
    aliased = [n for n, d in _NEED_TYPE_ALIASES.items() if d == document.document_type]
    # LP-623 — a need this document is one of the accepted ALTERNATIVES for (a passport or a green
    # card answering "Government ID"), which no equality, umbrella or alias could express.
    alternatives = [n for n, types in _NEED_ALTERNATIVES.items() if document.document_type in types]
    stmt = (
        select(NeedsItem)
        .where(
            NeedsItem.loan_file_id == document.loan_file_id,
            NeedsItem.needs_type.in_(
                [document.document_type, *umbrella_types, *aliased, *alternatives]
            ),
            NeedsItem.status.in_(OPEN_STATES),
        )
        .order_by(_MATCH_PRIORITY, NeedsItem.created_at)
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
            # LP-623 — THE DOCUMENT IS IN THE FILE. "Rejected" reads as "the borrower sent the wrong
            # thing", and the errand it implies (ask again) is the wrong one: what is needed is a
            # legible copy of a document already here. The state name is a stored enum and is left
            # alone; the sentence a processor actually reads is not.
            reason=(
                f"A {document.document_type or 'document'} is in the file but could not be "
                f"processed ({document.status.value}) — obtain a clean, legible copy rather than "
                "re-requesting it."
            ),
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


#: How far along a need is, for deciding which of two equivalent rows survives a merge. A need that a
#: document has actually reached beats one still waiting, whatever order they were created in.
_PROGRESS_RANK: dict[NeedsItemStatus, int] = {
    NeedsItemStatus.VERIFIED: 5,
    NeedsItemStatus.RECEIVED: 4,
    NeedsItemStatus.REJECTED: 3,
    NeedsItemStatus.REQUESTED: 2,
    NeedsItemStatus.PENDING: 1,
    NeedsItemStatus.WAIVED: 0,
}


async def repair_needs_for_file(db: AsyncSession, loan_file_id: UUID) -> int:
    """Repair rows an earlier version of this engine left inconsistent (LP-625). Returns rows touched.

    PREVENTING A DEFECT DOES NOT UNDO IT, and LP-623 shipped two fixes that only bind going forward:

      * `equivalent_need_type` stops the floor minting a second ID need under a new name — but LF-ABRS
        already carried BOTH, one VERIFIED against the borrower's green card and one REJECTED against
        their unreadable licence. Two rows, one title, contradictory states, and no amount of
        re-running fixes it because neither pass creates or removes a need.
      * `transition_need` now clears `reason` when a need leaves REJECTED — but a need that recovered
        BEFORE that shipped keeps the sentence describing how it failed, and only re-transitions if a
        new document arrives. LF-ABRS's RECEIVED W-2 still reads "could not be processed".

    So this is the repair half, run beside the other passes on every verification. Both operations are
    idempotent and neither invents a need: the merge WAIVES a redundant duplicate rather than deleting
    it, so the row and its history survive and a processor can see what happened.

    THE MERGE ONLY EVER WAIVES A FLOOR-ORIGIN ROW. That is the defect's own boundary — the floor is
    what minted the duplicate — and it is what keeps a processor's manually-added need, or an AI
    proposal they confirmed, out of scope no matter how the statuses rank. See the loop below.
    """
    needs = (
        await db.scalars(
            only_active(select(NeedsItem).where(NeedsItem.loan_file_id == loan_file_id), NeedsItem)
        )
    ).all()
    touched = 0

    # 1. MERGE EQUIVALENT DUPLICATES. Keyed exactly as `seed_floor_needs` now dedupes, so a pair it
    #    would no longer create is a pair this collapses.
    by_key: dict[tuple[str | None, object], list[NeedsItem]] = {}
    for need in needs:
        if need.status is NeedsItemStatus.WAIVED or not need.needs_type:
            continue  # a waived row is already out of the way; an untyped one has no equivalent
        by_key.setdefault((equivalent_need_type(need.needs_type), need.borrower_id), []).append(
            need
        )

    for (needs_type, _borrower), group in by_key.items():
        if len(group) < 2:
            continue
        # The furthest-along row wins; ties break on age, so the outcome does not depend on row order.
        group.sort(key=lambda n: (_PROGRESS_RANK.get(n.status, 0), -n.created_at.timestamp()))
        keeper = group[-1]
        # bug-009 REVIEW — the survivor is chosen by PROGRESS, not by whether a document can ever
        # satisfy it. So when the unmatchable row is the further along one (a processor marked the
        # `title_report` row received by hand), it becomes the keeper and the clearable
        # `title_commitment` row is waived — leaving the file with ONLY a need no upload can reach.
        # Strictly worse than doing nothing.
        #
        # The framing that stalls here is "preserve the progress OR prefer the actionable row". It is
        # a false choice: RENAMING the keeper does both. The alias map is a declaration that these
        # two types are the same requirement, so rewriting `title_report` -> `title_commitment` on a
        # row changes nothing about what was asked for — it changes only whether an upload can ever
        # match it. Progress is kept, and the row becomes satisfiable.
        #
        # This does mutate the keeper, which the merge otherwise never does. That convention exists
        # to stop the merge SILENTLY REVISING a requirement; a rename between declared-equivalent
        # types is not a revision, and leaving the row unsatisfiable to honour the convention would
        # protect the rule at the processor's expense.
        #
        # NOT FOR A MANUAL KEEPER. There the stored string is what a processor typed, and correcting
        # their words underneath them is exactly what the MANUAL guard below exists to prevent — so
        # that case is still only reported.
        if _is_unactionable_alias(keeper.needs_type) and any(
            not _is_unactionable_alias(n.needs_type) for n in group
        ):
            retyped = canonical_need_type(keeper.needs_type)
            if retyped and keeper.origin is not NeedsItemOrigin.MANUAL:
                logger.info(
                    "needs_merge_retyped_the_keeper",
                    loan_file_id=str(loan_file_id),
                    was=keeper.needs_type,  # a document type, not PII
                    now=retyped,
                    status=keeper.status.value,
                )
                keeper.needs_type = retyped
                touched += 1
            else:
                logger.warning(
                    "needs_merge_kept_an_unsatisfiable_row",
                    loan_file_id=str(loan_file_id),
                    kept_type=keeper.needs_type,  # a document type, not PII
                    kept_status=keeper.status.value,
                )
        for redundant in group[:-1]:
            # ONLY A ROW THE FLOOR MINTED MAY BE MERGED AWAY. The defect being repaired is the FLOOR
            # creating a second row under a renamed type, so a floor-origin duplicate is provably
            # redundant: `seed_floor_needs` now dedupes on this exact key and would no longer create
            # the pair. Nothing else in the group is.
            #
            # Without this the merge waived on `(equivalent_need_type, borrower_id)` alone, and a
            # processor's own need was in scope. Concretely: the floor's `bank_statement` need for a
            # borrower is RECEIVED with a Chase statement attached; the processor adds "Bank statement
            # — Wells Fargo, November" through POST /needs (origin MANUAL, disposition CONFIRMED, the
            # same needs_type). RECEIVED outranks PENDING, so the next run waived the manual need AND
            # `transition_need` flipped its disposition CONFIRMED -> WAIVED. A real requirement left
            # the open list and the Wells Fargo statement is never collected. The same shape covers
            # every legitimately multi-instance type — two years of `w2`, successive `paystub`s.
            #
            # This is the boundary `needs_dedup` states for LP-111 ("a confirmed / waived / adjusted /
            # received need is a fixed point"), applied to the axis that matters here. It is NOT that
            # module's PROPOSED+PENDING test: the floor ships CONFIRMED, so that test would make this
            # repair a no-op against its own motivating case — LF-ABRS's pair is VERIFIED + REJECTED.
            # bug-009 REVIEW — a SECOND provably-redundant case, because the FLOOR test alone
            # missed the pair this repair was written for. LP-69 creates its proposals with
            # origin AI_REASONING (`needs_ai.py`), not FLOOR, so the `title_report` row on a live
            # file was skipped here and the merge did nothing — while a test using a FLOOR-origin
            # fixture passed.
            #
            # A row whose stored type no document can ever match is redundant for a different
            # reason than the floor's: it is not a requirement a processor can act on, it is an
            # artifact. Collapsing it into an equivalent row that CAN be satisfied takes nothing
            # away.
            #
            # MANUAL IS STILL NEVER MERGED, whatever its type. The protection this guard exists for
            # is a processor's own ask — the Wells Fargo statement in the paragraph above — and a
            # mistyped manual need is something they can see and correct, not something to waive
            # underneath them.
            mergeable = redundant.origin is NeedsItemOrigin.FLOOR or (
                redundant.origin is not NeedsItemOrigin.MANUAL
                and _is_unactionable_alias(redundant.needs_type)
                and not _is_unactionable_alias(keeper.needs_type)
            )
            if not mergeable:
                logger.info(
                    "needs_duplicate_merge_skipped",
                    loan_file_id=str(loan_file_id),
                    needs_type=needs_type,  # a document type, not PII
                    origin=redundant.origin.value,
                )
                continue
            await transition_need(
                db,
                need=redundant,
                to_state=NeedsItemStatus.WAIVED,
                reason=(
                    f"Merged into the other '{needs_type}' need on this file, which is "
                    f"{keeper.status.value}. Both asked for the same document under different names."
                ),
            )
            touched += 1
            logger.info(
                "needs_duplicate_merged",
                loan_file_id=str(loan_file_id),
                needs_type=needs_type,  # a document type, not PII
                kept=keeper.status.value,
            )

    # 2. CLEAR A REASON THAT NO LONGER DESCRIBES THE STATE. `reason` belongs to REJECTED and WAIVED;
    #    anywhere else it is the residue of a failure the need has since recovered from.
    for need in needs:
        if need.reason and need.status not in (NeedsItemStatus.REJECTED, NeedsItemStatus.WAIVED):
            need.reason = None
            touched += 1

    if touched:
        await db.flush()
    return touched


async def rematch_needs_for_file(db: AsyncSession, loan_file_id: UUID) -> list[NeedsItem]:
    """Re-run satisfaction-matching over documents ALREADY on the file (LP-623).

    :func:`apply_document_to_needs` fires once, when a document is processed. Nothing ever
    re-evaluates, so every change to WHAT MATCHES silently skips the documents already there — and
    that is not hypothetical. bug-001 added ``existing_mortgage_statement -> mortgage_statement`` to
    ``_NEED_TYPE_ALIASES``; LF-ABRS's mortgage statement had arrived before it shipped, so the need
    sat PENDING beside the document that answers it, and would have forever.

    Same matcher, same guards, replayed: this calls ``apply_document_to_needs`` per document rather
    than reimplementing the rules, so an alias, an umbrella type or a state change is picked up here
    by construction. Oldest document first, so the ordering matches a fresh file's arrival order.

    IDEMPOTENT, AND THAT TOOK TWO GUARDS (LP-624). The claim used to be that "a document whose need is
    already satisfied finds nothing open and is a no-op", which is only true when there is no OTHER
    open need of the same type. There usually is:

    * A DOCUMENT IS CONSUMED ONCE. Nothing recorded which document had already satisfied which need,
      so a pay stub that satisfied need A was offered to need B on the next run — and this runs on
      every verification, so ONE upload walked down the whole list of same-typed needs, one per run,
      each marked `satisfied_by_document_id` by the same file.
    * ONLY A COMPLETED DOCUMENT IS REPLAYED. A FAILED/NEEDS_REVIEW document was replayed too, and
      `_MATCH_PRIORITY` prefers a non-REJECTED need — so the freshest untouched need is exactly where
      an old unreadable document landed. A need seeded today (a co-borrower added, a finding's
      request) was rejected with "a pay_stub is in the file but could not be processed … obtain a
      clean, legible copy", about a document that was never for it and was already accounted for
      elsewhere. Arrival-time matching still sees those documents; it is the REPLAY that must not
      re-litigate them.
    """
    documents = (
        await db.scalars(
            only_active(
                select(Document)
                .where(
                    Document.loan_file_id == loan_file_id,
                    Document.status == DocumentStatus.COMPLETED,
                )
                .order_by(Document.created_at),
                Document,
            )
        )
    ).all()
    consumed = set(
        (
            await db.scalars(
                only_active(
                    select(NeedsItem.satisfied_by_document_id).where(
                        NeedsItem.loan_file_id == loan_file_id,
                        NeedsItem.satisfied_by_document_id.is_not(None),
                    ),
                    NeedsItem,
                )
            )
        ).all()
    )
    advanced: list[NeedsItem] = []
    for document in documents:
        if document.id in consumed:
            continue  # already answered a need — it cannot answer a second one
        need = await apply_document_to_needs(db, document)
        if need is not None:
            consumed.add(document.id)
            advanced.append(need)
    if advanced:
        logger.info(
            "needs_rematched",
            loan_file_id=str(loan_file_id),
            advanced=len(advanced),
            documents=len(documents),
        )
    return advanced


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
    # LP-623 — `government_id`, not `drivers_license`. The title always said "Government ID"; the type
    # named one of the documents that provide it, so a borrower holding a passport or a green card had
    # an unsatisfiable need. See `_NEED_ALTERNATIVES`.
    ("government_id", "Government ID", DocumentCategory.BORROWER_INFO),
]
_PER_FILE_UNIVERSAL: list[tuple[str, str, DocumentCategory]] = []


async def _subject_property(db: AsyncSession, loan_file_id: UUID) -> Property | None:
    """The file's subject property row, or None (LP-642).

    Returns None on the ambiguous case too — more than one active row — rather than picking. A file
    cannot hold two today (`uq_properties_loan_file_id` is a plain UNIQUE on `loan_file_id`), so this
    is a guard against that constraint being relaxed, not a live path; `rental_treatment` makes the
    same distinction and says the same thing about it.
    """
    rows = (
        await db.scalars(
            only_active(select(Property).where(Property.loan_file_id == loan_file_id), Property)
        )
    ).all()
    return rows[0] if len(rows) == 1 else None


async def seed_floor_needs(db: AsyncSession, loan_file: LoanFile) -> list[NeedsItem]:
    """Seed the THIN deterministic floor of near-certain needs.

    Two parts: **universal needs** (always required on every file — a Government ID
    per borrower; refine the full list with Priya, see ``_PER_BORROWER_UNIVERSAL`` /
    ``_PER_FILE_UNIVERSAL``) and **conditional rules** from the stated data
    (employment income → pay stubs + W-2; a purchase → purchase agreement; stated
    assets → bank statements). Universal needs live in the floor — NOT LP-69's AI
    reasoning — precisely because they're not distinctive: the AI surfaces what's
    *special* about a file, so it may under-propose an obvious always-true need.

    RE-DERIVABLE, PER NEED (LP-623). This was one-shot: the guard asked "does this file have ANY
    floor need" and bailed, so the deterministic half of the list froze at MISMO import and never
    moved again. A borrower added afterwards never got a Government ID (the per-borrower loop only
    ever saw the borrowers who existed at import); a loan purpose corrected from purchase to
    refinance never gained its mortgage statement and payoff statement; income or assets added later
    never raised pay stubs, W-2s or bank statements. The AI half re-reasons on every document
    arrival, but it is asked what is DISTINCTIVE about a file and so is the least likely thing to
    propose a government ID for a borrower who turned up late.

    Idempotence now lives per NEED rather than per file: a need is skipped when the file already
    carries one of that type — for a per-borrower universal, of that type FOR THAT BORROWER. Matched
    against every need in ANY status and ANY origin, so a floor pass can neither duplicate what the
    AI or a finding already raised, nor resurrect one a processor waived or dismissed.

    ADDS ONLY. A need whose reason has since gone away (the purchase agreement on a file corrected to
    a refinance) is NOT removed here — a processor may have already requested or received it, and
    deleting their work under them is worse than a stale line. Surfacing "the reason for this is
    gone" is the follow-up.

    The floor is intentionally thin — the bulk of the intelligence is LP-69's AI reasoning, which
    augments this baseline. Floor needs are ``origin=FLOOR`` and ``disposition=CONFIRMED``
    (near-certain). Uses ``flush``.

    Flushes FIRST so the stated-data rules see the caller's just-added rows: the
    session runs ``autoflush=False`` (ADR), so ``StatedIncomeItem`` / ``StatedAsset``
    rows that a caller ``db.add``-ed but hasn't flushed are invisible to the SELECTs
    in :func:`_has_stated_employment_income` / :func:`_has_stated_assets`. Without
    this flush the employment (→ pay stubs + W-2) and asset (→ bank statements) rules
    silently miss the data and only the purchase rule (in-memory ``loan_purpose``)
    fires (LP-71.5).
    """
    await db.flush()
    # Every need already on the file, keyed for the two idempotence questions this function asks:
    # "does this borrower already have one" and "does the file already have one".
    existing_needs = (
        await db.scalars(
            only_active(select(NeedsItem).where(NeedsItem.loan_file_id == loan_file.id), NeedsItem)
        )
    ).all()
    existing_keys = {
        (equivalent_need_type(n.needs_type), n.borrower_id) for n in existing_needs if n.needs_type
    }
    existing_types = {needs_type for needs_type, _borrower in existing_keys}

    created: list[NeedsItem] = []

    # --- UNIVERSAL NEEDS (always required, every file — deterministic, NOT AI) ----
    # Per-borrower universals (a Government ID for EACH borrower — co-borrowers each
    # need their own), then per-file universals. See ``_PER_BORROWER_UNIVERSAL`` /
    # ``_PER_FILE_UNIVERSAL`` above (extensible; refine the full list with Priya).
    for borrower in await _active_borrowers(db, loan_file.id):
        # Identify which borrower each ID is for (name in the title + the borrower link).
        name = borrower.full_name.strip() or f"Borrower {borrower.borrower_position}"
        for needs_type, title, category in _PER_BORROWER_UNIVERSAL:
            # PER BORROWER, not per file: a co-borrower added after import needs their own ID, and a
            # file-level type check would read the primary's need as covering them.
            if (equivalent_need_type(needs_type), borrower.id) in existing_keys:
                continue
            existing_keys.add((equivalent_need_type(needs_type), borrower.id))
            existing_types.add(equivalent_need_type(needs_type))
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
        if equivalent_need_type(needs_type) in existing_types:
            continue
        existing_types.add(equivalent_need_type(needs_type))
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
    # LP-642 — AN INVESTMENT SUBJECT NEEDS A RENT SCHEDULE, and until now nothing asked for one.
    #
    # Fannie B3-3.8-02 (09/02/2026) makes Form 1007 (one unit) or Form 1025 (two-to-four) MANDATORY
    # where the subject's rental income is used to qualify. LF-ZE9N is the shape this is for: an
    # investment purchase whose DTI gates because no document on the file states what the subject will
    # rent for — and the processor was shown a blanked ratio with nothing to send the borrower.
    #
    # THE UNIT COUNT PICKS THE FORM, and an ABSENT count does not silently pick 1007. Asking for the
    # wrong form is a wasted round-trip with the borrower, so an unknown count asks for neither and the
    # gate keeps saying why — honest, and recoverable once the count is known.
    if (subject := await _subject_property(db, loan_file.id)) is not None and (
        subject.occupancy_type is OccupancyType.INVESTMENT
    ):
        units = subject.financed_unit_count
        form = (
            ("comparable_rent_schedule", "Comparable rent schedule (Form 1007)")
            if units == 1
            else ("small_residential_income_appraisal", "Rent schedule (Form 1025)")
            if units is not None and 2 <= units <= 4
            else None
        )
        if form is not None:
            specs.append(
                (
                    form[0],
                    form[1],
                    DocumentCategory.PROPERTY,
                    [
                        {
                            "kind": "mismo_field",
                            "label": (
                                "The subject is an investment property, so its market rent must be "
                                f"documented to qualify the loan ({units}-unit)"
                            ),
                        }
                    ],
                )
            )
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
        if equivalent_need_type(needs_type) in existing_types:
            continue
        existing_types.add(equivalent_need_type(needs_type))
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
