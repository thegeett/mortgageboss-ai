"""The file's lender, as the Conditions tab needs it (LP-949, ADR-417; LP-965, ADR-419).

1. **She is asked.** `lender_suggestion` reads which lender the newest sheet names
   (`app.conditions.lender_detect`) and offers it; `set_file_lender` sets it only when she confirms.
   Nothing here ever sets a lender by itself.
2. **The rounds and conditions follow the file's lender.** `on_file_lender_changed` runs inside every
   lender change (`loan_files.update_loan_file`) and moves the file's rounds and live conditions to the
   new lender, so matching across rounds by (lender, code) keeps working.

LP-965 — NO CODE MAP (the owner, 2026-10-07; ADR-419). This module used to type the file's untyped
conditions from the new lender's code map, record unknown codes for review, and copy the AI's proposed
type onto them for an admin to map. A condition's type now comes only from its reading, which asks the AI
fresh every time, so setting a lender types nothing. The lender still matters: its key decides how a
condition gets done there (LP-955 routes), and it scopes matching.

NO NPI IN LOGS: ids and counts only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.conditions.lender_codes.loader import lender_label, seeded_lender_keys
from app.conditions.lender_detect import DetectedLender, detect_lender
from app.models.condition import Condition, ConditionLenderStatus, ConditionReadingStatus
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import ConditionRound, ConditionRoundStatus
from app.models.helpers import only_active
from app.models.lender import Lender
from app.models.loan_file import LoanFile

logger = structlog.get_logger(__name__)

#: Rounds whose sheet can still name the file's lender: one under review, or one already imported.
_LIVE_ROUNDS = (ConditionRoundStatus.DRAFT, ConditionRoundStatus.IMPORTED)


class LenderRefused(Exception):
    """A lender change this file may not have, with the sentence she reads."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Suggestion:
    round_id: UUID
    detected: DetectedLender
    #: Her company's lender for this key (or with this name), when it already has one.
    lender_id: UUID | None


# --------------------------------------------------------------------------------------------- #
# What the tab shows
# --------------------------------------------------------------------------------------------- #


async def _company_lender_for(db: AsyncSession, *, company_id: UUID, key: str) -> Lender | None:
    """Her company's lender for a known key: by `canonical_lender_key`, else by the printed name.

    THE NAME MATCH NEVER ATTACHES THE KEY: a same-named lender without it is the file's lender, and an
    admin sets the key deliberately.
    """
    by_key = await db.scalar(
        only_active(
            select(Lender)
            .where(Lender.company_id == company_id, Lender.canonical_lender_key == key)
            .order_by(Lender.created_at, Lender.id),
            Lender,
        )
    )
    if by_key is not None:
        return by_key
    by_name: Lender | None = await db.scalar(
        only_active(
            select(Lender)
            .where(
                Lender.company_id == company_id,
                func.lower(Lender.name) == lender_label(key).lower(),
            )
            .order_by(Lender.created_at, Lender.id),
            Lender,
        )
    )
    return by_name


async def _declined_round_ids(db: AsyncSession, loan_file_id: UUID) -> set[UUID]:
    rows = await db.scalars(
        select(ConditionEvent.round_id).where(
            ConditionEvent.loan_file_id == loan_file_id,
            ConditionEvent.kind == ConditionEventKind.ROUND_LENDER_DECLINED,
        )
    )
    return {row for row in rows if row is not None}


async def lender_suggestion(db: AsyncSession, *, loan_file: LoanFile) -> Suggestion | None:
    """The lender the newest live sheet names, while the file has none and she has not said no."""
    if loan_file.lender_id is not None:
        return None
    rounds = list(
        await db.scalars(
            only_active(
                select(ConditionRound)
                .where(
                    ConditionRound.loan_file_id == loan_file.id,
                    ConditionRound.status.in_(_LIVE_ROUNDS),
                )
                .order_by(ConditionRound.created_at.desc(), ConditionRound.id.desc()),
                ConditionRound,
            )
        )
    )
    declined = await _declined_round_ids(db, loan_file.id)
    for round_ in rounds:
        if round_.id in declined:
            # SHE SAID NO TO THIS SHEET. An older sheet naming the same lender is not a new question.
            return None
        detected = detect_lender(round_.sheet_format, round_.header)
        if detected is None:
            continue
        lender = await _company_lender_for(db, company_id=loan_file.company_id, key=detected.key)
        return Suggestion(
            round_id=round_.id, detected=detected, lender_id=lender.id if lender else None
        )
    return None


async def file_lender_payload(db: AsyncSession, *, loan_file: LoanFile) -> dict[str, Any]:
    """`FileLenderPublic`'s data: the file's lender, or what the sheet suggests."""
    lender = await db.get(Lender, loan_file.lender_id) if loan_file.lender_id else None
    suggestion = await lender_suggestion(db, loan_file=loan_file)
    return {
        "lender": ({"id": lender.id, "name": lender.name} if lender is not None else None),
        "suggestion": (
            {
                "round_id": suggestion.round_id,
                "key": suggestion.detected.key,
                "name": suggestion.detected.name,
                "source": suggestion.detected.source,
                "lender_exists": suggestion.lender_id is not None,
            }
            if suggestion is not None
            else None
        ),
    }


# --------------------------------------------------------------------------------------------- #
# Her answer
# --------------------------------------------------------------------------------------------- #


