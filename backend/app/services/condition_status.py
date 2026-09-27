"""Moving the two status tracks, and recording what the lender said (LP-912, ADR-408).

THE ONE RULE THIS MODULE EXISTS TO ENFORCE: **only a recorded verdict may say the lender cleared
anything.** `cleared` and `waived` are unreachable here without a `source_kind` and a `source_date`,
and the date is the date the LENDER said it — never `today`, because a verdict dated by our clock is a
verdict about us. Everything else in this file is the same idea applied to a narrower case.

EVERY CHANGE WRITES EXACTLY ONE EVENT (spec §6 rule 4). The history is built from events and never
from current values, so a change with no event is a change nobody can audit — and two events for one
change is a history that double-counts. `condition_came_back` is the interesting case and ADR-408
settles it: it carries BOTH from→to pairs, because the lender's answer and its consequence for our
work are one statement, not two.

REFUSALS ARE TYPED AND WORDED, and the UI shows the server's sentence as-is (spec §6 rule 5).
Four of the sentences below are the spec's, character for character; four are mine, marked as such,
because the spec gives its four "for example" and the cases it does not name still need words a
processor can act on. `tests/.../test_refusal_sentences_match_the_spec.py` compares the four against
the tickets file's own bytes rather than a second hand-typed copy, which is what makes "verbatim" a
property instead of a claim.

THE CALLER OWNS THE TRANSACTION. Every function flushes and none commits, as every service here does.
The bulk entry point is called inside `loan_file_needs_lock`, which is ADVISORY and not mutual
exclusion — it yields `bool(acquired)` and its 30-second timeout auto-expires a held lock, so nothing
in here may assume it serialises anything. What actually protects a row is the optimistic check on
`updated_at`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.condition import (
    Condition,
    ConditionLenderStatus,
    ConditionPrepStatus,
)
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import ConditionRound
from app.models.helpers import only_active
from app.schemas.condition import (
    BulkAction,
    BulkRequest,
    OwnerRequest,
    PrepStatusRequest,
    ReopenRequest,
    VerdictRequest,
    VerdictSourceKind,
)

logger = structlog.get_logger(__name__)


class RefusalCode(StrEnum):
    """Why a write was refused. The code is for the client to branch on; the sentence is for a person.

    BOTH TRAVEL, AND THE CODE IS WHY BULK IS POSSIBLE AT ALL. A bulk write reports
    `{id, code, message}` per refused row, so the UI can say "1 skipped: information only" without
    parsing prose — and the four existing refusal exceptions in this feature carry a `reason` string
    only, which is why this module adds a class rather than a fifth copy of that shape.
    """

    # The spec's four (§LP-912), quoted verbatim below.
    BACKWARD_MOVE_NEEDS_REASON = "backward_move_needs_reason"
    INFO_ONLY_HAS_NO_STATUS = "info_only_has_no_status"
    VERDICT_NEEDS_SOURCE = "verdict_needs_source"
    STALE = "stale"

    # MINE, NOT THE SPEC'S. It gives its four "for example", and these are the cases it leaves unnamed.
    # Each needs a sentence because the alternative is a 422 with a field path, which tells a processor
    # which key was wrong rather than what to do.
    WAITING_NEEDS_OWNER = "waiting_needs_owner"
    NOTHING_TO_REOPEN = "nothing_to_reopen"
    VERDICT_NEEDS_ROUND = "verdict_needs_round"
    STATUS_NOT_OFFERED = "status_not_offered"


#: The spec's sentences, character for character (spec §LP-912). The em dashes are U+2014.
#:
#: `backward_move_needs_reason` INTERPOLATES ITS TARGET, and the spec's example does not — it writes
#: "Moving back to *To do* needs a short reason." for the one case S2-05 draws. A move from
#: *Sent to lender* to *Waiting on Borrower* is also backward, and naming "To do" there would be
#: simply wrong, so the label is a parameter and the To-do instance is what the test pins.
#: The `*…*` in the spec is markdown emphasis in prose, not part of the sentence: returning literal
#: asterisks would put a rendering artifact in front of a processor.
_BACKWARD_MOVE_NEEDS_REASON = "Moving back to {target} needs a short reason."
_INFO_ONLY_HAS_NO_STATUS = "This line is information from the lender — there is nothing to track."
_VERDICT_NEEDS_SOURCE = "Say where the lender cleared it (portal, email, phone) and on what date."
_STALE = "Someone else changed this condition — reload to see their change."

#: Mine. Written to name the next action rather than the broken field.
_WAITING_NEEDS_OWNER = "Say who you are waiting on."
_NOTHING_TO_REOPEN = "Only a condition the lender cleared or waived can be reopened."
_VERDICT_NEEDS_ROUND = (
    "A verdict that came from a round comparison or an underwriter's note has to name the round it "
    "came from."
)
_STATUS_NOT_OFFERED = "That status is not one this screen offers."

#: Our track in order, which is what makes a move "backward". `review` IS ABSENT ON PURPOSE (A4): it
#: stays in the database and is offered nowhere, so it has no rank and a move to it is refused by
#: `STATUS_NOT_OFFERED` rather than silently treated as forward.
_PREP_RANK: dict[ConditionPrepStatus, int] = {
    ConditionPrepStatus.TO_DO: 0,
    ConditionPrepStatus.WAITING: 1,
    ConditionPrepStatus.READY: 2,
    ConditionPrepStatus.WITH_UNDERWRITER: 3,
}

#: The labels the refusal sentence uses, matching what the screens show.
_PREP_LABEL: dict[ConditionPrepStatus, str] = {
    ConditionPrepStatus.TO_DO: "To do",
    ConditionPrepStatus.WAITING: "Waiting on someone",
    ConditionPrepStatus.READY: "Ready to send",
    ConditionPrepStatus.WITH_UNDERWRITER: "Sent to lender",
    ConditionPrepStatus.REVIEW: "Review",
}

#: The two lender statuses a verdict may assert, and the two a reopen may undo.
_VERDICT_STATUSES = (
    ConditionLenderStatus.CLEARED,
    ConditionLenderStatus.WAIVED,
    ConditionLenderStatus.NOT_CLEARED,
)
_REOPENABLE = (ConditionLenderStatus.CLEARED, ConditionLenderStatus.WAIVED)

#: The two sources the APP derives, which must name the sheet that showed it.
_DERIVED_SOURCES = (VerdictSourceKind.ROUND_COMPARISON, VerdictSourceKind.UNDERWRITER_NOTE)


class ConditionRefused(Exception):
    """A write this condition may not have, with the code and the sentence the UI shows.

    TWO FIELDS, WHERE THE SIBLINGS HAVE ONE. `RoundNotImportable` and friends carry `.reason` and the
    router turns it into a 409 message — enough while one row is refused for one reason. Bulk refuses
    rows individually and reports `{id, code, message}`, so the code has to survive as data rather than
    be re-derived from prose at the boundary.
    """

    def __init__(self, code: RefusalCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class BulkOutcome:
    """What a bulk write did: the rows it applied, and the rows it refused with reasons."""

    applied: list[UUID]
    refused: list[tuple[UUID, RefusalCode, str]]


def _refuse(code: RefusalCode, message: str) -> ConditionRefused:
    return ConditionRefused(code, message)


async def _lock_fresh(db: AsyncSession, condition: Condition, expected: datetime | None) -> None:
    """Lock the row, re-read it, THEN compare — so the stale check cannot race (LP-912 review).

    THE FIRST VERSION COMPARED A VALUE READ WITHOUT A LOCK, the same shape LP-909 uses for drafts.
    Two requests that both read `updated_at = U` both passed the check and both wrote, the second
    silently overwriting the first: the lost update the check exists to prevent, in exactly the
    concurrent case it is for. `SELECT … FOR UPDATE` makes the second request wait for the first to
    commit, and the refresh then hands it the NEW `updated_at`, which the check refuses as stale.

    The lock is held to the end of the caller's transaction. Every caller here commits straight after,
    and bulk's rows are locked one at a time in request order.
    """
    await db.refresh(condition, with_for_update=True)
    _guard_fresh(condition, expected)


def _guard_fresh(condition: Condition, expected: datetime | None) -> None:
    """Optimistic concurrency, the pattern LP-909 established for drafts.

    `None` IS "NO OPINION", NOT "FORCE". A caller that never read the row cannot echo its timestamp,
    and refusing those would make the field mandatory in a way the spec does not ask for. What makes
    the guard real is that the client always HAS the value — LP-911 put `updated_at` on
    `ConditionPublic` precisely so this check could fire at all, because until then every request would
    have sent `None` and the refusal could never have happened.
    """
    if expected is None:
        return
    if condition.updated_at != expected:
        raise _refuse(RefusalCode.STALE, _STALE)


def _guard_trackable(condition: Condition) -> None:
    """An information-only line has no preparation track at all (ADR-408).

    It asks for nothing, so there is nothing to prepare, nothing to wait on and nobody to send it to.
    The list shows "Information only" instead of a status control, and this is the same rule at the API
    so that a client which offers the control anyway is refused rather than obeyed.
    """
    if condition.info_only:
        raise _refuse(RefusalCode.INFO_ONLY_HAS_NO_STATUS, _INFO_ONLY_HAS_NO_STATUS)


def _event(
    condition: Condition,
    kind: ConditionEventKind,
    detail: dict[str, Any],
    *,
    actor_user_id: UUID | None,
) -> ConditionEvent:
    """One event for one change.

    `round_id` IS NULL FOR EVERY EVENT THIS MODULE WRITES, and that is correct rather than lazy: a
    status move and a verdict happen on a CONDITION, not on a sheet. The two exceptions carry a round
    inside their verdict (`round_comparison`, `underwriter_note`) because the lender's statement came
    off one, and that round id travels in the verdict where it belongs — as provenance, not as the
    event's own subject. `events_for_round` filters `condition_id IS NULL`, so these correctly do not
    appear in a round's history; `events_for_condition` is what renders them.
    """
    return ConditionEvent(
        company_id=condition.company_id,
        loan_file_id=condition.loan_file_id,
        condition_id=condition.id,
        kind=kind,
        actor_user_id=actor_user_id,
        detail=detail,
    )


# --------------------------------------------------------------------------- #
# Our track
# --------------------------------------------------------------------------- #


async def move_prep_status(
    db: AsyncSession,
    *,
    condition: Condition,
    payload: PrepStatusRequest,
    actor_user_id: UUID | None = None,
) -> None:
    """Move our track. Forward needs nothing; backward needs a reason. Flushes; caller commits.

    THE ASYMMETRY IS THE POINT (ADR-408). Forward is the work progressing and the move itself is the
    record. Backward means something went wrong, and the reason is the only record of WHAT — without it
    a file's history shows a condition bouncing between states with no account of why, which is worse
    than no history because it looks like one.
    """
    await _lock_fresh(db, condition, payload.expected_updated_at)
    _guard_trackable(condition)

    target = payload.to
    if target not in _PREP_RANK:
        # `review` (A4): in the database, offered nowhere.
        raise _refuse(RefusalCode.STATUS_NOT_OFFERED, _STATUS_NOT_OFFERED)

    current = condition.prep_status
    # A CURRENT STATUS OUTSIDE THE OFFERED FOUR IS TREATED AS THE START, not as an error. No writer
    # produces `review` today; if one ever did, refusing to move OFF it would strand the row in a state
    # the UI does not show — the opposite of what A4 intends.
    current_rank = _PREP_RANK.get(current, 0)
    backward = _PREP_RANK[target] < current_rank

    if backward and not (payload.reason or "").strip():
        # THE OWNER BY NAME WHEN THE MOVE IS TO WAITING (LP-912 review): the screens say "Waiting on
        # Title", so "Moving back to Waiting on someone" was the one place the sentence and the
        # status token disagreed.
        label = _PREP_LABEL[target]
        if target is ConditionPrepStatus.WAITING and payload.waiting_on is not None:
            label = f"Waiting on {payload.waiting_on.value.capitalize()}"
        raise _refuse(
            RefusalCode.BACKWARD_MOVE_NEEDS_REASON,
            _BACKWARD_MOVE_NEEDS_REASON.format(target=label),
        )

    if target is ConditionPrepStatus.WAITING and payload.waiting_on is None:
        raise _refuse(RefusalCode.WAITING_NEEDS_OWNER, _WAITING_NEEDS_OWNER)

    # A MOVE TO WHERE IT ALREADY IS CHANGES NOTHING, SO IT WRITES NOTHING (LP-912 review). The first
    # version wrote an event and reset `prep_status_changed_at` anyway, so a bulk "Waiting on Borrower"
    # over rows already waiting on the borrower restarted every clock the column exists to keep ("how
    # long has this sat with the borrower") and put a line in each history for nothing that happened.
    # Same status with a different owner, a note or a new sent date IS a change and is recorded.
    new_waiting_on = payload.waiting_on if target is ConditionPrepStatus.WAITING else None
    status_changed = target is not current
    if (
        not status_changed
        and new_waiting_on == condition.waiting_on
        and payload.note is None
        and payload.sent_at is None
    ):
        return

    now = datetime.now(UTC)
    detail: dict[str, Any] = {"from": current.value, "to": target.value}
    if backward:
        detail["reason"] = (payload.reason or "").strip()

    condition.prep_status = target
    if status_changed:
        condition.prep_status_changed_at = now
    # THE OWNER IS CLEARED WHEN LEAVING `waiting`, because "waiting on Title" is meaningless once we
    # are no longer waiting — and a stale value there would keep the row in the Owner filter's Title
    # group after the work moved on.
    condition.waiting_on = new_waiting_on
    if payload.waiting_on is not None and target is ConditionPrepStatus.WAITING:
        detail["waiting_on"] = payload.waiting_on.value
    if payload.note is not None:
        condition.prep_note = payload.note
    if target is ConditionPrepStatus.WITH_UNDERWRITER:
        condition.sent_at = payload.sent_at or now

    db.add(
        _event(
            condition, ConditionEventKind.CONDITION_PREP_MOVED, detail, actor_user_id=actor_user_id
        )
    )
    await db.flush()
    # Ids, codes and counts only — never the reason or the note, which are what a processor typed
    # about one borrower's file (ADR-405).
    logger.info(
        "condition_prep_moved",
        condition_id=str(condition.id),
        loan_file_id=str(condition.loan_file_id),
        to=target.value,
        backward=backward,
    )


# --------------------------------------------------------------------------- #
# The lender's track
# --------------------------------------------------------------------------- #


def verdict_record(
    payload: VerdictRequest, *, actor_user_id: UUID | None, at: datetime
) -> dict[str, Any]:
    """The verdict as it is stored — who said so, where, and on what date.

    ONE BUILDER, BECAUSE THREE THINGS WRITE A VERDICT. This endpoint, LP-915's confirm step
    (`round_comparison`), and the import's came-back hook (`underwriter_note`). Three hand-built dicts
    would drift in exactly the field an auditor later needs.

    `source_date` IS THE LENDER'S DATE AND `recorded_at` IS OURS, and keeping both is the whole point:
    "cleared on the 12th, recorded on the 14th" is a different fact from either date alone.
    """
    record: dict[str, Any] = {
        "status": payload.status.value,
        "source_kind": payload.source_kind.value,
        "source_date": payload.source_date.isoformat(),
        "recorded_at": at.isoformat(),
    }
    if payload.round_id is not None:
        record["round_id"] = str(payload.round_id)
    if payload.note is not None:
        record["note"] = payload.note
    if actor_user_id is not None:
        record["recorded_by"] = str(actor_user_id)
    return record


async def record_verdict(
    db: AsyncSession,
    *,
    condition: Condition,
    payload: VerdictRequest,
    actor_user_id: UUID | None = None,
    derived_allowed: bool = False,
) -> None:
    """Record what the lender said. The ONLY route to `cleared` or `waived`. Flushes; caller commits.

    OUR TRACK IS LEFT ALONE FOR `cleared` AND `waived`, DELIBERATELY (ADR-408). A condition that was
    *Sent to lender* and is now cleared was still sent, and rewriting our status to something tidier
    would erase what we did. The history says it; the row does not need to.

    `not_cleared` IS THE EXCEPTION, AND IT NOW MATCHES THE NOTE-DRIVEN CAME-BACK (ADR-408 as amended;
    LP-912 follow-up). The part 2 review found two routes to one status with opposite effects: the
    lender's dated note reset our track, while a processor recording that same refusal from a phone call
    left the condition sitting at *Sent to lender*. This function's own reopen argument settles which is
    right — leaving it there hides the condition from the list that would make somebody pick it up — so
    both routes reset `ready` / `with_underwriter` to `to_do`.

    AND BOTH LEAVE `to_do` / `waiting` ALONE, for the reason the import gives: a condition already being
    worked needs no correction, and resetting it would wipe the owner a processor chose.
    """
    await _lock_fresh(db, condition, payload.expected_updated_at)
    # An information-only line has no lender answer either: nothing was asked, so nothing can be
    # cleared. Same sentence as the prep track, because it is the same fact about the row.
    _guard_trackable(condition)

    if payload.status not in _VERDICT_STATUSES:
        raise _refuse(RefusalCode.STATUS_NOT_OFFERED, _STATUS_NOT_OFFERED)
    # THE APP'S OWN SOURCES ARE NOT A CLIENT'S TO CLAIM (LP-912 review). `round_comparison` and
    # `underwriter_note` say "the app read this off a sheet", and `came_back` is defined as a
    # `not_cleared` sourced to an underwriter note — so the first version let any client post
    # `{not_cleared, underwriter_note, <any uuid>}` and paint S2-08's amber *Came back* on a note that
    # never existed. Measured: 200, `came_back: true`, a round id that named nothing. A person records
    # what the lender said through portal, email or phone (S2-04); LP-915's confirm step and the import
    # are the only writers of the other two, and they pass `derived_allowed`.
    if payload.source_kind in _DERIVED_SOURCES and not derived_allowed:
        raise _refuse(RefusalCode.VERDICT_NEEDS_SOURCE, _VERDICT_NEEDS_SOURCE)
    if payload.source_kind in _DERIVED_SOURCES and payload.round_id is None:
        raise _refuse(RefusalCode.VERDICT_NEEDS_ROUND, _VERDICT_NEEDS_ROUND)
    if payload.round_id is not None:
        # AND THE ROUND MUST BE THIS FILE'S. A verdict's round is its provenance — "the sheet that
        # showed it" — and one naming another file's round, or another company's, points an auditor at
        # a sheet that says nothing about this condition.
        on_this_file = await db.scalar(
            only_active(
                select(ConditionRound.id).where(
                    ConditionRound.id == payload.round_id,
                    ConditionRound.loan_file_id == condition.loan_file_id,
                ),
                ConditionRound,
            )
        )
        if on_this_file is None:
            raise _refuse(RefusalCode.VERDICT_NEEDS_ROUND, _VERDICT_NEEDS_ROUND)

    now = datetime.now(UTC)
    lender_from = condition.lender_status
    prep_from = condition.prep_status
    condition.verdict = verdict_record(payload, actor_user_id=actor_user_id, at=now)
    condition.lender_status = payload.status
    condition.lender_status_changed_at = now
    # THE REFUSAL PUTS THE WORK BACK, exactly as the note-driven came-back does. Scoped to
    # `not_cleared`: a cleared or waived condition is finished, and moving our track there would erase
    # that it had been sent.
    if payload.status is ConditionLenderStatus.NOT_CLEARED and prep_from in (
        ConditionPrepStatus.READY,
        ConditionPrepStatus.WITH_UNDERWRITER,
    ):
        condition.prep_status = ConditionPrepStatus.TO_DO
        condition.prep_status_changed_at = now
        condition.waiting_on = None

    db.add(
        _event(
            condition,
            ConditionEventKind.CONDITION_VERDICT_RECORDED,
            {
                "status": payload.status.value,
                "source_kind": payload.source_kind.value,
                "source_date": payload.source_date.isoformat(),
                # BOTH FROM→TO PAIRS, NAMED AS `condition_came_back` NAMES THEM. The lender's answer
                # and its consequence for our work are one statement, so one event carries both — and a
                # reader composing a history line should not have to read two different vocabularies
                # depending on which route produced the refusal. `status` is kept beside them because it
                # is what existing readers already use.
                "lender_status_from": lender_from.value,
                "lender_status_to": payload.status.value,
                "prep_status_from": prep_from.value,
                "prep_status_to": condition.prep_status.value,
                **({"round_id": str(payload.round_id)} if payload.round_id else {}),
            },
            actor_user_id=actor_user_id,
        )
    )
    await db.flush()
    # THE SOURCE AND THE DATE ARE SAFE TO LOG AND THE NOTE IS NOT. A source kind is a closed
    # vocabulary and a date the lender printed names nobody; `verdict.note` is what a processor typed.
    logger.info(
        "condition_verdict_recorded",
        condition_id=str(condition.id),
        status=payload.status.value,
        source_kind=payload.source_kind.value,
    )


async def reopen(
    db: AsyncSession,
    *,
    condition: Condition,
    payload: ReopenRequest,
    actor_user_id: UUID | None = None,
) -> None:
    """Put a cleared or waived condition back to open, with a reason. Flushes; caller commits.

    THE OLD VERDICT IS NOT DELETED — it is already in `condition_events`, and this writes a
    `CONDITION_REOPENED` beside it. The row's `verdict` is cleared because it is "the current one", and
    a reopened condition has none; the history is where "it was cleared on the 12th and reopened on the
    20th" lives. That is what makes this safe for both cases it serves: a misclick, and a lender
    re-issuing something it had cleared.

    AND OUR TRACK GOES BACK TO `to_do`, unlike a verdict, which leaves it alone. The condition needs
    working again, so leaving it at *Sent to lender* would hide it from the only list that would make
    somebody pick it up.
    """
    await _lock_fresh(db, condition, payload.expected_updated_at)

    if condition.lender_status not in _REOPENABLE:
        raise _refuse(RefusalCode.NOTHING_TO_REOPEN, _NOTHING_TO_REOPEN)

    now = datetime.now(UTC)
    previous = condition.verdict or {}
    condition.lender_status = ConditionLenderStatus.OPEN
    condition.lender_status_changed_at = now
    condition.verdict = None
    condition.prep_status = ConditionPrepStatus.TO_DO
    condition.prep_status_changed_at = now
    condition.waiting_on = None

    db.add(
        _event(
            condition,
            ConditionEventKind.CONDITION_REOPENED,
            {
                "reason": payload.reason.strip(),
                # WHAT IS BEING OVERRULED, as provenance rather than prose: the source and date of the
                # verdict this undoes, so the history line can say which one was reopened. The
                # verdict's own `note` is not copied — it is the processor's words and belongs where it
                # already is.
                "overruled_source_kind": previous.get("source_kind"),
                "overruled_source_date": previous.get("source_date"),
            },
            actor_user_id=actor_user_id,
        )
    )
    await db.flush()
    logger.info(
        "condition_reopened",
        condition_id=str(condition.id),
        overruled_source_kind=previous.get("source_kind"),
    )


# --------------------------------------------------------------------------- #
# Who it is waiting on
# --------------------------------------------------------------------------- #


async def set_owner(
    db: AsyncSession,
    *,
    condition: Condition,
    payload: OwnerRequest,
    actor_user_id: UUID | None = None,
) -> None:
    """Set or clear the manual owner override (A2). Flushes; caller commits.

    THE PROCESSOR'S CHOICE OUTRANKS EVERY GUESS, which is A2's whole content: a `TC:` prefix, a
    heading and a code-map default are evidence of varying quality, and a person deciding is not a
    guess at all. Clearing the override restores whatever was inferred rather than leaving the row
    ownerless, which is why `owner=None` means "back to the hint" and not "nobody".

    NEITHER `owner_hint` NOR `owner_hint_source` IS TOUCHED. The hint is a fact about what the sheet
    said and stays true; the override is a separate fact about what we decided. Overwriting the hint
    would destroy the better record of where the guess came from — the same reasoning that stops the
    import overwriting a prefix hint with a code-map default.

    THAT INCLUDES THE SOURCE, AND AN EARLIER DRAFT OF THIS FUNCTION GOT IT WRONG. It set
    `owner_hint_source = manual`, which threw away "the code map said processor", and then rebuilt a
    plausible value when the override was cleared. `services/conditions.py::effective_owner_source`
    derives `manual` from the override instead, so there is nothing here to overwrite and nothing to
    reconstruct.
    """
    await _lock_fresh(db, condition, payload.expected_updated_at)

    before = condition.owner_override
    if payload.owner == before:
        # NOTHING CHANGES, SO NOTHING IS WRITTEN (LP-912 review) — see `move_prep_status`.
        return
    condition.owner_override = payload.owner

    db.add(
        _event(
            condition,
            ConditionEventKind.CONDITION_OWNER_CHANGED,
            {
                "from": before.value if before else None,
                "to": payload.owner.value if payload.owner else None,
                "hint": condition.owner_hint.value,
            },
            actor_user_id=actor_user_id,
        )
    )
    await db.flush()
    logger.info(
        "condition_owner_changed",
        condition_id=str(condition.id),
        to=payload.owner.value if payload.owner else None,
    )


# --------------------------------------------------------------------------- #
# Many at once
# --------------------------------------------------------------------------- #


async def apply_bulk(
    db: AsyncSession,
    *,
    loan_file_id: UUID,
    payload: BulkRequest,
    actor_user_id: UUID | None = None,
) -> BulkOutcome:
    """Apply one write to many conditions, refusing the rows that may not have it.

    IT APPLIES WHAT IT CAN AND REPORTS THE REST, rather than refusing the whole batch (spec §LP-912).
    A processor who selects eleven rows and marks them cleared should not lose the ten that were fine
    because one is information-only — and the UI's line is "4 marked cleared · 1 skipped: information
    only", which needs both halves.

    EACH ROW IS GUARDED INDIVIDUALLY, INCLUDING FRESHNESS. `expected_updated_at` is not sent per row by
    the bulk dialog, so it is normally `None` here and the stale check is a no-op — but the per-row
    refusal shape means a future caller CAN send it, and a row that moved under the processor is then
    reported rather than overwritten.

    ROWS ARE LOADED COMPANY-SCOPED THROUGH THE FILE, so an id belonging to another tenant is simply not
    found and is refused as such rather than acted on. That is the same property `get_scoped_condition`
    gives the single-row routes, expressed for a list.
    """
    rows = (
        (
            await db.execute(
                only_active(
                    select(Condition).where(
                        Condition.loan_file_id == loan_file_id,
                        Condition.id.in_(payload.condition_ids),
                    ),
                    Condition,
                )
            )
        )
        .scalars()
        .all()
    )
    found = {row.id: row for row in rows}

    applied: list[UUID] = []
    refused: list[tuple[UUID, RefusalCode, str]] = []

    for condition_id in payload.condition_ids:
        condition = found.get(condition_id)
        if condition is None:
            # NOT AN ERROR FOR THE WHOLE BATCH. An id that is not on this file — deleted meanwhile, or
            # another tenant's — is one refused row, and the message says only that it is not there.
            refused.append((condition_id, RefusalCode.STALE, _STALE))
            continue
        try:
            await _apply_one(db, condition=condition, payload=payload, actor_user_id=actor_user_id)
        except ConditionRefused as refusal:
            refused.append((condition_id, refusal.code, refusal.message))
        else:
            applied.append(condition_id)

    logger.info(
        "conditions_bulk_applied",
        loan_file_id=str(loan_file_id),
        action=payload.action.value,
        requested=len(payload.condition_ids),
        applied=len(applied),
        refused=len(refused),
    )
    return BulkOutcome(applied=applied, refused=refused)


async def _apply_one(
    db: AsyncSession,
    *,
    condition: Condition,
    payload: BulkRequest,
    actor_user_id: UUID | None,
) -> None:
    """One row of a bulk write, routed to the same function the single-row endpoint calls.

    THROUGH THE SAME SERVICE, NEVER A PARALLEL IMPLEMENTATION. If bulk had its own copy of the
    backward-move rule, "needs a reason" would be enforceable one row at a time and not eleven — which
    is precisely the shape of hole that makes a bulk action the way to get round a guard.
    """
    if payload.action is BulkAction.PREP_STATUS:
        if payload.to is None:
            raise _refuse(RefusalCode.STATUS_NOT_OFFERED, _STATUS_NOT_OFFERED)
        await move_prep_status(
            db,
            condition=condition,
            payload=PrepStatusRequest(
                to=payload.to,
                waiting_on=payload.waiting_on,
                reason=payload.reason,
                note=payload.note,
                sent_at=payload.sent_at,
                expected_updated_at=payload.expected_updated_at,
            ),
            actor_user_id=actor_user_id,
        )
        return

    if payload.action is BulkAction.VERDICT:
        if payload.status is None or payload.source_kind is None or payload.source_date is None:
            # THE SPEC'S SENTENCE, because this is exactly what it is for: a verdict with no source or
            # no date is the one refusal the screen is built to prevent.
            raise _refuse(RefusalCode.VERDICT_NEEDS_SOURCE, _VERDICT_NEEDS_SOURCE)
        await record_verdict(
            db,
            condition=condition,
            payload=VerdictRequest(
                status=payload.status,
                source_kind=payload.source_kind,
                source_date=payload.source_date,
                round_id=payload.round_id,
                note=payload.note,
                expected_updated_at=payload.expected_updated_at,
            ),
            actor_user_id=actor_user_id,
        )
        return

    await set_owner(
        db,
        condition=condition,
        payload=OwnerRequest(owner=payload.owner, expected_updated_at=payload.expected_updated_at),
        actor_user_id=actor_user_id,
    )


# --------------------------------------------------------------------------- #
# The came-back hook (A1), for the import to call
# --------------------------------------------------------------------------- #


def normalise_note_text(text: str) -> str:
    """A note's text for COMPARISON only — never for display (survey §5.2, R8).

    THE READER KEEPS WHATEVER SPACING ARRIVES. `_NOTE` captures `(.*?)` and only strips the ends, and a
    browser copy of a portal need not space a note the way the lender's PDF does — measured: a paste
    gives `'Not in  Upload'` where the PDF gives `'Not in Upload'`. Comparing raw text therefore fails
    to recognise the same note and fires a false *Came back*, which reopens a condition on the lender's
    behalf. This is the folding `note_stripped` already uses for wording.
    """
    return " ".join(text.lower().split())


def came_back_verdict(*, note_date: date, round_id: UUID, at: datetime) -> dict[str, Any]:
    """The verdict a came-back records: the lender's own note, on the note's date (A1).

    ITS PROVENANCE IS WHAT MAKES THE EVENT LEGITIMATE, and the append-only guard's question is now
    phrased around exactly that: could a reader infer the lender answered WITHOUT the row saying where
    the lender said it? `condition_came_back` does state an answer — "not satisfied" — so it is allowed
    only because it carries `source_kind: underwriter_note` and the note's date. A test asserts this
    detail, because without it the event becomes the bare claim ADR-404 forbids.
    """
    return {
        "status": ConditionLenderStatus.NOT_CLEARED.value,
        "source_kind": VerdictSourceKind.UNDERWRITER_NOTE.value,
        "source_date": note_date.isoformat(),
        "round_id": str(round_id),
        "recorded_at": at.isoformat(),
    }


__all__ = [
    "BulkOutcome",
    "ConditionRefused",
    "RefusalCode",
    "apply_bulk",
    "came_back_verdict",
    "move_prep_status",
    "normalise_note_text",
    "record_verdict",
    "reopen",
    "set_owner",
    "verdict_record",
]
