"""What changed when a round was imported (LP-915, screens S2-06 / S2-07 / S2-08 / S2-10).

THE COMPARISON IS COMPUTED ONCE AND SAVED, which is the spec's requirement rather than an
optimisation: "opening the panel later shows the same result". A comparison recomputed on each visit
would answer a different question every time the file moved underneath it — a condition cleared after
the import would quietly stop appearing as "probably cleared", and a panel a processor half-confirmed
would change shape between visits. It is recomputed only when a round's completeness changes (A7),
which is the one edit that legitimately changes what "absent from this sheet" means.

IT COMPARES AGAINST EVERYTHING OPEN BEFORE THIS ROUND, NOT AGAINST THE PREVIOUS ROUND (A6). A
condition can skip a sheet and return; comparing round 3 with round 2 alone would call such a
condition "new". The set is every condition on the file that was open or came back, came off a sheet,
and is not superseded.

IT STORES IDS, NEVER THE LENDER'S WORDING. S2-08 draws the reworded pair's old and new text, but the
screen already holds both conditions — it resolves them itself. What makes this column NPI is
`letter_changes`, which carries verified income, verified assets and the housing/debt ratios: facts
about a borrower's finances, derived from `header`, which `readonly.condition_rounds` already drops.

NOTHING HERE DECIDES ANYTHING. "Probably cleared" is a SUGGESTION with a button; only a recorded
verdict may say the lender cleared a condition (ADR-404), and `confirm_probably_cleared` is what turns
a suggestion into one. This module computes and saves; it never sets a lender status.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.condition import Condition, ConditionLenderStatus, ConditionOrigin
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import (
    ConditionRound,
    ConditionRoundCompleteness,
    ConditionRoundStatus,
)
from app.models.helpers import only_active
from app.services.condition_plan import carry_plan
from app.services.conditions import APPEARED_ON

logger = structlog.get_logger(__name__)

#: The lender statuses that count as "still owed an answer" for A6's comparison set.
#:
#: `not_cleared` IS IN IT. A condition the lender refused is emphatically still open work — and one
#: that came back on THIS round was open before it, which is the question this set answers.
_OPEN_BEFORE = (ConditionLenderStatus.OPEN, ConditionLenderStatus.NOT_CLEARED)

#: S2-10's callout, and the reason `switch_completeness` writes when suggestions are withdrawn.
#:
#: ONE CONSTANT BECAUSE TWO PATHS PRODUCE IT. An import of a partial round and a switch back to
#: *Just some* must put the same words on the same panel; two literals would drift the moment one was
#: reworded, and the screen shows this string as-is (spec §6 rule 5).
_PARTIAL_NO_SUGGESTIONS = "This round was just some conditions, so nothing is suggested as cleared."

#: The loan facts the letter-changes block reads, in the order the design lists them.
#:
#: A FIXED LIST RATHER THAN "EVERY KEY THAT DIFFERS". The sheet carries about thirty facts, most of
#: which never move and several of which are restatements. The spec names these; showing every
#: difference would bury the note rate under the submission date.
_FACTS: tuple[tuple[str, str], ...] = (
    ("Note Rate", "note rate"),
    ("Housing / Debt Ratios", "housing / debt ratios"),
    ("Verified Income", "verified income"),
    ("Verified Assets", "verified assets"),
    ("Max Funds to Close", "max funds to close"),
    ("Rate Lock Exp", "rate lock expiry"),
    ("Must Not Close Before", "must not close before"),
    ("Must Fund By", "must fund by"),
)

#: The expiry table's keys, in the order the sheet prints them.
_EXPIRIES: tuple[str, ...] = (
    "close_by",
    "appraisal",
    "asset",
    "cpl",
    "credit",
    "income",
    "insurance",
    "other",
    "payoff",
    "short_sale",
    "title",
    "vob",
)


@dataclass(frozen=True)
class LetterChange:
    """One value the lender changed between two sheets.

    `old` AND `new` ARE BOTH OPTIONAL AND A MISSING ONE IS NEVER GUESSED. Round 1's `Rate Lock Exp`
    is genuinely blank and round 2's is 09/30/2026 — "— → 09/30/2026" is the truthful rendering, and
    inventing a prior value would put a date in front of a processor that no sheet ever carried.
    """

    label: str
    old: str | None
    new: str | None


@dataclass
class RoundComparison:
    """What one import changed. Saved to `condition_rounds.comparison`.

    EVERY CONDITION IS AN ID. See the module docstring: the screen resolves wording from rows it
    already has, so this blob never carries a word the lender wrote.
    """

    round_id: UUID
    round_number: int | None
    #: How many conditions were open before this round — the panel's "Compared with the N conditions
    #: that were open before it."
    compared_with: int
    new: list[UUID] = field(default_factory=list)
    still_open: list[UUID] = field(default_factory=list)
    came_back: list[UUID] = field(default_factory=list)
    #: `(old, new)` — the condition this sheet may have reworded, and the one it created.
    reworded: list[tuple[UUID, UUID]] = field(default_factory=list)
    probably_cleared: list[UUID] = field(default_factory=list)
    letter_changes: list[LetterChange] = field(default_factory=list)
    #: Why no suggestions were produced, or None when they were. Shown as the panel's callout.
    no_suggestions_reason: str | None = None
    #: `{condition: (from, to)}` for each came-back that moved OUR track — S2-08's "our status moved
    #: from Sent to lender back to To do" (LP-915 review). Read off the round's own
    #: `CONDITION_CAME_BACK` events, which this function already walks, so the panel needs no history
    #: fetch per condition. Statuses only; nothing the lender wrote.
    came_back_moves: dict[UUID, tuple[str, str]] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        """The stored shape. Ids as strings, because JSONB holds no UUIDs."""
        return {
            "round_id": str(self.round_id),
            "round_number": self.round_number,
            "compared_with": self.compared_with,
            "new": [str(value) for value in self.new],
            "still_open": [str(value) for value in self.still_open],
            "came_back": [str(value) for value in self.came_back],
            "reworded": [[str(old), str(new)] for old, new in self.reworded],
            "probably_cleared": [str(value) for value in self.probably_cleared],
            "letter_changes": [
                {"label": change.label, "old": change.old, "new": change.new}
                for change in self.letter_changes
            ],
            "no_suggestions_reason": self.no_suggestions_reason,
            "came_back_moves": {
                str(condition_id): [before, after]
                for condition_id, (before, after) in self.came_back_moves.items()
            },
        }


def _as_text(value: object) -> str | None:
    """A fact or a date as the panel prints it, or None when the sheet did not carry it.

    IT MUST HANDLE A DATE AND AN ISO STRING ALIKE, AND THE FIRST VERSION HANDLED ONLY THE DATE.
    `expiry_dates` is a JSONB column: the reader puts `date` objects in, and everything that reads
    them back off a round gets `"2026-10-30"`. So the `isinstance(value, date)` branch fired for a
    freshly parsed sheet and never for a stored one — and the panel printed `note rate 6.374%` beside
    `close by expiry 2026-10-30`, two date formats in one list, depending only on whether the value
    had been round-tripped through the database.

    Measured rather than reasoned about: the letter-changes test failed on
    `('2026-10-30', '11/03/2026')` — the OLD round read from JSONB, the NEW one still in memory.
    """
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return f"{value.month:02d}/{value.day:02d}/{value.year}"
    text = str(value)
    # `2026-10-30` → `10/30/2026`. Narrow on purpose: only a bare ISO date is reinterpreted, so a
    # fact that merely contains digits ("32.51% / 40.36%") is never rewritten.
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        try:
            parsed = date.fromisoformat(text)
        except ValueError:
            return text
        return f"{parsed.month:02d}/{parsed.day:02d}/{parsed.year}"
    return text


def _uw_team(header: dict[str, Any] | None) -> str | None:
    """The `UW Team` name out of `header["lender_team"]`.

    A LIST OF ROLES, NOT A DICT. The reader stores `[{role, name, phone_ext}, …]`, so the team is
    found by its role rather than by position — a sheet that omits the AE would otherwise shift it.
    """
    for member in (header or {}).get("lender_team") or []:
        if isinstance(member, dict) and member.get("role") == "UW Team":
            return _as_text(member.get("name"))
    return None


def letter_changes(previous: ConditionRound | None, current: ConditionRound) -> list[LetterChange]:
    """Only the values that MOVED, old → new (spec §LP-915).

    NOTHING IS SHOWN WHEN THERE IS NOTHING TO COMPARE. A paste carries no letter, so a round without
    a header produces no changes rather than a list of every value appearing from nowhere — which is
    what S2-10's "a paste has no letter details, so there are no letter changes to show" describes.
    """
    if previous is None or previous.header is None or current.header is None:
        return []

    before = (previous.header or {}).get("loan_facts") or {}
    after = (current.header or {}).get("loan_facts") or {}

    changes: list[LetterChange] = []
    for key, label in _FACTS:
        old, new = _as_text(before.get(key)), _as_text(after.get(key))
        if old != new:
            changes.append(LetterChange(label=label, old=old, new=new))

    old_team, new_team = _uw_team(previous.header), _uw_team(current.header)
    if old_team != new_team:
        changes.append(LetterChange(label="UW team", old=old_team, new=new_team))

    old_expiry = previous.expiry_dates or {}
    new_expiry = current.expiry_dates or {}
    for key in _EXPIRIES:
        old, new = _as_text(old_expiry.get(key)), _as_text(new_expiry.get(key))
        if old != new:
            changes.append(LetterChange(label=f"{key.replace('_', ' ')} expiry", old=old, new=new))

    return changes


async def _events_on_round(db: AsyncSession, *, round_id: UUID) -> list[ConditionEvent]:
    """The CONDITION-level events this round wrote — the opposite filter to `events_for_round`.

    That function takes `condition_id IS NULL` because a round's HISTORY panel must not render thirty
    "a condition was added" lines. This is the other half of the same table: which conditions this
    sheet actually touched, which is what every outcome below is derived from.
    """
    stmt = (
        select(ConditionEvent)
        .where(ConditionEvent.round_id == round_id, ConditionEvent.condition_id.is_not(None))
        .order_by(ConditionEvent.occurred_at.asc(), ConditionEvent.id.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def _open_before(
    db: AsyncSession, *, loan_file_id: UUID, created_here: set[UUID]
) -> list[Condition]:
    """A6's set: every condition that was open before this round.

    `origin = sheet` EXCLUDES HAND-TYPED CONDITIONS (A5). A processor's own note-to-self is not
    something the lender's next sheet can be silent about, so its absence is not evidence of anything.

    NOT SUPERSEDED, because a replaced condition's successor carries the work; suggesting the old half
    as cleared would clear a row that already points elsewhere.
    """
    stmt = select(Condition).where(
        Condition.loan_file_id == loan_file_id,
        Condition.origin == ConditionOrigin.SHEET,
        Condition.superseded_by_id.is_(None),
        Condition.lender_status.in_(_OPEN_BEFORE),
    )
    rows = (await db.execute(only_active(stmt, Condition))).scalars().all()
    # CREATED BY THIS ROUND IS NOT "OPEN BEFORE IT". Excluded here rather than in the query because
    # the ids come from this round's events, not from a column.
    return [row for row in rows if row.id not in created_here]


async def _previous_imported(
    db: AsyncSession, *, loan_file_id: UUID, before_number: int | None
) -> ConditionRound | None:
    """The imported round before this one, by number. None when this is the first."""
    if before_number is None:
        return None
    stmt = select(ConditionRound).where(
        ConditionRound.loan_file_id == loan_file_id,
        ConditionRound.status == ConditionRoundStatus.IMPORTED,
        ConditionRound.round_number < before_number,
    )
    stmt = only_active(stmt, ConditionRound).order_by(ConditionRound.round_number.desc())
    return (await db.execute(stmt)).scalars().first()


async def confirm_probably_cleared(
    db: AsyncSession,
    *,
    round_: ConditionRound,
    condition_ids: list[UUID],
    actor_user_id: UUID | None = None,
    resolve_rest: bool = True,
) -> list[UUID]:
    """Turn ticked suggestions into recorded verdicts (S2-07). Flushes; caller commits.

    THIS IS THE ONLY PLACE A `round_comparison` VERDICT IS WRITTEN, and it is why the suggestion is
    not a status. Nothing the comparison computed touched a lender status; a person ticking a box and
    pressing **Confirm N as cleared** is what records one — "the app proposes, and the processor
    confirms" (spec §6 rule 1).

    ONLY IDS THIS ROUND ACTUALLY SUGGESTED ARE ACCEPTED. The saved comparison is the authority, so a
    caller cannot clear an arbitrary condition through this door by naming it — the derived source
    `round_comparison` asserts the sheet showed it, and that assertion has to be true.

    THE DATE IS THE SHEET'S, NEVER TODAY'S. `date_printed` when the letter carried one, else the
    round's date. `VerdictRequest.source_date` has no default precisely so this choice is made
    somewhere a reader can see it.

    UNTICKED ONES STAY OPEN AND LOSE THE SUGGESTION (spec §LP-915), WHEN THE PANEL CONFIRMS. The
    panel is the processor deciding the whole round, so `resolve_rest` is true there.

    FROM THE DETAIL SHEET IT IS ONE CONDITION (LP-915 review). "The suggestion is per condition, so
    she can also confirm one from the detail sheet", and *Not now* keeps the rest pending "until she
    decides". The first version resolved the whole round on a one-row confirm, so confirming `7086`
    from its sheet silently withdrew the other four questions. The sheet sends `resolve_rest: false`.
    """
    from app.schemas.condition import VerdictRequest, VerdictSourceKind

    saved = round_.comparison or {}
    suggested = {UUID(value) for value in saved.get("probably_cleared", [])}
    ticked = [value for value in condition_ids if value in suggested]
    # A STALE PANEL MUST NOT WITHDRAW EVERYTHING AND RECORD NOTHING. The suggestions are resolved
    # either way once this runs, so a request whose ids are ALL already resolved — a second tab, a
    # double press, a reload after someone else confirmed — would clear the pending list and write no
    # verdict, losing the questions without answering one. Refusing keeps the panel as it is.
    if not ticked:
        raise RoundComparisonRefused(
            f"Round {round_.round_number} has no pending suggestion among those conditions. "
            "Reload the round to see the current panel."
        )

    confirmed: list[UUID] = []
    if ticked:
        rows = (
            (
                await db.execute(
                    only_active(select(Condition).where(Condition.id.in_(ticked)), Condition)
                )
            )
            .scalars()
            .all()
        )
        payload = VerdictRequest(
            status=ConditionLenderStatus.CLEARED,
            source_kind=VerdictSourceKind.ROUND_COMPARISON,
            source_date=round_.date_printed or round_.round_date,
            round_id=round_.id,
        )
        # THROUGH `record_verdict`, NOT BY SETTING THE COLUMN. Every guard it carries applies here —
        # an information-only line is still refused, and each row gets its own event.
        from app.services.condition_status import record_verdict

        for condition in rows:
            # ALREADY ANSWERED IS SKIPPED, NEVER OVERWRITTEN. `record_verdict` withdraws a suggestion
            # when any verdict lands, so this should not happen; it is here so a stale saved list can
            # never replace a processor's recorded answer with an inferred one.
            if (
                condition.lender_status not in _OPEN_BEFORE
                or condition.superseded_by_id is not None
            ):
                continue
            await record_verdict(
                db,
                condition=condition,
                payload=payload,
                actor_user_id=actor_user_id,
                derived_allowed=True,
            )
            confirmed.append(condition.id)

    # Resolved: the whole round from the panel, or only the ones named from the detail sheet.
    # `record_verdict` has already withdrawn the confirmed ids, so read the CURRENT list.
    current = round_.comparison or {}
    remaining = (
        []
        if resolve_rest
        else [
            value
            for value in current.get("probably_cleared") or []
            if UUID(str(value)) not in set(ticked)
        ]
    )
    round_.comparison = {**current, "probably_cleared": remaining}
    await db.flush()
    logger.info(
        "condition_suggestions_confirmed",
        round_id=str(round_.id),
        offered=len(suggested),
        confirmed=len(confirmed),
    )
    return confirmed


class RoundComparisonRefused(Exception):
    """A comparison decision cannot be applied, with the reason a processor can act on.

    THE SAME SHAPE AS `RoundNotImportable` AND ITS FOUR SIBLINGS, deliberately: the round exists and
    the caller may see it, so the route answers 409 with `exc.reason` and the screen shows that
    sentence as-is. A second refusal vocabulary for the same kind of "the round's state says no"
    would leave the client branching on two.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def confirm_reworded(
    db: AsyncSession,
    *,
    round_: ConditionRound,
    old_id: UUID,
    new_id: UUID,
    same: bool,
    actor_user_id: UUID | None = None,
) -> bool:
    """Answer S2-08's *Same condition* / *Different conditions*. Flushes; caller commits.

    NOTHING HAPPENS UNTIL SHE CHOOSES, WHICH IS WHY THE IMPORT ONLY RECORDED A QUESTION. The import
    wrote `possible_match` — same code, different wording — and made no decision; this is the click.
    *Same* marks the old one **Replaced** and points it at its successor. *Different* leaves both
    conditions exactly as they are.

    THE PAIR IS RESOLVED EITHER WAY, AND THAT IS A DECISION I TOOK WITHOUT THE PRODUCT OWNER. The
    spec says "Different leaves both", which is true of the two CONDITIONS; it does not say what
    becomes of the question. Left pending, the panel would ask again on every visit and there would be
    no way to answer "these are different" at all. `confirm_probably_cleared` already resolves the
    suggestions it was not given, for the same reason, so this follows the behaviour beside it.

    ONLY A PAIR THIS ROUND ACTUALLY OFFERED IS ACCEPTED. The saved comparison is the authority, so a
    caller cannot supersede an arbitrary condition by naming two ids — being replaced hides a row from
    the working list, and nothing but the sheet's own evidence may cause it.
    """
    saved = round_.comparison or {}
    offered = {
        (str(pair[0]), str(pair[1]))
        for pair in saved.get("reworded") or []
        if isinstance(pair, (list, tuple)) and len(pair) == 2
    }
    if (str(old_id), str(new_id)) not in offered:
        raise RoundComparisonRefused(
            f"Round {round_.round_number} did not suggest those two conditions as a reworded pair."
        )

    if same:
        rows = (
            (
                await db.execute(
                    only_active(
                        select(Condition).where(
                            Condition.id.in_([old_id, new_id]),
                            # SCOPED THROUGH THE ROUND'S FILE, so a pair naming another file's or
                            # another tenant's condition is simply not found.
                            Condition.loan_file_id == round_.loan_file_id,
                        ),
                        Condition,
                    )
                )
            )
            .scalars()
            .all()
        )
        by_id = {row.id: row for row in rows}
        old, new = by_id.get(old_id), by_id.get(new_id)
        if old is None or new is None:
            raise RoundComparisonRefused(
                "One of those two conditions is no longer on this file. Reload the round."
            )
        if old.superseded_by_id is not None:
            raise RoundComparisonRefused(
                "That condition has already been replaced. Reload the round to see the current pair."
            )

        now = datetime.now(UTC)
        lender_from = old.lender_status
        old.superseded_by_id = new.id
        old.lender_status = ConditionLenderStatus.SUPERSEDED
        old.lender_status_changed_at = now
        # OUR TRACK IS LEFT ALONE, exactly as a verdict leaves it. A condition that was *Sent to
        # lender* before it was reworded still was, and rewriting that would erase what we did — the
        # history and `superseded_by_id` are where "the work moved to this other row" is recorded.
        db.add(
            ConditionEvent(
                company_id=old.company_id,
                loan_file_id=old.loan_file_id,
                condition_id=old.id,
                round_id=round_.id,
                kind=ConditionEventKind.CONDITION_SUPERSEDED,
                actor_user_id=actor_user_id,
                # IDS AND STATUSES, NEVER THE TWO WORDINGS — the pair is what the lender wrote.
                detail={
                    "superseded_by_id": str(new.id),
                    "lender_status_from": lender_from.value,
                    "lender_status_to": ConditionLenderStatus.SUPERSEDED.value,
                    "round_number": round_.round_number,
                },
            )
        )
        # LP-920 — the replaced condition hands its plan to the new one, for her to confirm (§4a 3).
        await carry_plan(db, from_condition=old, to_condition=new, actor_user_id=actor_user_id)

    remaining = [
        pair
        for pair in saved.get("reworded") or []
        if not (
            isinstance(pair, (list, tuple))
            and len(pair) == 2
            and (str(pair[0]), str(pair[1])) == (str(old_id), str(new_id))
        )
    ]
    # A NEW dict rather than a mutated one — SQLAlchemy does not track in-place JSONB mutation, so an
    # updated key on the existing object would simply not be written. Same note as `compare_round`.
    round_.comparison = {**saved, "reworded": remaining}
    await db.flush()
    logger.info(
        "condition_reworded_resolved",
        round_id=str(round_.id),
        same=same,
        pairs_left=len(remaining),
    )
    return same


