"""Needs coverage flagging (LP-631) — the file already answers this need.

An AI-proposed need is PROVISIONAL when it is written. LP-69 reasons at MISMO import, when
``documents_present`` is empty by construction, and :func:`app.services.needs_ai.apply_ai_needs` can
only ever create a row or refresh its reasoning — there is no branch that reconsiders a need the new
proposal set omitted, and the JSON contract has no channel to withdraw one. So a need proposed from
stated data alone survives every document that arrives afterwards and answers it.

Staging's LF-AWBB is the worked example: *"Lease agreement or documentation for the lease payment
liability"*, written at 22:34:58 from the MISMO liability ``LeasePayment / ALLY FINANCIAL / $438.00``,
still open beside a credit report — completed at 22:37:47 — whose tradelines list
``ALLY FINANCIAL / AUTO / 438``. Fannie Mae B3-6-01 asks for separate documentation only for a
liability *"that is not shown on a credit report"*. The need's precondition was false three minutes
after it was written, and nothing could say so.

**This module flags; it never closes (ADR-388).** A predicate that is right most of the time is a
good flag and a bad actuator: on staging today the liability predicate reaches six open needs and
should fire on two of them, because the other four sit on files with no credit report and are
therefore *correct* needs under the same guideline. The processor disposes — dismiss the need, or
keep it (:func:`keep_need_despite_coverage`, which sets ``coverage_reviewed`` so no pass re-flags a
judgement already made).

**The eligibility gate is LP-625's ``_refreshable`` boundary, restated once here:** origin
``AI_REASONING``, disposition still ``PROPOSED``, still open. A need a processor confirmed, dismissed
or adjusted carries their judgement, and no predicate has business touching it.

Adding a predicate is adding a function to :data:`_PREDICATES`. Each answers one question — *is this
need's precondition now false, and which document proves it?* — and returns the evidence rather than
acting on it.
"""

import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document import Document, DocumentStatus
from app.models.extraction import Extraction
from app.models.helpers import only_active
from app.models.needs_item import (
    NeedsItem,
    NeedsItemDisposition,
    NeedsItemOrigin,
    NeedsItemStatus,
)
from app.models.stated_financials import StatedLiability

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CoverageFinding:
    """One predicate's conclusion: this need looks answered by that document, for this reason."""

    need_id: UUID
    document_id: UUID
    note: str


CoveragePredicate = Callable[
    [AsyncSession, UUID, Sequence[NeedsItem]], Awaitable[list[CoverageFinding]]
]


# --------------------------------------------------------------------------- #
# LP-632 — the liability the credit report already documents
# --------------------------------------------------------------------------- #

#: Need type -> the MISMO ``LiabilityType`` it exists to document. A need outside this map is not
#: something a credit report can answer, whatever it cites.
_LIABILITY_DOC_NEEDS: dict[str, str] = {
    "lease_agreement": "leasepayment",
    "installment_statement": "installment",
    "credit_card_statement": "revolving",
}

#: A creditor name shorter than this carries too little signal to match on a prefix, which keeps the
#: rule from collapsing to "starts with the same letter".
#:
#: Prefix matching covers TRUNCATION (``BANK OF AMER`` for ``BANK OF AMERICA``) and nothing else. It
#: does NOT cover abbreviation, which is what LF-AWBB's report actually does — ``UNITED WHSLE MORT``
#: and ``DIGITAL FED CREDIT UNI`` are not prefixes of their expansions and will not match. That is
#: accepted rather than solved: a non-match leaves the need standing, which is the safe direction, and
#: fuzzy creditor matching is a much larger problem than this predicate should own. On the file that
#: prompted the work it costs nothing — both sides come from the same import, so the four names agree
#: exactly and prefix matching is only the margin.
_MIN_NAME_CHARS = 6


def _normalize_creditor(name: str | None) -> str:
    """Upper-case, alphanumerics only. ``SYNCB/ROOMS TO GO`` -> ``SYNCBROOMSTOGO``."""
    return re.sub(r"[^A-Z0-9]", "", (name or "").upper())


def _names_match(stated: str, reported: str) -> bool:
    """Prefix match in either direction, because either side may be the truncated one."""
    if len(stated) < _MIN_NAME_CHARS or len(reported) < _MIN_NAME_CHARS:
        return False
    return stated.startswith(reported) or reported.startswith(stated)


def _dollars(raw: Any) -> int | None:
    """A monthly payment rounded to whole dollars, or None when there isn't one.

    Rounded because the two sides come from different places: an application states ``438.00`` and a
    credit report reports ``438``. Zero is not a payment — a $0 tradeline is not evidence of a $438
    obligation — so it reads as absent.
    """
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    rounded = int(value.to_integral_value())
    return rounded or None


