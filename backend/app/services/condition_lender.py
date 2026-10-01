"""The file's lender, as the Conditions tab needs it (LP-949, ADR-417).

A condition gets its library type ONLY from its lender's code map, at import
(`condition_import._apply_code_defaults`). A file with no lender therefore imports every condition
untyped, the reading splits each one itself, and nothing downstream that needs a type works: emails
carry no library wording, no document is found already in the file, no condition waits on another. The
staging trial of 2026-09-30 (LF-DH8V) was exactly that. This module closes it in three places:

1. **She is asked.** `lender_suggestion` reads which lender the newest sheet names
   (`app.conditions.lender_detect`) and offers it; `set_file_lender` sets it only when she confirms.
   Nothing here ever sets a lender by itself.
2. **Setting the lender types what is untyped.** `on_file_lender_changed` runs inside every lender
   change (`loan_files.update_loan_file`) and applies the new lender's code map to the file's UNTYPED
   conditions. A typed condition is never re-typed, and a condition already read keeps its reading: the
   caller queues a reading only for conditions still unread, so "never re-read a read or confirmed
   condition" holds (LP-952 states the same rule for its route).
3. **The AI may propose, a person decides.** A code with no meaning in the map is recorded for review
   (`OBSERVED_UNMAPPED`, as import already does), with the reading's proposed type copied onto it
   (`proposed_type_id`). `type_conditions_for_code` applies a type only after she maps the code in
   "Codes to review".

NO NPI IN LOGS: ids, codes, type ids and counts only.
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
from app.conditions.library import load_library
from app.models.base import utcnow
from app.models.condition import (
    Condition,
    ConditionLenderStatus,
    ConditionReadingStatus,
    OwnerHintSource,
)
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import ConditionRound, ConditionRoundStatus
from app.models.helpers import only_active
from app.models.lender import Lender
from app.models.lender_condition_code import LenderCodeStatus, LenderConditionCode
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
    """Her company's lender for a shipped key: by `canonical_lender_key`, else by the printed name.

    THE NAME MATCH NEVER ATTACHES THE KEY. The seed's rule is that a lender with no key is "skipped and
    reported, never guessed at" (`seed_lender_codes.py`), so a same-named lender without the key is the
    file's lender but carries no code map until an admin sets the key. `set_file_lender` says so.
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


async def _has_code_map(db: AsyncSession, lender_id: UUID) -> bool:
    """Whether ANY of this lender's codes has a library type, which is what typing needs.

    MEASURED ON THE ROWS, NOT THE KEY (review). The build said `canonical_lender_key in shipped`, so a
    keyless lender whose codes an admin had mapped was still "has no condition codes in the app" on the
    banner, and a keyed lender whose seed had not run claimed a map it did not have.
    """
    found = await db.scalar(
        select(LenderConditionCode.id)
        .where(
            LenderConditionCode.lender_id == lender_id,
            LenderConditionCode.canonical_type_id.is_not(None),
        )
        .limit(1)
    )
    return found is not None


async def file_lender_payload(db: AsyncSession, *, loan_file: LoanFile) -> dict[str, Any]:
    """`FileLenderPublic`'s data: the file's lender, or what the sheet suggests."""
    lender = await db.get(Lender, loan_file.lender_id) if loan_file.lender_id else None
    suggestion = await lender_suggestion(db, loan_file=loan_file)
    return {
        "lender": (
            {
                "id": lender.id,
                "name": lender.name,
                "has_code_map": await _has_code_map(db, lender.id),
            }
            if lender is not None
            else None
        ),
        "suggestion": (
            {
                "round_id": suggestion.round_id,
                "key": suggestion.detected.key,
                "name": suggestion.detected.name,
                "source": suggestion.detected.source,
                "lender_exists": suggestion.lender_id is not None,
                # Whether confirming types anything (review): a lender she adds here is created
                # with its key and seeded, so it does; a same-named lender without the key does not,
                # and the banner must not promise that it will.
                "has_code_map": suggestion.lender_id is None
                or await _has_code_map(db, suggestion.lender_id),
            }
            if suggestion is not None
            else None
        ),
    }