async def switch_completeness(
    db: AsyncSession,
    *,
    round_: ConditionRound,
    completeness: ConditionRoundCompleteness,
    expected_updated_at: datetime | None = None,
    actor_user_id: UUID | None = None,
) -> ConditionRound:
    """Change an imported round's completeness, and follow the consequences (A7). Caller commits.

    THIS IS THE ONE EDIT THAT LEGITIMATELY CHANGES WHAT "ABSENT FROM THIS SHEET" MEANS, which is why
    the comparison — computed once and saved everywhere else — is recomputed here. A sheet pasted as
    *Just some* claimed to list nothing in particular; the same sheet marked *Full list* claims to
    list everything, and absence becomes evidence.

    *Just some → Full list* RUNS THE COMPARISON, as the spec states outright.

    *Full list → Just some* WITHDRAWS UNCONFIRMED SUGGESTIONS AND RECOMPUTES NOTHING. Confirmed
    verdicts stay: they are the processor's recorded decision, and only the lender clears, so nothing
    here may unpick one (ADR-404). Recomputing would ALSO be wrong rather than merely unnecessary —
    `_open_before` reads current statuses, so after five confirms it would find five fewer conditions
    open and the panel's "Compared with the 11 conditions that were open before it" would quietly
    become 6. That number is a fact about the past, which is what "computed once and saved" protects.

    IMPORTED ROUNDS ONLY. A draft's completeness is part of what the review screen is still editing,
    and `update_draft` already carries it; a second door onto the same field would let a round be
    switched out from under that screen.
    """
    if round_.status is not ConditionRoundStatus.IMPORTED:
        raise RoundComparisonRefused(
            "Only an imported round's completeness can be changed. This round is "
            f"{round_.status.value.replace('_', ' ')}."
        )
    # EXACT, AND OPTIONAL FOR THE SAME REASON `update_draft` GIVES: `None` means "no opinion", and any
    # modification bumps `updated_at`, so a tab whose round was re-imported or switched by someone
    # else is refused rather than overwriting a decision it never saw.
    if expected_updated_at is not None and expected_updated_at != round_.updated_at:
        raise RoundComparisonRefused(
            "Someone else changed this round while you were looking at it. Reload to see their "
            "version before switching it."
        )

    before = round_.completeness
    if before is completeness:
        # NOTHING CHANGES, SO NOTHING IS WRITTEN — and in particular no event and no recompute. The
        # same rule `move_prep_status` and `set_owner` keep: a switch to where it already is would
        # otherwise put a line in the history for nothing that happened, and rerun the comparison.
        return round_

    round_.completeness = completeness
    withdrawn = 0
    if completeness is ConditionRoundCompleteness.FULL:
        await compare_round(db, round_=round_, actor_user_id=actor_user_id)
    else:
        saved = round_.comparison or {}
        withdrawn = len(saved.get("probably_cleared") or [])
        round_.comparison = {
            **saved,
            "probably_cleared": [],
            "no_suggestions_reason": _PARTIAL_NO_SUGGESTIONS,
        }

    db.add(
        ConditionEvent(
            company_id=round_.company_id,
            loan_file_id=round_.loan_file_id,
            round_id=round_.id,
            kind=ConditionEventKind.ROUND_COMPLETENESS_CHANGED,
            actor_user_id=actor_user_id,
            detail={
                "completeness_from": before.value,
                "completeness_to": completeness.value,
                "round_number": round_.round_number,
                # A COUNT, NOT THE CODES — what was withdrawn is derivable from the round, and the
                # history line only needs to say how many questions stopped being asked.
                "suggestions_withdrawn": withdrawn,
            },
        )
    )
    await db.flush()
    logger.info(
        "condition_round_completeness_changed",
        round_id=str(round_.id),
        completeness_from=before.value,
        completeness_to=completeness.value,
        suggestions_withdrawn=withdrawn,
    )
    return round_