async def _lender_for_key(db: AsyncSession, *, company_id: UUID, key: str) -> Lender:
    """Her company's lender for a known key, created with that key if absent."""
    if key not in seeded_lender_keys():
        raise LenderRefused("That lender is not one the app knows.")
    existing = await _company_lender_for(db, company_id=company_id, key=key)
    if existing is not None:
        return existing
    from app.services.lenders import LenderError, create_lender

    try:
        lender = await create_lender(db, company_id=company_id, name=lender_label(key))
    except LenderError as exc:
        raise LenderRefused(exc.args[0] if exc.args else "The lender could not be added.") from exc
    lender.canonical_lender_key = key
    await db.flush()
    logger.info("file_lender_created_from_sheet", lender_id=str(lender.id), key=key)
    return lender


async def set_file_lender(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    lender_key: str | None,
    lender_id: UUID | None,
    actor_user_id: UUID | None,
) -> None:
    """She confirms the file's lender: a shipped key from the suggestion, or one of her lenders.

    Goes through `update_loan_file`, the one door every lender change takes, so the underwriter is
    cleared (LP-813) and the conditions follow it (`on_file_lender_changed`) whichever screen she used.
    Flushes; the caller commits and then queues the reading (`unread_round_to_read`).
    """
    from app.schemas.loan_file import LoanFileUpdate
    from app.services.lenders import get_scoped_lender
    from app.services.loan_files import update_loan_file, update_loan_file_with_activity

    if (lender_key is None) == (lender_id is None):
        raise LenderRefused("Choose one lender.")
    if lender_id is not None:
        lender = await get_scoped_lender(db, lender_id=lender_id, company_id=loan_file.company_id)
        if lender is None:
            raise LenderRefused("That lender is not one of your company's lenders.")
    else:
        assert lender_key is not None
        lender = await _lender_for_key(db, company_id=loan_file.company_id, key=lender_key)
    if actor_user_id is None:
        await update_loan_file(db, loan_file=loan_file, data=LoanFileUpdate(lender_id=lender.id))
        return
    # THE ACTIVITY LOG RECORDS IT, as it records the same change made in Overview's loan editor.
    await update_loan_file_with_activity(
        db,
        loan_file=loan_file,
        data=LoanFileUpdate(lender_id=lender.id),
        actor_user_id=actor_user_id,
    )


async def decline_suggestion(
    db: AsyncSession, *, loan_file: LoanFile, round_id: UUID, actor_user_id: UUID | None
) -> None:
    """She says the detected lender is not this file's. Recorded on the round; nothing else changes."""
    suggestion = await lender_suggestion(db, loan_file=loan_file)
    if suggestion is None or suggestion.round_id != round_id:
        raise LenderRefused("There is no lender suggestion for that sheet.")
    db.add(
        ConditionEvent(
            company_id=loan_file.company_id,
            loan_file_id=loan_file.id,
            round_id=round_id,
            condition_id=None,
            kind=ConditionEventKind.ROUND_LENDER_DECLINED,
            actor_user_id=actor_user_id,
            detail={"key": suggestion.detected.key, "source": suggestion.detected.source},
        )
    )
    await db.flush()


# --------------------------------------------------------------------------------------------- #
# The file's rounds and conditions follow its lender
# --------------------------------------------------------------------------------------------- #


async def on_file_lender_changed(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    previous_lender_id: UUID | None,
    actor_user_id: UUID | None,
) -> int:
    """Move the file's rounds and live conditions to its new lender. Returns how many conditions moved.

    EVERY ONE, NOT ONLY THE UNTYPED (LP-965). Typed conditions used to keep their lender because their
    type came from that lender's code map; a type now comes from the reading, so nothing ties a condition
    to an earlier lender. Nothing is typed or read here.
    """
    new_id = loan_file.lender_id
    if new_id is None or new_id == previous_lender_id:
        return 0
    new_lender = await db.get(Lender, new_id)
    if new_lender is None or new_lender.company_id != loan_file.company_id:
        # TENANCY (review): never move a file's conditions onto another company's lender. The PATCH
        # route refuses such an id; this is the second lock on the same door.
        logger.warning(
            "file_lender_not_applied_foreign", loan_file_id=str(loan_file.id), lender_id=str(new_id)
        )
        return 0
    for round_ in await db.scalars(
        select(ConditionRound).where(ConditionRound.loan_file_id == loan_file.id)
    ):
        round_.lender_id = new_id
    conditions = list(
        await db.scalars(
            only_active(
                select(Condition).where(
                    Condition.loan_file_id == loan_file.id,
                    Condition.lender_status != ConditionLenderStatus.SUPERSEDED,
                ),
                Condition,
            )
        )
    )
    for condition in conditions:
        condition.lender_id = new_id
    await db.flush()
    logger.info(
        "file_lender_applied_to_conditions",
        loan_file_id=str(loan_file.id),
        lender_id=str(new_id),
        conditions=len(conditions),
    )
    return len(conditions)


async def unread_round_to_read(db: AsyncSession, *, loan_file_id: UUID) -> UUID | None:
    """The round to read when the file has unread conditions: its newest imported round, else None.

    `read_round` reads every unread condition on the round's FILE, so the newest imported round is
    the right one to name whichever round the unread conditions came from.
    """
    unread = await db.scalar(
        only_active(
            select(func.count(Condition.id)).where(
                Condition.loan_file_id == loan_file_id,
                Condition.reading_status == ConditionReadingStatus.UNREAD,
                Condition.lender_status != ConditionLenderStatus.SUPERSEDED,
            ),
            Condition,
        )
    )
    if not unread:
        return None
    newest: UUID | None = await db.scalar(
        only_active(
            select(ConditionRound.id)
            .where(
                ConditionRound.loan_file_id == loan_file_id,
                ConditionRound.status == ConditionRoundStatus.IMPORTED,
            )
            .order_by(ConditionRound.created_at.desc(), ConditionRound.id.desc())
            .limit(1),
            ConditionRound,
        )
    )
    return newest