# --------------------------------------------------------------------------------------------- #
# Her answer
# --------------------------------------------------------------------------------------------- #


async def _lender_for_key(db: AsyncSession, *, company_id: UUID, key: str) -> Lender:
    """Her company's lender for a shipped key, created with that key (and its code map) if absent."""
    from app.scripts.seed_lender_codes import seed_lender

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
    await seed_lender(db, lender=lender)
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
    cleared (LP-813) and the conditions are typed (`on_file_lender_changed`) whichever screen she used.
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
# Typing what is untyped
# --------------------------------------------------------------------------------------------- #


def _apply_type(
    condition: Condition, code_row: LenderConditionCode, *, by: str, actor_user_id: UUID | None
) -> ConditionEvent | None:
    """Give an untyped condition the code map's type, as import would have. None when there is none.

    The same three things import's `_apply_code_defaults` applies, and only those: the type,
    `info_only` (raised, never lowered) and the owner hint WHERE THE SHEET GAVE NONE.
    """
    if condition.canonical_type_id is not None or not code_row.canonical_type_id:
        return None
    condition.canonical_type_id = code_row.canonical_type_id
    if code_row.info_only:
        condition.info_only = True
    if (
        condition.owner_hint_source is OwnerHintSource.NONE
        and code_row.default_owner_hint is not None
    ):
        condition.owner_hint = code_row.default_owner_hint
        condition.owner_hint_source = OwnerHintSource.CODE_MAP
    return ConditionEvent(
        company_id=condition.company_id,
        loan_file_id=condition.loan_file_id,
        condition_id=condition.id,
        kind=ConditionEventKind.CONDITION_TYPED,
        actor_user_id=actor_user_id,
        detail={
            "by": by,
            "type_id": code_row.canonical_type_id,
            "lender_id": str(code_row.lender_id),
            "code": condition.lender_code,
        },
    )


def _proposal(condition: Condition) -> str | None:
    """The reading's proposed type for an untyped condition, if it names a real library type."""
    proposed = (condition.reading or {}).get("proposed_type_id")
    if isinstance(proposed, str) and load_library().get(proposed) is not None:
        return proposed
    return None


async def record_proposals(
    db: AsyncSession, *, lender_id: UUID, conditions: list[Condition]
) -> int:
    """Copy each untyped condition's proposed type onto its code's review row. Returns how many.

    Only onto a row still `OBSERVED_UNMAPPED`: a seeded or mapped code already has a person's answer,
    and a proposal must never sit beside it looking like a second one. A proposal already there is
    kept: the first reading's guess is not replaced by a later one without a person looking.
    """
    wanted = {
        condition.lender_code: proposed
        for condition in conditions
        if condition.canonical_type_id is None
        and condition.lender_code
        and (proposed := _proposal(condition)) is not None
    }
    if not wanted:
        return 0
    rows = await db.scalars(
        select(LenderConditionCode).where(
            LenderConditionCode.lender_id == lender_id,
            LenderConditionCode.code.in_(list(wanted)),
            LenderConditionCode.status == LenderCodeStatus.OBSERVED_UNMAPPED,
            LenderConditionCode.proposed_type_id.is_(None),
        )
    )
    written = 0
    for row in rows:
        row.proposed_type_id = wanted[row.code]
        written += 1
    return written


async def _untyped(db: AsyncSession, *, where: list[Any]) -> list[Condition]:
    return list(
        await db.scalars(
            only_active(
                select(Condition)
                .where(
                    Condition.canonical_type_id.is_(None),
                    Condition.lender_code.is_not(None),
                    Condition.lender_status != ConditionLenderStatus.SUPERSEDED,
                    *where,
                )
                .order_by(Condition.sequence, Condition.created_at, Condition.id),
                Condition,
            )
        )
    )