async def compare_round(
    db: AsyncSession, *, round_: ConditionRound, actor_user_id: UUID | None = None
) -> RoundComparison:
    """Compare an imported round with everything that was open before it, and SAVE the result.

    Flushes; the caller commits — as every service here does.

    WRITES EXACTLY ONE `round_compared` EVENT (spec §6 rule 4). The event states that a comparison was
    computed, which is a fact about us rather than a claim about the lender — the append-only guard
    permits it for that reason, and nothing in it says a condition was cleared.
    """
    events = await _events_on_round(db, round_id=round_.id)

    created_here: set[UUID] = set()
    reworded: list[tuple[UUID, UUID]] = []
    came_back: set[UUID] = set()
    came_back_moves: dict[UUID, tuple[str, str]] = {}
    on_sheet: set[UUID] = set()

    for event in events:
        condition_id = event.condition_id
        if condition_id is None:
            continue
        if event.kind in APPEARED_ON:
            on_sheet.add(condition_id)
        if event.kind is ConditionEventKind.CONDITION_CREATED:
            created_here.add(condition_id)
            # THE REWORDED PAIR'S ONLY INPUT. `possible_match` is written by the import for a row
            # with the SAME code and a DIFFERENT fingerprint, pointing at the oldest such condition —
            # an id for Stage 2 to ask about, never a decision the import made.
            possible = (event.detail or {}).get("possible_match")
            if isinstance(possible, str):
                try:
                    reworded.append((UUID(possible), condition_id))
                except ValueError:
                    logger.warning("condition_compare_bad_possible_match", round_id=str(round_.id))
        elif event.kind is ConditionEventKind.CONDITION_CAME_BACK:
            came_back.add(condition_id)
            before = (event.detail or {}).get("prep_status_from")
            after = (event.detail or {}).get("prep_status_to")
            if isinstance(before, str) and isinstance(after, str) and before != after:
                came_back_moves[condition_id] = (before, after)

    open_before = await _open_before(
        db, loan_file_id=round_.loan_file_id, created_here=created_here
    )
    previous = await _previous_imported(
        db, loan_file_id=round_.loan_file_id, before_number=round_.round_number
    )

    # --- why suggestions may be withheld entirely --------------------------------------------- #
    #
    # BOTH REASONS ARE ABOUT WHAT ABSENCE MEANS. A partial sheet never claimed to list everything, and
    # a sheet printed before the latest one describes a state the file has already moved past.
    reason: str | None = None
    if round_.completeness is not ConditionRoundCompleteness.FULL:
        reason = _PARTIAL_NO_SUGGESTIONS
    elif (
        previous is not None
        and round_.date_printed is not None
        and previous.date_printed is not None
        and round_.date_printed < previous.date_printed
    ):
        reason = (
            f"This sheet is older than round {previous.round_number}, "
            "so missing conditions aren't treated as cleared."
        )

    # A PAIR ALREADY ANSWERED *SAME* IS NOT ASKED AGAIN (LP-915 review). `reworded` is rebuilt from
    # the import's events, so a Full → Just some → Full switch recomputed it and re-asked a pair
    # whose old half is already Replaced, where *Same* is then refused as "already replaced".
    if reworded:
        replaced = set(
            (
                await db.execute(
                    select(Condition.id).where(
                        Condition.id.in_([old for old, _ in reworded]),
                        Condition.superseded_by_id.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        reworded = [(old, new) for old, new in reworded if old not in replaced]

    reworded_old = {old for old, _ in reworded}
    probably_cleared: list[UUID] = []
    if reason is None:
        probably_cleared = [
            condition.id
            for condition in open_before
            if condition.id not in on_sheet and condition.id not in reworded_old
        ]

    comparison = RoundComparison(
        round_id=round_.id,
        round_number=round_.round_number,
        compared_with=len(open_before),
        new=sorted(created_here - {new for _, new in reworded}, key=str),
        still_open=sorted(on_sheet - created_here - came_back, key=str),
        came_back=sorted(came_back, key=str),
        reworded=reworded,
        probably_cleared=sorted(probably_cleared, key=str),
        letter_changes=letter_changes(previous, round_),
        no_suggestions_reason=reason,
        came_back_moves=came_back_moves,
    )

    # A NEWER FULL SHEET SUPERSEDES OLDER ROUNDS' PENDING QUESTIONS (LP-915 review). This comparison
    # re-derives "probably cleared" against everything still open (A6), so a condition missing from
    # both sheets is asked about again HERE, by the newer sheet. Left in place, the older round's
    # questions were counted twice by the summary and could no longer be answered from the list or
    # the sheet, which read only the newest round. A partial or older sheet supersedes nothing.
    superseded = 0
    if reason is None:
        from app.services.condition_status import withdraw_suggestions

        superseded = await withdraw_suggestions(
            db,
            loan_file_id=round_.loan_file_id,
            condition_ids=set(),
            except_round_id=round_.id,
            all_conditions=True,
        )

    # A NEW dict rather than a mutated one: SQLAlchemy does not track in-place JSONB mutation, so an
    # updated key on the existing object would simply not be written.
    round_.comparison = json.loads(json.dumps(comparison.to_json()))

    db.add(
        ConditionEvent(
            company_id=round_.company_id,
            loan_file_id=round_.loan_file_id,
            round_id=round_.id,
            kind=ConditionEventKind.ROUND_COMPARED,
            actor_user_id=actor_user_id,
            # COUNTS, NEVER CODES OR WORDING — the same rule every sibling writer keeps.
            detail={
                "round_number": round_.round_number,
                "compared_with": comparison.compared_with,
                "probably_cleared": len(comparison.probably_cleared),
                "came_back": len(comparison.came_back),
                "reworded": len(comparison.reworded),
                "new": len(comparison.new),
                "suggestions_superseded": superseded,
            },
        )
    )
    await db.flush()
    logger.info(
        "condition_round_compared",
        round_id=str(round_.id),
        round_number=round_.round_number,
        probably_cleared=len(comparison.probably_cleared),
        suggestions_withheld=reason is not None,
    )
    return comparison