async def _newest_credit_report(
    db: AsyncSession, loan_file_id: UUID
) -> tuple[Document, dict[str, Any]] | None:
    """The file's newest COMPLETED credit report and its current extraction payload."""
    stmt = (
        only_active(
            select(Document, Extraction)
            .join(Extraction, Extraction.document_id == Document.id)
            .where(
                Document.loan_file_id == loan_file_id,
                Document.document_type == "credit_report",
                Document.status == DocumentStatus.COMPLETED,
                Extraction.is_current.is_(True),
            ),
            Document,
        )
        .order_by(Document.created_at.desc())
        .limit(1)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        return None
    document, extraction = row
    payload = extraction.extracted_data if isinstance(extraction.extracted_data, dict) else {}
    return document, payload


def _reported_obligations(payload: dict[str, Any]) -> list[tuple[str, int]]:
    """The credit report's tradelines as ``(normalized creditor, whole-dollar payment)``.

    Rows are bare scalars (LP-443 capture), not typed ``{value}`` nodes. A row with no payment is
    dropped: it cannot evidence an obligation's amount, which is half of what makes a match
    identifying.
    """
    rows = payload.get("tradelines")
    if not isinstance(rows, list):
        return []
    obligations: list[tuple[str, int]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = _normalize_creditor(row.get("creditor_name"))
        payment = _dollars(row.get("monthly_payment"))
        if name and payment is not None:
            obligations.append((name, payment))
    return obligations


async def _liabilities_by_type(
    db: AsyncSession, loan_file_id: UUID
) -> dict[str, list[StatedLiability]]:
    """The file's active stated liabilities, grouped by lower-cased ``liability_type``."""
    rows = (
        await db.scalars(
            only_active(
                select(StatedLiability).where(StatedLiability.loan_file_id == loan_file_id),
                StatedLiability,
            )
        )
    ).all()
    grouped: dict[str, list[StatedLiability]] = {}
    for liability in rows:
        key = (liability.liability_type or "").strip().lower()
        if key:
            grouped.setdefault(key, []).append(liability)
    return grouped


def _describe(liability: StatedLiability, payment: int) -> str:
    return f"{liability.holder_name or 'an unnamed creditor'} at ${payment:,}/mo"


async def liability_documented_by_credit_report(
    db: AsyncSession, loan_file_id: UUID, needs: Sequence[NeedsItem]
) -> list[CoverageFinding]:
    """LP-632 — a need to document a liability, where the credit report already shows it.

    Fannie Mae B3-6-01: the lender must "verify any other liability **that is not shown on a credit
    report** by obtaining documentation from the borrower or creditor". So the need applies only
    where the liability is absent from the report, and that is a join, not a judgement.

    **Every liability of the type must match, not any.** A need reading "statements for all four
    revolving accounts" is answered only when all four are on the report — LP-108's discipline
    arriving from the coverage side, where under-claiming costs a click and over-claiming is the
    dangerous direction. No liabilities of the type means no basis for a flag, not a vacuous one.

    Matching is creditor name AND payment. Name alone is not identifying and LF-AWBB proves it: two
    ``CAPITAL ONE`` rows, two ``SYNCB/TJXDC`` rows.
    """
    in_scope = [n for n in needs if (n.needs_type or "") in _LIABILITY_DOC_NEEDS]
    if not in_scope:
        return []
    report = await _newest_credit_report(db, loan_file_id)
    if report is None:
        return []
    document, payload = report
    reported = _reported_obligations(payload)
    if not reported:
        return []
    by_type = await _liabilities_by_type(db, loan_file_id)

    findings: list[CoverageFinding] = []
    for need in in_scope:
        liability_type = _LIABILITY_DOC_NEEDS[need.needs_type or ""]
        liabilities = by_type.get(liability_type, [])
        if not liabilities:
            continue
        matched: list[str] = []
        for liability in liabilities:
            stated_name = _normalize_creditor(liability.holder_name)
            stated_payment = _dollars(liability.monthly_payment)
            if stated_payment is None:
                break  # nothing to match on — treat the need as unanswered
            hit = next(
                (
                    payment
                    for name, payment in reported
                    if payment == stated_payment and _names_match(stated_name, name)
                ),
                None,
            )
            if hit is None:
                break
            matched.append(_describe(liability, hit))
        else:
            findings.append(
                CoverageFinding(
                    need_id=need.id,
                    document_id=document.id,
                    note=(
                        f"The credit report lists {_join(matched)}, matching "
                        f"{'the' if len(matched) == 1 else 'every'} stated "
                        f"{liability_type} liabilit{'y' if len(matched) == 1 else 'ies'} on the "
                        "application. Fannie Mae B3-6-01 asks for separate documentation only for a "
                        "liability that is NOT shown on a credit report."
                    ),
                )
            )
    return findings


def _join(parts: list[str]) -> str:
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


#: The registry. Order is irrelevant — the first predicate to reach a need wins, and a second one
#: reaching the same need would only restate the conclusion.
_PREDICATES: tuple[CoveragePredicate, ...] = (liability_documented_by_credit_report,)


# --------------------------------------------------------------------------- #
# The pass
# --------------------------------------------------------------------------- #


def is_flaggable(need: NeedsItem) -> bool:
    """LP-625's ``_refreshable`` boundary, plus "not already flagged, not already judged".

    Untouched means untouched. A need a processor confirmed, dismissed or adjusted is theirs, and a
    predicate concluding otherwise does not get to say so on their row.
    """
    return (
        need.origin is NeedsItemOrigin.AI_REASONING
        and need.disposition is NeedsItemDisposition.PROPOSED
        and need.status in (NeedsItemStatus.PENDING, NeedsItemStatus.REQUESTED)
        # ``coverage_note`` is the flag, not ``covered_by_document_id``: a predicate always has a
        # document to point at, but LP-633's retraction may have only an argument, and a flag with no
        # note would be a row saying "possibly covered" with nothing to check.
        and need.coverage_note is None
        and not need.coverage_reviewed
    )


async def flag_covered_needs(db: AsyncSession, *, loan_file_id: UUID) -> int:
    """Run every coverage predicate over the file and FLAG what they answer. Returns rows flagged.

    Best-effort and idempotent: a flagged need is no longer eligible, so a second run over an
    unchanged file flags nothing. Never raises — a predicate that fails flags nothing rather than
    failing the needs update it runs inside. Gated by ``settings.needs_coverage_flagging_enabled``.
    Uses ``flush``; the caller owns the transaction and the per-file lock.
    """
    if not settings.needs_coverage_flagging_enabled:
        return 0
    needs = (
        await db.scalars(
            only_active(select(NeedsItem).where(NeedsItem.loan_file_id == loan_file_id), NeedsItem)
        )
    ).all()
    eligible = [n for n in needs if is_flaggable(n)]
    if not eligible:
        return 0

    by_id = {n.id: n for n in eligible}
    flagged = 0
    for predicate in _PREDICATES:
        try:
            findings = await predicate(db, loan_file_id, eligible)
        except Exception:  # a predicate is an optimisation; it never breaks the needs update
            logger.warning(
                "needs_coverage_predicate_failed",
                loan_file_id=str(loan_file_id),
                predicate=predicate.__name__,
                exc_info=True,
            )
            continue
        for finding in findings:
            need = by_id.get(finding.need_id)
            if need is None or need.coverage_note is not None:
                continue  # already flagged by an earlier predicate this pass
            need.covered_by_document_id = finding.document_id
            need.coverage_note = finding.note
            flagged += 1
            logger.info(
                "needs_coverage_flagged",
                loan_file_id=str(loan_file_id),
                needs_type=need.needs_type,  # a document type, not PII
                predicate=predicate.__name__,
            )
    if flagged:
        await db.flush()
    return flagged


async def apply_retraction(
    db: AsyncSession, *, need: NeedsItem, why: str, document_id: UUID | None = None
) -> bool:
    """LP-633 — the reasoner withdraws its own proposal, as an LP-631 flag. Returns whether it stuck.

    The AI is simply another source of the same signal, and it lands in the same columns under the
    same rules: only on a need no human has touched, and only as a flag (ADR-388). It never closes
    one — LP-69's guardrail 2 says the model does not self-CONFIRM a need, and the closing direction
    is not obviously safer merely because it removes work rather than creating it.

    ``document_id`` is optional and often absent: a predicate always has a document to point at, but
    a retraction may rest on an argument ("the file's income is documented three other ways"). The
    note is what makes the flag checkable, so it is required.
    """
    if not is_flaggable(need) or not why.strip():
        return False
    need.coverage_note = why.strip()
    need.covered_by_document_id = document_id
    await db.flush()
    return True


async def keep_need_despite_coverage(db: AsyncSession, *, need: NeedsItem) -> NeedsItem:
    """The processor KEEPS a flagged need: clear the flag, record that they judged it (LP-631).

    The mirror of LP-111's "not a duplicate". ``coverage_reviewed`` is what stops the next pass
    re-flagging what a human has already decided — without it the flag returns on the next document
    to arrive, and the processor is asked the same question forever.
    """
    need.covered_by_document_id = None
    need.coverage_note = None
    need.coverage_reviewed = True
    await db.flush()
    return need