async def on_file_lender_changed(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    previous_lender_id: UUID | None,
    actor_user_id: UUID | None,
) -> int:
    """Apply the file's new lender to its rounds and its UNTYPED conditions. Returns how many got a type.

    - Every round on the file takes the new lender: the sheet is now known to be this lender's.
    - Every untyped condition on the file takes the new lender, then its type from that lender's code
      map (whatever lender it carried before: an earlier lender of this file, through any number of
      changes, including one to no lender). A code the map does not know is recorded for review
      (`OBSERVED_UNMAPPED`, as import does), with the reading's proposal copied on.
    - Nothing typed is touched, and nothing is read here: the caller queues the reading after commit,
      and the reading takes only unread conditions.
    """
    new_id = loan_file.lender_id
    if new_id is None or new_id == previous_lender_id:
        return 0
    new_lender = await db.get(Lender, new_id)
    if new_lender is None or new_lender.company_id != loan_file.company_id:
        # TENANCY (review): never write review rows onto, or type from, another company's lender.
        # The PATCH route refuses such an id; this is the second lock on the same door.
        logger.warning(
            "file_lender_not_applied_foreign", loan_file_id=str(loan_file.id), lender_id=str(new_id)
        )
        return 0
    # EVERY ROUND AND EVERY UNTYPED CONDITION ON THE FILE FOLLOWS THE FILE'S LENDER (review). The
    # build moved only those with no lender or the PREVIOUS one, so A -> none -> B left A's untyped
    # conditions at A for ever, while A -> B moved them. Nothing else puts a lender on a round or a
    # condition but the file's lender at the time, so "the previous one" was only ever a proxy for
    # "an earlier lender of this file", and the none hop broke the proxy.
    for round_ in await db.scalars(
        select(ConditionRound).where(ConditionRound.loan_file_id == loan_file.id)
    ):
        round_.lender_id = new_id

    conditions = await _untyped(db, where=[Condition.loan_file_id == loan_file.id])
    if not conditions:
        await db.flush()
        return 0
    for condition in conditions:
        condition.lender_id = new_id

    codes = sorted({c.lender_code for c in conditions if c.lender_code})
    code_map = {
        row.code: row
        for row in await db.scalars(
            select(LenderConditionCode).where(
                LenderConditionCode.lender_id == new_id, LenderConditionCode.code.in_(codes)
            )
        )
    }
    now = utcnow()
    for code in codes:
        if code not in code_map:
            # THE SAME ROW IMPORT WRITES FOR A CODE NOBODY HAS MAPPED (`_record_codes`): the label is
            # the code itself, because an unknown code has no meaning by definition.
            created = LenderConditionCode(
                lender_id=new_id,
                code=code,
                label=code,
                status=LenderCodeStatus.OBSERVED_UNMAPPED,
                times_seen=1,
                first_seen_at=now,
                last_seen_at=now,
            )
            db.add(created)
            code_map[code] = created
    await db.flush()

    typed = 0
    for condition in conditions:
        code_row = code_map.get(condition.lender_code or "")
        if code_row is None:
            continue
        event = _apply_type(condition, code_row, by="lender_set", actor_user_id=actor_user_id)
        if event is not None:
            db.add(event)
            typed += 1
    await record_proposals(db, lender_id=new_id, conditions=conditions)
    await db.flush()
    logger.info(
        "file_lender_applied_to_conditions",
        loan_file_id=str(loan_file.id),
        lender_id=str(new_id),
        untyped=len(conditions),
        typed=typed,
    )
    return typed


async def type_conditions_for_code(
    db: AsyncSession, *, lender: Lender, code: str, actor_user_id: UUID | None
) -> set[UUID]:
    """After she maps a code: type every untyped condition with that code at that lender.

    Returns the files that gained a type, so the caller can queue the reading for the unread ones.
    """
    mapped: LenderConditionCode | None = await db.scalar(
        select(LenderConditionCode).where(
            LenderConditionCode.lender_id == lender.id, LenderConditionCode.code == code
        )
    )
    if mapped is None or not mapped.canonical_type_id:
        return set()
    files: set[UUID] = set()
    for condition in await _untyped(
        db, where=[Condition.lender_id == lender.id, Condition.lender_code == code]
    ):
        event = _apply_type(condition, mapped, by="code_confirmed", actor_user_id=actor_user_id)
        if event is not None:
            db.add(event)
            files.add(condition.loan_file_id)
    await db.flush()
    return files


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
