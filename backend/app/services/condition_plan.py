"""The action plan (LP-920, plan §5 LP-920 and §6): items, needs, next steps, reasons.

Built from the reading (LP-919) right after it, so importing round 1 produces the plan with nobody
creating anything by hand. Everything here is code; the model's part ended with the reading.

WHAT THE PLAN DECIDES, IN ORDER, PER CONDITION:

1. **The whole condition's step**, when it is one: a push-back the reading found (6178), the lender doing
   it (the reading, the lender's heading, or this lender's setting — UWM orders the final inspection,
   decision 1), information only.
2. **Each item's option**, from the reading, then adjusted: the lender's "who does what" setting, and the
   file's "Lender is processing this file" switch (§4a change 8) turn third-party asks into "Lender is
   doing it".
3. **Already in the file**: an item the file already holds a document for (matched by type AND the
   library's words, so a credit invoice is not taken for a processing invoice) points to it.
4. **Waits on**: a type that waits on another (0007's invoice on 1228's inspection) links to that
   condition.
5. **Needs**: every document item she asks someone for becomes a need with `origin = CONDITION`. One need
   can serve items on several conditions (§4a change 2): the borrower's statements for one account are
   ONE need, which is how 7086, 6132 and 6637's source and clearance are "asked for once". An open need
   the file already has for the same document is reused rather than duplicated.
6. **The reason** shown under the step, in S3-02's words.

CARRY-OVER (§4a change 3): a condition that already has a plan is not planned again, so a condition seen
again keeps its plan. A condition that came back has its unfinished items reopened. A replaced condition
hands its items to its successor (`carry_plan`), for her to confirm.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.conditions import facts
from app.conditions.library import ConditionType, load_library
from app.models.activity_log import ActivityType
from app.models.borrower import Borrower
from app.models.condition import (
    BucketKind,
    Condition,
    ConditionLenderStatus,
    ConditionPrepStatus,
    ConditionReadingStatus,
)
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_item import ConditionItem
from app.models.condition_round import ConditionRound
from app.models.condition_vocabulary import (
    ConditionItemOrigin,
    ConditionItemStatus,
    Performer,
    PlanOption,
)
from app.models.document import Document
from app.models.lender import Lender
from app.models.loan_file import LoanFile
from app.models.needs_item import NeedsItem, NeedsItemDisposition, NeedsItemOrigin, NeedsItemStatus
from app.services.activity_log import log_activity
from app.services.condition_reading import GENERIC_NAME
from app.services.needs_items import create_needs_item

logger = structlog.get_logger(__name__)

ET = ZoneInfo("America/New_York")

#: Business days an ask is due after the plan is made (the build brief's "fixed from the screens": the
#: borrower email is due 4 business days after the plan; 08/28 gives Thursday 09/03). Editable per item.
ASK_DUE_BUSINESS_DAYS = 4

_ASKS = frozenset({PlanOption.ASK_BORROWER, PlanOption.ASK_THIRD_PARTY})
_THIRD_PARTIES = frozenset(
    {
        Performer.TITLE,
        Performer.ATTORNEY,
        Performer.INSURANCE,
        Performer.HOA,
        Performer.EMPLOYER,
        Performer.APPRAISER,
        Performer.OTHER_PARTY,
    }
)
_OPEN_NEED = frozenset(
    {NeedsItemStatus.PENDING, NeedsItemStatus.REQUESTED, NeedsItemStatus.REJECTED}
)

REASON_CONFIRM = "Please confirm how we read this"
REASON_LENDER_ORDERS = "Ordered through the lender — confirm on your files"
REASON_LENDER = "The lender is doing it"
REASON_LENDER_VERIFIES = "The lender verifies it — its setting for this lender"
REASON_PUSH_BACK = "Reason from the letter"
REASON_SHORTFALL = "Shortfall computed by code"
REASON_TITLE_INSTRUCTION = "Added to the title email"
REASON_LENDER_PROCESSING = "Lender is processing this file"
#: LP-953 — "Already in the file" names a document, so choosing it by hand means one is linked.
LINK_FIRST = "Link the document that is already in the file first: choose it, then this step."

ITEM_DONE_ONLY_FOR_TASKS = (
    "Only your own tasks are marked done here — an item you asked for is done when it arrives."
)


# --------------------------------------------------------------------------------------------- #
# Per-lender settings (decision 1, 4, 5): who orders what, and what the upload asks
# --------------------------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LenderConditionSettings:
    """How conditions are worked at one lender. Stored on `lenders.condition_settings`; LP-925 edits it."""

    lender_orders_final_inspection: bool = False
    lender_orders_title_insurance_payoffs: bool = False
    #: LP-945 — the lender verifies a self-employed borrower's business exists (IE-08).
    lender_verifies_business_existence: bool = False
    new_files_lender_processing: bool = False
    upload_cutoff: str | None = None  # "20:00"
    upload_cutoff_tz: str = "America/New_York"
    upload_fields: tuple[str, ...] = ("note",)
    mortgagee_clause: str | None = None


#: The defaults a lender starts with, by its canonical key. Decision 1: at UWM the final inspection is
#: ordered by the lender; title, insurance and payoffs are asked of the party; Processor Assist and
#: Underwriting+ are off. Decision 4: Sun West's upload asks for a comment, Name of Source and Date
#: Verified. Every other lender: nothing ticked.
_CANONICAL_DEFAULTS: dict[str, dict[str, Any]] = {
    "uwm": {
        "lender_orders_final_inspection": True,
        "upload_cutoff": "20:00",
        "upload_fields": ["note"],
    },
    "sunwest": {"upload_fields": ["note", "name_of_source", "date_verified"]},
}


@dataclass(frozen=True)
class Route:
    """LP-955 — one way a condition gets done at one lender, offered as a choice on the condition."""

    key: str
    label: str
    hint: str
    #: The condition's step when she picks it; None leaves the items to carry their own (her task).
    step: PlanOption | None


#: LP-955 — the choices a condition offers at a lender, by (canonical lender key, library type). Data,
#: not branches: a new lender or type is a new row. IV-01 at UWM: credit pulled in UWM's own system
#: means UWM holds the invoice, so the underwriter is asked to clear it; pulled through the broker's own
#: vendor, the invoice is hers to upload.
ROUTES: dict[tuple[str, str], tuple[Route, ...]] = {
    ("uwm", "IV-01"): (
        Route(
            key="lender_system",
            label="Pulled in UWM's system",
            hint="UWM has the invoice: the underwriter is asked to clear it.",
            step=PlanOption.ASK_UNDERWRITER,
        ),
        Route(
            key="our_vendor",
            label="Our vendor",
            hint="Your task: upload the vendor's invoice.",
            step=None,
        ),
    ),
}


def routes_for(lender_key: str | None, type_id: str | None) -> tuple[Route, ...]:
    if not lender_key or not type_id:
        return ()
    return ROUTES.get((lender_key, type_id), ())


def chosen_route(condition: Condition, routes: tuple[Route, ...]) -> str | None:
    """The route her condition is on: the one whose step it has. None until she has chosen a stepped
    one (the task route is the condition's default state, so it reads as chosen only after a change)."""
    for route in routes:
        if route.step is not None and condition.next_step is route.step:
            return route.key
    return None


async def choose_route(
    db: AsyncSession, *, condition: Condition, route_key: str, actor_user_id: UUID
) -> None:
    """LP-955 — she picks how this condition gets done. The step follows; the plan re-syncs its drafts
    (the underwriter's question appears or goes) through `set_next_step`, the one door for steps."""
    lender = await db.get(Lender, condition.lender_id) if condition.lender_id else None
    routes = routes_for(
        lender.canonical_lender_key if lender else None, condition.canonical_type_id
    )
    route = next((each for each in routes if each.key == route_key), None)
    if route is None:
        raise PlanRefused("That choice is not offered for this condition.")
    await set_next_step(db, condition=condition, next_step=route.step, actor_user_id=actor_user_id)


#: Types the "lender orders the final inspection / appraisal updates" setting covers.
_FINAL_INSPECTION_TYPES = frozenset({"PA-03"})
#: LP-945 — types the "lender verifies business existence" setting covers.
_BUSINESS_EXISTENCE_TYPES = frozenset({"IE-08"})
#: Types the Processor Assist setting ("lender orders title updates, insurance, payoffs") covers.
_PROCESSOR_ASSIST_TYPES = frozenset({"TI-01", "TI-02", "TI-05", "IN-01", "IN-02", "IN-04"})


def lender_condition_settings(lender: Lender | None) -> LenderConditionSettings:
    """The stored settings, or the canonical lender's defaults, or nothing ticked."""
    if lender is None:
        return LenderConditionSettings()
    raw = lender.condition_settings
    if raw is None:
        raw = _CANONICAL_DEFAULTS.get(lender.canonical_lender_key or "", {})
    return LenderConditionSettings(
        lender_orders_final_inspection=bool(raw.get("lender_orders_final_inspection", False)),
        lender_orders_title_insurance_payoffs=bool(
            raw.get("lender_orders_title_insurance_payoffs", False)
        ),
        lender_verifies_business_existence=bool(
            raw.get("lender_verifies_business_existence", False)
        ),
        new_files_lender_processing=bool(raw.get("new_files_lender_processing", False)),
        upload_cutoff=raw.get("upload_cutoff"),
        upload_cutoff_tz=str(raw.get("upload_cutoff_tz") or "America/New_York"),
        upload_fields=tuple(raw.get("upload_fields") or ("note",)),
        mortgagee_clause=raw.get("mortgagee_clause"),
    )


# --------------------------------------------------------------------------------------------- #
# Building the plan
# --------------------------------------------------------------------------------------------- #


@dataclass
class PlanOutcome:
    planned: int = 0
    needs_created: int = 0
    needs_reused: int = 0
    condition_ids: list[UUID] = field(default_factory=list)


def _today_et() -> date:
    return datetime.now(ET).date()


def _is_planned(condition: Condition, has_items: bool) -> bool:
    return has_items or condition.next_step is not None


async def _items_by_condition(
    db: AsyncSession, loan_file_id: UUID
) -> dict[UUID, list[ConditionItem]]:
    # LP-948c: NOT A WITHDRAWN CONDITION'S ITEMS. Withdrawing (LP-940) soft-deletes the condition and
    # leaves its items as they were, so Undo brings it back whole; a child-table query must filter the
    # parent, or a caller that iterates this map shows items of a condition that is on no list.
    rows = (
        await db.execute(
            select(ConditionItem)
            .join(Condition, Condition.id == ConditionItem.condition_id)
            .where(
                ConditionItem.loan_file_id == loan_file_id,
                ConditionItem.deleted_at.is_(None),
                Condition.deleted_at.is_(None),
            )
            .order_by(ConditionItem.sequence, ConditionItem.created_at)
        )
    ).scalars()
    out: dict[UUID, list[ConditionItem]] = {}
    for item in rows:
        out.setdefault(item.condition_id, []).append(item)
    return out


def _find_document(
    item: dict[str, Any], match_words: tuple[str, ...], documents: list[Document]
) -> Document | None:
    """A document the file already holds for this item: the ONE matching rule arrival uses too
    (`condition_matching.document_answers`, LP-953). The newest wins. A new item has nothing she has
    unlinked yet, so no `unlinked` set is passed."""
    from app.services.condition_matching import document_answers

    for document in documents:
        if document_answers(
            wanted=item.get("documents"), match_words=match_words, document=document
        ):
            return document
    return None


def _need_group(item: ConditionItem) -> tuple[str, str, str]:
    """What makes two items the same ask: who provides it, the document, and the account."""
    document = item.documents[0] if item.documents else item.key
    who = "borrower" if item.performer is Performer.BORROWER else item.performer.value
    account = str(item.specifics.get("account_last4") or "")
    return who, document, account


_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]  # fmt: skip


def _months_phrase(months: list[str]) -> str:
    """`["2026-07", "2026-08"]` → `July and August 2026`."""
    parsed = sorted({m for m in months if len(m) == 7})
    if not parsed:
        return ""
    names = [_MONTH_NAMES[int(m[5:7]) - 1] for m in parsed]
    year = parsed[-1][:4]
    return f"{' and '.join(names)} {year}" if len(names) <= 2 else f"{', '.join(names)} {year}"


def _need_title(items: list[ConditionItem]) -> str:
    first = items[0]
    if first.documents and first.documents[0] == "bank_statement":
        bank = first.specifics.get("account_bank") or "Bank"
        last4 = first.specifics.get("account_last4")
        months = _months_phrase([str(i.specifics.get("month") or "") for i in items])
        account = f"{bank} ··{last4}" if last4 else bank
        return f"{account} statements{', ' + months if months else ''}"[:255]
    return first.name[:255]


async def _needs_for_items(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    items: list[ConditionItem],
    outcome: PlanOutcome,
) -> None:
    """Every document item she asks for points at a need; items that are the same ask share one."""
    asks = [
        item
        for item in items
        if item.option in _ASKS
        and item.documents
        and item.status is ConditionItemStatus.OPEN
        and item.need_id is None
    ]
    if not asks:
        return

    # A borrower bank-statement item that names no account joins the one account the round asks
    # about, when there is exactly one (6637's source and clearance name none; 6132 names ··9912).
    accounts = {
        (str(i.specifics.get("account_bank") or ""), str(i.specifics.get("account_last4")))
        for i in asks
        if i.performer is Performer.BORROWER
        and i.documents[0] == "bank_statement"
        and i.specifics.get("account_last4")
    }
    if len(accounts) == 1:
        bank, last4 = next(iter(accounts))
        for item in asks:
            if (
                item.performer is Performer.BORROWER
                and item.documents[0] == "bank_statement"
                and not item.specifics.get("account_last4")
                and item.key != "other_accounts"
            ):
                item.specifics = {
                    **item.specifics,
                    "account_bank": bank or None,
                    "account_last4": last4,
                }

    groups: dict[tuple[str, str, str], list[ConditionItem]] = {}
    for item in asks:
        groups.setdefault(_need_group(item), []).append(item)

    primary_borrower = await db.scalar(
        select(Borrower.id).where(
            Borrower.loan_file_id == loan_file.id, Borrower.is_primary.is_(True)
        )
    )
    existing = list(
        (
            await db.execute(
                select(NeedsItem).where(
                    NeedsItem.loan_file_id == loan_file.id,
                    NeedsItem.deleted_at.is_(None),
                    NeedsItem.status.in_(_OPEN_NEED),
                )
            )
        ).scalars()
    )
    for (who, document, account), members in groups.items():
        reuse = next(
            (
                need
                for need in existing
                if need.needs_type == document
                and (not account or account in (need.title or ""))
                and (
                    need.origin is not NeedsItemOrigin.CONDITION
                    or need.title == _need_title(members)
                )
            ),
            None,
        )
        if reuse is not None:
            need = reuse
            outcome.needs_reused += 1
        else:
            need = await create_needs_item(
                db,
                loan_file_id=loan_file.id,
                title=_need_title(members),
                needs_type=document,
                borrower_id=primary_borrower if who == "borrower" else None,
                origin=NeedsItemOrigin.CONDITION,
                description=members[0].acceptable,
                disposition=NeedsItemDisposition.CONFIRMED,
            )
            existing.append(need)
            outcome.needs_created += 1
        for item in members:
            item.need_id = need.id


def _step_and_reason(
    condition: Condition,
    condition_type: ConditionType | None,
    reading: dict[str, Any],
    settings: LenderConditionSettings,
    loan_file: LoanFile,
) -> tuple[PlanOption | None, str | None]:
    """The whole condition's step (or None when its items carry their own), and the reason for it."""
    if reading.get("push_back"):
        return PlanOption.PUSH_BACK, REASON_PUSH_BACK
    type_id = condition_type.id if condition_type else None
    if type_id in _FINAL_INSPECTION_TYPES and settings.lender_orders_final_inspection:
        return PlanOption.LENDER_DOING_IT, REASON_LENDER_ORDERS
    if type_id in _BUSINESS_EXISTENCE_TYPES and settings.lender_verifies_business_existence:
        return PlanOption.LENDER_DOING_IT, REASON_LENDER_VERIFIES
    if reading.get("lender_doing_it") or condition.bucket_kind is BucketKind.LENDER_TO_CLEAR:
        return PlanOption.LENDER_DOING_IT, REASON_LENDER
    if reading.get("information_only") or condition.info_only:
        return PlanOption.INFORMATION_ONLY, None
    return None, None


def _item_option(
    raw: dict[str, Any],
    condition_type: ConditionType | None,
    settings: LenderConditionSettings,
    loan_file: LoanFile,
) -> PlanOption:
    option = PlanOption(str(raw.get("option") or PlanOption.ASK_BORROWER.value))
    performer = Performer(str((raw.get("performers") or ["borrower"])[0]))
    type_id = condition_type.id if condition_type else None
    if (
        settings.lender_orders_title_insurance_payoffs
        and type_id in _PROCESSOR_ASSIST_TYPES
        and performer in _THIRD_PARTIES
    ):
        return PlanOption.LENDER_DOING_IT
    if loan_file.lender_processing and option is PlanOption.ASK_THIRD_PARTY:
        return PlanOption.LENDER_DOING_IT
    return option


def _event(
    condition: Condition,
    kind: ConditionEventKind,
    detail: dict[str, Any],
    *,
    round_id: UUID | None,
    actor_user_id: UUID | None = None,
) -> ConditionEvent:
    return ConditionEvent(
        company_id=condition.company_id,
        loan_file_id=condition.loan_file_id,
        condition_id=condition.id,
        round_id=round_id,
        kind=kind,
        actor_user_id=actor_user_id,
        detail=detail,
    )


async def build_plan(db: AsyncSession, *, round_id: UUID, today: date | None = None) -> PlanOutcome:
    """Plan every read, not-yet-planned condition on this round's file. Flushes; the caller commits."""
    outcome = PlanOutcome()
    round_ = await db.get(ConditionRound, round_id)
    if round_ is None:
        return outcome
    loan_file = await db.get(LoanFile, round_.loan_file_id)
    if loan_file is None:
        return outcome
    lender = await db.get(Lender, loan_file.lender_id) if loan_file.lender_id else None
    settings = lender_condition_settings(lender)
    library = load_library()
    today = today or _today_et()
    due = facts.business_days_after(today, ASK_DUE_BUSINESS_DAYS)

    conditions = list(
        (
            await db.execute(
                select(Condition)
                .where(
                    Condition.loan_file_id == loan_file.id,
                    Condition.deleted_at.is_(None),
                    Condition.lender_status != ConditionLenderStatus.SUPERSEDED,
                )
                .order_by(Condition.sequence, Condition.created_at)
            )
        ).scalars()
    )
    items_by_condition = await _items_by_condition(db, loan_file.id)
    documents = list(
        (
            await db.execute(
                select(Document)
                .where(Document.loan_file_id == loan_file.id, Document.deleted_at.is_(None))
                .order_by(Document.created_at.desc())
            )
        ).scalars()
    )
    by_type: dict[str, Condition] = {}
    for condition in conditions:
        if condition.canonical_type_id and condition.canonical_type_id not in by_type:
            by_type[condition.canonical_type_id] = condition

    new_items: list[ConditionItem] = []
    for condition in conditions:
        if condition.reading is None or condition.reading_status is ConditionReadingStatus.UNREAD:
            continue
        if _is_planned(condition, bool(items_by_condition.get(condition.id))):
            continue
        condition_type = library.get(condition.canonical_type_id)
        reading = condition.reading
        step, reason = _step_and_reason(condition, condition_type, reading, settings, loan_file)

        created: list[ConditionItem] = []
        # LP-954 — THE LENDER DOES THE TYPE'S WORK, NOT EVERY CLAUSE'S. An item the reading added for a
        # clause the library type does not cover (1228's "possibly a Change of Circumstance", the LO's
        # re-disclosure) keeps its own step when the lender orders the inspection.
        library_keys = {each.key for each in condition_type.items} if condition_type else None
        for index, raw in enumerate(reading.get("items") or []):
            performers = [str(p) for p in raw.get("performers") or ["borrower"]]
            option = _item_option(raw, condition_type, settings, loan_file)
            status = ConditionItemStatus.OPEN
            if step in (PlanOption.PUSH_BACK, PlanOption.INFORMATION_ONLY):
                status = ConditionItemStatus.NOT_NEEDED
            elif step is PlanOption.LENDER_DOING_IT and (
                library_keys is None or str(raw.get("key")) in library_keys
            ):
                option = PlanOption.LENDER_DOING_IT
            item = ConditionItem(
                company_id=condition.company_id,
                loan_file_id=condition.loan_file_id,
                condition_id=condition.id,
                round_id=round_.id,
                key=str(raw.get("key") or f"item_{index + 1}")[:40],
                name=str(raw.get("name") or GENERIC_NAME)[:200],
                acceptable=str(raw.get("acceptable") or ""),
                performer=Performer(performers[0]),
                performers=performers,
                option=option,
                status=status,
                origin=ConditionItemOrigin.READING,
                documents=list(raw.get("documents") or []),
                checks=list(raw.get("checks") or []),
                specifics=dict(raw.get("specifics") or {}),
                sequence=index,
                due_date=due if option in _ASKS and status is ConditionItemStatus.OPEN else None,
            )
            parts = split_item(item)
            route_ask(item)
            base = next(
                (i for i in (condition_type.items if condition_type else ()) if i.key == item.key),
                None,
            )
            # Already in the file (existing coverage, by type and the library's words). `item.option`,
            # not `option`: an ask routed to her task by `route_ask` is looked for too.
            if item.option is PlanOption.I_WILL_DO_IT and status is ConditionItemStatus.OPEN:
                found = _find_document(raw, base.match_words if base else (), documents)
                if found is not None:
                    item.option = PlanOption.ALREADY_IN_FILE
                    item.document_id = found.id
                    item.document_page = 1
                    item.status = ConditionItemStatus.DONE
                    reason = (
                        reason or f"Found: {found.document_name or found.document_type}, page 1"
                    )
            db.add(item)
            created.append(item)
            for part in parts:
                db.add(part)
                created.append(part)

        # Waits on another condition (0007's invoice on 1228's inspection).
        if condition_type is not None and condition_type.waits_on_type:
            waited = by_type.get(condition_type.waits_on_type)
            if waited is not None and waited.id != condition.id:
                for item in created:
                    item.waits_on_condition_id = waited.id
                reason = reason or f"Waits on {waited.lender_code or 'another condition'}"

        if reason is None and (reading.get("figures") or {}).get("shortfall"):
            reason = REASON_SHORTFALL
        if reason is None and condition_type is not None and condition_type.id == "TI-04":
            reason = REASON_TITLE_INSTRUCTION
        if (
            reason is None
            and loan_file.lender_processing
            and any(i.option is PlanOption.LENDER_DOING_IT for i in created)
        ):
            reason = REASON_LENDER_PROCESSING
        if condition.reading_status is ConditionReadingStatus.NEEDS_CONFIRMATION:
            reason = REASON_CONFIRM
        if (
            step is None
            and created
            and all(i.option is PlanOption.LENDER_DOING_IT for i in created)
        ):
            step = PlanOption.LENDER_DOING_IT
        elif step is PlanOption.LENDER_DOING_IT and any(
            i.option is not PlanOption.LENDER_DOING_IT
            for i in created
            if i.status is not ConditionItemStatus.NOT_NEEDED
        ):
            # LP-954 — the lender is not doing ALL of it: the items carry their own steps, and the
            # reason still says what the lender does.
            step = None

        condition.next_step = step
        condition.plan_reason = reason
        new_items.extend(created)
        db.add(
            _event(
                condition,
                ConditionEventKind.CONDITION_PLANNED,
                {
                    "next_step": step.value if step else None,
                    "items": len(created),
                    "options": sorted({i.option.value for i in created}),
                },
                round_id=round_.id,
            )
        )
        outcome.planned += 1
        outcome.condition_ids.append(condition.id)

    await db.flush()
    await _needs_for_items(db, loan_file=loan_file, items=new_items, outcome=outcome)

    # Came back on this round: its unfinished items are asked again (§4a change 3).
    for condition in conditions:
        if (
            condition.lender_status is ConditionLenderStatus.NOT_CLEARED
            and condition.last_seen_round_id == round_.id
        ):
            for item in items_by_condition.get(condition.id, []):
                if item.status in (ConditionItemStatus.REQUESTED, ConditionItemStatus.RECEIVED):
                    item.status = ConditionItemStatus.OPEN

    if outcome.planned:
        round_.plan_ready_at = datetime.now(UTC)
        await log_activity(
            db,
            loan_file_id=loan_file.id,
            activity_type=ActivityType.CONDITION_PLAN_READY,
            summary=f"Plan ready for round {round_.round_number}: {outcome.planned} conditions",
            detail={"round_id": str(round_.id), "planned": outcome.planned},
        )
    await db.flush()
    logger.info(
        "condition_plan_built",
        round_id=str(round_id),
        planned=outcome.planned,
        needs_created=outcome.needs_created,
        needs_reused=outcome.needs_reused,
    )
    return outcome


async def carry_plan(
    db: AsyncSession,
    *,
    from_condition: Condition,
    to_condition: Condition,
    actor_user_id: UUID | None,
) -> int:
    """A replaced (reworded) condition hands its plan to its successor, for her to confirm (§4a 3)."""
    existing = await _items_by_condition(db, from_condition.loan_file_id)
    if existing.get(to_condition.id):
        return 0
    from app.services.condition_matching import copy_unlinks

    carried = 0
    for item in existing.get(from_condition.id, []):
        # AN EXPLICIT ID SO HER REFUSALS CAN FOLLOW (LP-953 review). `condition_item_unlinks` is keyed
        # `(item_id, document_id)`, and a carry replaces the item id, so without the copy below the
        # successor's item is unprotected and the next arrival re-links a document she removed.
        new_id = uuid4()
        db.add(
            ConditionItem(
                id=new_id,
                company_id=to_condition.company_id,
                loan_file_id=to_condition.loan_file_id,
                condition_id=to_condition.id,
                round_id=item.round_id,
                key=item.key,
                name=item.name,
                acceptable=item.acceptable,
                performer=item.performer,
                performers=list(item.performers),
                option=item.option,
                status=item.status,
                origin=ConditionItemOrigin.CARRIED,
                documents=list(item.documents),
                checks=list(item.checks),
                specifics=dict(item.specifics),
                need_id=item.need_id,
                document_id=item.document_id,
                document_page=item.document_page,
                waits_on_condition_id=item.waits_on_condition_id,
                due_date=item.due_date,
                sequence=item.sequence,
            )
        )
        await copy_unlinks(
            db,
            from_item_id=item.id,
            to_item_id=new_id,
            company_id=to_condition.company_id,
            loan_file_id=to_condition.loan_file_id,
        )
        carried += 1
    to_condition.next_step = from_condition.next_step
    to_condition.plan_reason = f"Carried from the condition it replaced — {REASON_CONFIRM.lower()}"
    if to_condition.reading_status is not ConditionReadingStatus.CONFIRMED:
        to_condition.reading_status = ConditionReadingStatus.NEEDS_CONFIRMATION
    db.add(
        _event(
            to_condition,
            ConditionEventKind.CONDITION_PLAN_CHANGED,
            {"change": "carried", "items": carried},
            round_id=to_condition.last_seen_round_id,
            actor_user_id=actor_user_id,
        )
    )
    await db.flush()
    return carried


# --------------------------------------------------------------------------------------------- #
# Her edits (she can change any part of the plan) and confirming the round's plan
# --------------------------------------------------------------------------------------------- #


class PlanRefused(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# --------------------------------------------------------------------------------------------- #
# Our status from the step (LP-921)
# --------------------------------------------------------------------------------------------- #

#: Shown, never acted on (plan §4a change 12): they add no status and move nothing.
DISPLAY_ONLY = frozenset({PlanOption.LENDER_DOING_IT, PlanOption.INFORMATION_ONLY})


def ready_because(condition: Condition, items: list[ConditionItem]) -> PlanOption | None:
    """The step that makes this condition Ready to send now, or None while something is still owed.

    Ready when its own step is "Already in the file", or when it has no step of its own (or "I'll do
    it") and every live item is done — the file held it, or she marked her task done. A condition-level
    ask, question or push-back is owed until LP-922's send moves it; a display-only step never moves.
    """
    if condition.next_step is PlanOption.ALREADY_IN_FILE:
        return PlanOption.ALREADY_IN_FILE
    if condition.next_step is not None and condition.next_step is not PlanOption.I_WILL_DO_IT:
        return None
    live = [item for item in items if item.status is not ConditionItemStatus.NOT_NEEDED]
    if not live or any(item.status is not ConditionItemStatus.DONE for item in live):
        return None
    if any(item.option is PlanOption.I_WILL_DO_IT for item in live):
        return PlanOption.I_WILL_DO_IT
    return live[0].option


async def _resync_drafts(
    db: AsyncSession, *, condition: Condition, actor_user_id: UUID | None
) -> None:
    """LP-922 — after a plan edit on a confirmed round, the round's unsent drafts follow the edit."""
    if not await _plan_in_force(db, condition):
        return
    from app.services.condition_drafts import resync_file

    await resync_file(db, loan_file_id=condition.loan_file_id, actor_user_id=actor_user_id)


async def _plan_in_force(db: AsyncSession, condition: Condition) -> bool:
    """Whether the condition's round has a confirmed plan. Before that, every step is a proposal."""
    if condition.last_seen_round_id is None:
        return False
    round_ = await db.get(ConditionRound, condition.last_seen_round_id)
    return round_ is not None and round_.plan_confirmed_at is not None


async def apply_step_status(
    db: AsyncSession,
    *,
    condition: Condition,
    items: list[ConditionItem] | None = None,
    actor_user_id: UUID | None,
    in_force: bool | None = None,
) -> bool:
    """Move our status to Ready when the chosen step says so. Returns whether it moved. Flushes.

    FORWARD ONLY, AND ONLY FROM TO DO. The plan never moves a condition backwards and never overrides a
    move she made herself: a condition she already has at Waiting or Sent to lender is hers. The move
    writes `condition_prep_moved` with `by: "plan"` and the option, so the history says why it moved.
    """
    if condition.prep_status is not ConditionPrepStatus.TO_DO:
        return False
    if condition.info_only or condition.lender_status not in (
        ConditionLenderStatus.OPEN,
        ConditionLenderStatus.NOT_CLEARED,
    ):
        return False
    if in_force is None:
        in_force = await _plan_in_force(db, condition)
    if not in_force:
        return False
    if items is None:
        items = (await _items_by_condition(db, condition.loan_file_id)).get(condition.id, [])
    because = ready_because(condition, items)
    if because is None:
        return False
    condition.prep_status = ConditionPrepStatus.READY
    condition.prep_status_changed_at = datetime.now(UTC)
    condition.waiting_on = None
    db.add(
        _event(
            condition,
            ConditionEventKind.CONDITION_PREP_MOVED,
            {
                "prep_status_from": ConditionPrepStatus.TO_DO.value,
                "prep_status_to": ConditionPrepStatus.READY.value,
                "by": "plan",
                "option": because.value,
            },
            round_id=condition.last_seen_round_id,
            actor_user_id=actor_user_id,
        )
    )
    await db.flush()
    logger.info(
        "condition_prep_moved_by_plan",
        condition_id=str(condition.id),
        loan_file_id=str(condition.loan_file_id),
        option=because.value,
    )
    return True


async def _has_link(db: AsyncSession, item: ConditionItem) -> bool:
    """LP-953 — whether a document answers this item: the pointer, or an evidence row."""
    from app.models.condition_evidence import ConditionEvidence

    if item.document_id is not None:
        return True
    found = await db.scalar(
        select(ConditionEvidence.id).where(ConditionEvidence.item_id == item.id).limit(1)
    )
    return found is not None


async def set_next_step(
    db: AsyncSession, *, condition: Condition, next_step: PlanOption | None, actor_user_id: UUID
) -> None:
    if next_step is PlanOption.ALREADY_IN_FILE:
        # LP-953 — THE WHOLE CONDITION "already in the file" means every live item has its document.
        live = [
            item
            for item in await db.scalars(
                select(ConditionItem).where(
                    ConditionItem.condition_id == condition.id,
                    ConditionItem.deleted_at.is_(None),
                )
            )
            if item.status is not ConditionItemStatus.NOT_NEEDED
        ]
        if not live or not all([await _has_link(db, item) for item in live]):
            raise PlanRefused(LINK_FIRST)
    before = condition.next_step
    condition.next_step = next_step
    db.add(
        _event(
            condition,
            ConditionEventKind.CONDITION_PLAN_CHANGED,
            {
                "change": "next_step",
                "from": before.value if before else None,
                "to": next_step.value if next_step else None,
            },
            round_id=condition.last_seen_round_id,
            actor_user_id=actor_user_id,
        )
    )
    await db.flush()
    await apply_step_status(db, condition=condition, actor_user_id=actor_user_id)
    await _resync_drafts(db, condition=condition, actor_user_id=actor_user_id)


async def update_item(
    db: AsyncSession,
    *,
    condition: Condition,
    item: ConditionItem,
    option: PlanOption | None,
    name: str | None,
    performers: list[Performer] | None,
    due_date: date | None,
    actor_user_id: UUID,
    status: ConditionItemStatus | None = None,
) -> None:
    """Her edit to one item. `status` is done/open on an "I'll do it" item only (LP-921): an ask's item
    is done when its evidence passes (LP-923), never by hand here."""
    changed: dict[str, Any] = {"change": "item", "item_key": item.key}
    if status is not None and status is not item.status:
        if item.option is not PlanOption.I_WILL_DO_IT or status not in (
            ConditionItemStatus.DONE,
            ConditionItemStatus.OPEN,
        ):
            raise PlanRefused(ITEM_DONE_ONLY_FOR_TASKS)
        changed["status"] = {"from": item.status.value, "to": status.value}
        item.status = status
    if option is not None and option is not item.option:
        if option is PlanOption.ALREADY_IN_FILE and not await _has_link(db, item):
            raise PlanRefused(LINK_FIRST)
        changed["option"] = {"from": item.option.value, "to": option.value}
        item.option = option
    if name is not None and name.strip() and name.strip() != item.name:
        item.name = name.strip()[:200]
        changed["name"] = True
    if performers:
        item.performer = performers[0]
        item.performers = [p.value for p in performers][:3]
        changed["performers"] = item.performers
    if due_date is not None:
        item.due_date = due_date
        changed["due_date"] = due_date.isoformat()
    # LP-946: a re-edit re-splits. Only the parts NEVER ASKED go (soft): an OPEN part is still in an
    # unsent draft or is her untouched task. A part whose ask went out (REQUESTED), whose document came
    # (RECEIVED) or that is DONE is KEPT, as the record of what was requested or arrived — the LP-940
    # doctrine that a SENT draft keeps its items (LP-946 review). A kept part is not split out again.
    from app.services.condition_matching import copy_unlinks

    kept: set[str] = set()
    # HER REFUSALS FOLLOW A PART THAT IS REMADE (LP-953 review): a deleted part's id is replaced, and
    # `condition_item_unlinks` is keyed on it, so without carrying them the next arrival re-links a
    # document she removed from that part. Keyed by key, which `split_item` derives deterministically.
    replaced: dict[str, UUID] = {}
    for old in (
        await db.execute(
            select(ConditionItem).where(
                ConditionItem.part_of_item_id == item.id, ConditionItem.deleted_at.is_(None)
            )
        )
    ).scalars():
        if old.status is ConditionItemStatus.OPEN:
            old.deleted_at = datetime.now(UTC)
            replaced[old.key] = old.id
        else:
            kept.add(old.key)
    parts = [part for part in split_item(item) if part.key not in kept]
    for part in parts:
        db.add(part)
        was = replaced.get(part.key)
        if was is not None:
            await copy_unlinks(
                db,
                from_item_id=was,
                to_item_id=part.id,
                company_id=item.company_id,
                loan_file_id=item.loan_file_id,
            )
    if parts:
        changed["split"] = [p.performers for p in parts]
    before = item.option
    route_ask(item)
    if item.option is not before:
        changed["routed"] = {"from": before.value, "to": item.option.value}
    db.add(
        _event(
            condition,
            ConditionEventKind.CONDITION_PLAN_CHANGED,
            changed,
            round_id=condition.last_seen_round_id,
            actor_user_id=actor_user_id,
        )
    )
    await db.flush()
    await apply_step_status(db, condition=condition, actor_user_id=actor_user_id)
    await _resync_drafts(db, condition=condition, actor_user_id=actor_user_id)


async def add_item(
    db: AsyncSession,
    *,
    condition: Condition,
    name: str,
    performers: list[Performer],
    option: PlanOption | None,
    actor_user_id: UUID,
) -> ConditionItem:
    from app.services.condition_reading import option_for

    if not name.strip():
        raise PlanRefused("An item needs a few words saying what it is.")
    if not performers:
        raise PlanRefused("An item needs someone to act on it.")
    count = await db.scalar(
        select(ConditionItem.sequence)
        .where(ConditionItem.condition_id == condition.id)
        .order_by(ConditionItem.sequence.desc())
        .limit(1)
    )
    chosen = option or option_for(performers[0])
    item = ConditionItem(
        company_id=condition.company_id,
        loan_file_id=condition.loan_file_id,
        condition_id=condition.id,
        round_id=condition.last_seen_round_id,
        key=f"manual_{(count or 0) + 1}",
        name=name.strip()[:200],
        acceptable="",
        performer=performers[0],
        performers=[p.value for p in performers][:3],
        option=chosen,
        origin=ConditionItemOrigin.MANUAL,
        documents=[],
        checks=[],
        specifics={},
        sequence=(count or 0) + 1,
        due_date=facts.business_days_after(_today_et(), ASK_DUE_BUSINESS_DAYS)
        if chosen in _ASKS
        else None,
    )
    parts = split_item(item)
    route_ask(item)
    db.add(item)
    for part in parts:
        db.add(part)
    if condition.next_step in (PlanOption.INFORMATION_ONLY, PlanOption.LENDER_DOING_IT):
        condition.next_step = None
    db.add(
        _event(
            condition,
            ConditionEventKind.CONDITION_PLAN_CHANGED,
            {"change": "item_added", "option": chosen.value},
            round_id=condition.last_seen_round_id,
            actor_user_id=actor_user_id,
        )
    )
    await db.flush()
    await _resync_drafts(db, condition=condition, actor_user_id=actor_user_id)
    return item


async def remove_item(
    db: AsyncSession, *, condition: Condition, item: ConditionItem, actor_user_id: UUID
) -> None:
    item.deleted_at = datetime.now(UTC)
    db.add(
        _event(
            condition,
            ConditionEventKind.CONDITION_PLAN_CHANGED,
            {"change": "item_removed", "item_key": item.key},
            round_id=condition.last_seen_round_id,
            actor_user_id=actor_user_id,
        )
    )
    await db.flush()
    await apply_step_status(db, condition=condition, actor_user_id=actor_user_id)
    await _resync_drafts(db, condition=condition, actor_user_id=actor_user_id)


async def set_lender_processing(
    db: AsyncSession, *, loan_file: LoanFile, on: bool, actor_user_id: UUID
) -> int:
    """The file-level switch (§4a change 8). Re-defaults third-party asks that have not gone out yet."""
    loan_file.lender_processing = on
    items = list(
        (
            await db.execute(
                select(ConditionItem).where(
                    ConditionItem.loan_file_id == loan_file.id,
                    ConditionItem.deleted_at.is_(None),
                    ConditionItem.status == ConditionItemStatus.OPEN,
                    ConditionItem.performer.in_([p.value for p in _THIRD_PARTIES]),
                )
            )
        ).scalars()
    )
    moved = 0
    for item in items:
        if on and item.option is PlanOption.ASK_THIRD_PARTY:
            item.option = PlanOption.LENDER_DOING_IT
            moved += 1
        elif not on and item.option is PlanOption.LENDER_DOING_IT:
            item.option = PlanOption.ASK_THIRD_PARTY
            moved += 1
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.FILE_UPDATED,
        summary=f"Lender is processing this file: {'on' if on else 'off'}",
        actor_user_id=actor_user_id,
        detail={"lender_processing": on, "items_changed": moved},
    )
    await db.flush()
    return moved


async def round_plan_blockers(db: AsyncSession, *, round_: ConditionRound) -> list[str]:
    """Codes on this round whose reading still needs her — the plan cannot be confirmed past them."""
    rows = (
        await db.execute(
            select(Condition.lender_code).where(
                Condition.loan_file_id == round_.loan_file_id,
                Condition.deleted_at.is_(None),
                Condition.reading_status == ConditionReadingStatus.NEEDS_CONFIRMATION,
                Condition.lender_status != ConditionLenderStatus.SUPERSEDED,
            )
        )
    ).all()
    return [code or "—" for (code,) in rows]


async def confirm_round_plan(
    db: AsyncSession, *, round_: ConditionRound, actor_user_id: UUID
) -> None:
    """S3-02's "Confirm plan…". Refused while any reading still needs her (README rule 3)."""
    blockers = await round_plan_blockers(db, round_=round_)
    if blockers:
        first = blockers[0]
        more = len(blockers) - 1
        raise PlanRefused(
            f"Confirm {first}'s reading first — "
            + (
                "one condition still needs you."
                if more == 0
                else f"{more + 1} conditions still need you."
            )
        )
    if round_.plan_confirmed_at is not None:
        return
    round_.plan_confirmed_at = datetime.now(UTC)
    round_.plan_confirmed_by_user_id = actor_user_id
    db.add(
        ConditionEvent(
            company_id=round_.company_id,
            loan_file_id=round_.loan_file_id,
            condition_id=None,
            round_id=round_.id,
            kind=ConditionEventKind.ROUND_PLAN_CONFIRMED,
            actor_user_id=actor_user_id,
            detail={},
        )
    )
    await log_activity(
        db,
        loan_file_id=round_.loan_file_id,
        activity_type=ActivityType.CONDITION_PLAN_CONFIRMED,
        summary=f"Plan confirmed for round {round_.round_number}",
        actor_user_id=actor_user_id,
        detail={"round_id": str(round_.id)},
    )
    await db.flush()
    # THE STEPS COME INTO FORCE NOW (LP-921): "Already in the file" moves to Ready at confirm, not while
    # the plan was a proposal.
    by_condition = await _items_by_condition(db, round_.loan_file_id)
    on_round = (
        await db.execute(
            select(Condition).where(
                Condition.last_seen_round_id == round_.id, Condition.deleted_at.is_(None)
            )
        )
    ).scalars()
    for condition in on_round:
        await apply_step_status(
            db,
            condition=condition,
            items=by_condition.get(condition.id, []),
            actor_user_id=actor_user_id,
            in_force=True,
        )
    # LP-922 — "Confirm plan and draft 3 emails": the drafts are made now, from the confirmed steps.
    from app.services.condition_drafts import sync_round_drafts

    await sync_round_drafts(db, round_=round_, actor_user_id=actor_user_id)


# --------------------------------------------------------------------------------------------- #
# Read side: items as the screens draw them, and the round's plan summary (S3-02)
# --------------------------------------------------------------------------------------------- #

#: Who an email goes to, by performer. Title and attorney share ONE email (S3-05's "title company /
#: attorney"); everyone else gets their own. The borrower's email is always its own.
_RECIPIENT: dict[Performer, tuple[str, str]] = {
    Performer.BORROWER: ("borrower", "Borrower"),
    Performer.TITLE: ("title_attorney", "Title/attorney"),
    Performer.ATTORNEY: ("title_attorney", "Title/attorney"),
    Performer.LO: ("lo", "LO"),
    Performer.INSURANCE: ("insurance", "Insurance agent"),
    Performer.HOA: ("hoa", "HOA"),
    Performer.EMPLOYER: ("employer", "Employer"),
    Performer.OTHER_PARTY: ("other_party", "Other party"),
    # LP-942 — the lender's own asks go to the lender, one draft per round. So do the APPRAISER's:
    # appraiser independence means loan production staff do not contact the appraiser directly, so an
    # appraisal request goes through the lender (`APPRAISAL_VIA_LENDER` is the line on the item).
    Performer.LENDER: ("lender", "Lender"),
    Performer.APPRAISER: ("lender", "Lender"),
}
#: LP-942 — shown on an appraiser's ask, which goes to the lender instead of the appraiser.
APPRAISAL_VIA_LENDER = "Appraisal requests go through the lender"
_RECIPIENT_ORDER = [
    "borrower",
    "title_attorney",
    "lo",
    "insurance",
    "hoa",
    "employer",
    "other_party",
    "lender",
]


class AskShape(Protocol):
    """What routing reads of an item: a stored `ConditionItem`, or the `ConditionItemPublic` the
    condition payload carries (LP-947 predicts the wait from the public rows)."""

    @property
    def option(self) -> PlanOption: ...
    @property
    def performer(self) -> Performer: ...
    @property
    def performers(self) -> Sequence[str]: ...


def recipient_for(item: AskShape) -> tuple[str, str] | None:
    """The email an ask goes into. The first performer asks, except a Borrower + LO item, which the LO
    sends to the borrower (0132's disclosure goes out in the LO email)."""
    if item.option not in _ASKS:
        return None
    performers = [Performer(p) for p in item.performers] or [item.performer]
    if Performer.LO in performers:
        return _RECIPIENT[Performer.LO]
    return _RECIPIENT.get(performers[0])


def destinations(item: ConditionItem) -> list[list[Performer]]:
    """LP-946 — the performers of an ask, grouped by where each is asked: one group per email, and one
    for HER (her task). THE LO RELAYS TO THE BORROWER (plan §6, the Stage 3A acceptance): a borrower on
    an item the LO also acts on is asked through the LO's email, so `[borrower, lo]` is one group."""
    performers = [Performer(p) for p in item.performers] or [item.performer]
    if item.option not in _ASKS:
        return [performers]
    relayed = Performer.LO in performers
    groups: dict[str, list[Performer]] = {}
    for performer in performers:
        if performer is Performer.PROCESSOR:
            key = "you"
        elif relayed and performer is Performer.BORROWER:
            key = _RECIPIENT[Performer.LO][0]
        else:
            key = _RECIPIENT[performer][0] if performer in _RECIPIENT else performer.value
        groups.setdefault(key, []).append(performer)
    return list(groups.values())


def split_item(item: ConditionItem) -> list[ConditionItem]:
    """LP-946 — EVERY OUTSIDE PERFORMER GETS THE ASK IN THEIR OWN DRAFT, AND SHE GETS A TASK ONLY IF SHE IS
    ONE OF THEM. An item with more than one destination keeps the first and returns one new PART per
    other destination (not yet added to the session: the caller adds the item first, so the part's link
    to it is inserted after it). Each part is a whole item: its own option, its own draft or her task,
    its own evidence. Returns [] when there is one destination."""
    groups = destinations(item)
    if len(groups) <= 1:
        return []
    if item.id is None:
        item.id = uuid4()
    first, *rest = groups
    item.performer = first[0]
    item.performers = [p.value for p in first]
    parts: list[ConditionItem] = []
    for group in rest:
        lead = group[0]
        # An ask of the lead; `route_ask` below makes HER part her task (one rule, not two).
        option = (
            PlanOption.ASK_BORROWER if lead is Performer.BORROWER else PlanOption.ASK_THIRD_PARTY
        )
        part = ConditionItem(
            id=uuid4(),
            company_id=item.company_id,
            loan_file_id=item.loan_file_id,
            condition_id=item.condition_id,
            round_id=item.round_id,
            key=f"{item.key}.{lead.value}"[:40],
            name=item.name,
            acceptable=item.acceptable,
            performer=lead,
            performers=[p.value for p in group],
            option=option,
            status=ConditionItemStatus.OPEN,
            origin=item.origin,
            documents=list(item.documents or []),
            checks=list(item.checks or []),
            specifics=dict(item.specifics or {}),
            sequence=item.sequence,
            due_date=item.due_date if option in _ASKS else None,
            part_of_item_id=item.part_of_item_id or item.id,
        )
        route_ask(part)
        parts.append(part)
    return parts


def route_ask(item: ConditionItem) -> None:
    """LP-942 — AN ASK NEVER ENDS UP WITH NO DESTINATION. The lender and the appraiser have an email now
    (the lender's); the one performer with none is the processor herself, and an ask addressed to her
    is her own task, so it becomes one ("I'll do it"). Called wherever an item is made or edited."""
    if item.option not in _ASKS or recipient_for(item) is not None:
        return
    performers = [Performer(p) for p in item.performers] or [item.performer]
    if performers[0] is Performer.PROCESSOR:
        item.option = PlanOption.I_WILL_DO_IT
        item.due_date = None


async def items_public_for_file(db: AsyncSession, *, loan_file_id: UUID) -> dict[UUID, list[Any]]:
    """Every live item on the file, as `ConditionItemPublic`, keyed by condition. ONE query per table."""
    from app.schemas.condition import ConditionItemPublic, ReadingSpecificsPublic

    by_condition = await _items_by_condition(db, loan_file_id)
    all_items = [item for items in by_condition.values() for item in items]
    if not all_items:
        return {}
    code_rows = await db.execute(
        select(
            Condition.id, Condition.lender_code, Condition.sequence, Condition.canonical_type_id
        ).where(Condition.loan_file_id == loan_file_id)
    )
    codes: dict[UUID, str | None] = {}
    sequence: dict[UUID, int] = {}
    type_ids: dict[UUID, str | None] = {}
    for condition_id, code, seq, type_id in code_rows.tuples().all():
        codes[condition_id] = code
        sequence[condition_id] = seq
        type_ids[condition_id] = type_id
    library = load_library()
    from app.services.condition_drafts import draft_tails

    tails = await draft_tails(db, {item.draft_id for item in all_items if item.draft_id})
    need_ids = {item.need_id for item in all_items if item.need_id}
    need_titles: dict[UUID, str] = {}
    if need_ids:
        need_rows = await db.execute(
            select(NeedsItem.id, NeedsItem.title).where(NeedsItem.id.in_(need_ids))
        )
        need_titles = dict(need_rows.tuples().all())
    doc_ids = {item.document_id for item in all_items if item.document_id}
    doc_names = (
        {
            doc_id: name or kind
            for doc_id, name, kind in (
                await db.execute(
                    select(Document.id, Document.document_name, Document.document_type).where(
                        Document.id.in_(doc_ids)
                    )
                )
            ).all()
        }
        if doc_ids
        else {}
    )
    need_members: dict[UUID, set[UUID]] = {}
    for item in all_items:
        if item.need_id:
            need_members.setdefault(item.need_id, set()).add(item.condition_id)

    out: dict[UUID, list[Any]] = {}
    for condition_id, items in by_condition.items():
        rows = []
        library_type = library.get(type_ids.get(condition_id))
        tasks = {each.key: each.task for each in library_type.items} if library_type else {}
        for item in items:
            shared: list[str] = []
            if item.need_id is not None:
                # SHEET ORDER, as S3-01 prints "Same statement as 7086 and 6132".
                shared = [
                    codes.get(other) or "—"
                    for other in sorted(
                        need_members.get(item.need_id, set()), key=lambda c: sequence.get(c, 0)
                    )
                    if other != condition_id
                ]
            rows.append(
                ConditionItemPublic(
                    id=item.id,
                    key=item.key,
                    name=item.name,
                    acceptable=item.acceptable,
                    performer=item.performer,
                    performers=[Performer(p) for p in item.performers] or [item.performer],
                    option=item.option,
                    status=item.status,
                    origin=item.origin,
                    need_id=item.need_id,
                    need_title=need_titles.get(item.need_id) if item.need_id else None,
                    shared_with_codes=shared,
                    document_id=item.document_id,
                    document_name=doc_names.get(item.document_id) if item.document_id else None,
                    document_page=item.document_page,
                    waits_on_condition_id=item.waits_on_condition_id,
                    waits_on_code=codes.get(item.waits_on_condition_id)
                    if item.waits_on_condition_id
                    else None,
                    due_date=item.due_date,
                    specifics=ReadingSpecificsPublic.model_validate(item.specifics or {}),
                    # THE LIBRARY'S WORDS WHILE THE ITEM IS STILL ITS TASK: an item she re-pointed to an
                    # ask is no longer hers to do.
                    task=tasks.get(item.key) if item.option is PlanOption.I_WILL_DO_IT else None,
                    route_note=APPRAISAL_VIA_LENDER
                    if (item.performers or [item.performer.value])[0] == Performer.APPRAISER.value
                    and recipient_for(item) is not None
                    else None,
                    draft=tails.get(item.draft_id) if item.draft_id else None,
                    part_of_item_id=item.part_of_item_id,
                )
            )
        out[condition_id] = rows
    return out


async def round_plan_summary(db: AsyncSession, *, round_: ConditionRound) -> Any:
    """S3-02's heading and pills, computed from the round's conditions and their items."""
    from app.schemas.condition import RoundPlanDraftPublic, RoundPlanPublic

    conditions = list(
        (
            await db.execute(
                select(Condition).where(
                    Condition.loan_file_id == round_.loan_file_id,
                    Condition.last_seen_round_id == round_.id,
                    Condition.deleted_at.is_(None),
                    Condition.lender_status != ConditionLenderStatus.SUPERSEDED,
                )
            )
        ).scalars()
    )
    by_condition = await _items_by_condition(db, round_.loan_file_id)
    drafts: dict[str, tuple[str, set[str]]] = {}
    your_tasks = already = push_back = lender = confirm = 0
    for condition in conditions:
        items = by_condition.get(condition.id, [])
        code = condition.lender_code or "—"
        if condition.reading_status is ConditionReadingStatus.NEEDS_CONFIRMATION:
            confirm += 1
        if condition.next_step is PlanOption.PUSH_BACK:
            push_back += 1
            continue
        if condition.next_step is PlanOption.LENDER_DOING_IT:
            lender += 1
            continue
        if condition.next_step is PlanOption.INFORMATION_ONLY:
            continue
        # LP-954 — the lender doing PART of a condition (1228's inspection, beside the LO's
        # re-disclosure) still counts: the pill says what the lender is doing, not the whole step.
        if any(
            i.option is PlanOption.LENDER_DOING_IT
            and i.status is not ConditionItemStatus.NOT_NEEDED
            for i in items
        ):
            lender += 1
        if any(i.option is PlanOption.I_WILL_DO_IT for i in items):
            your_tasks += 1
        if items and all(i.option is PlanOption.ALREADY_IN_FILE for i in items):
            already += 1
        for item in items:
            recipient = recipient_for(item)
            if recipient is not None and item.status is ConditionItemStatus.OPEN:
                key, label = recipient
                drafts.setdefault(key, (label, set()))[1].add(code)
    planned = sum(1 for c in conditions if c.next_step is not None or by_condition.get(c.id))
    blockers = await round_plan_blockers(db, round_=round_)
    return RoundPlanPublic(
        round_id=round_.id,
        round_number=round_.round_number,
        round_date=round_.round_date,
        planned=planned,
        ready_at=round_.plan_ready_at,
        confirmed_at=round_.plan_confirmed_at,
        nothing_sent=True,
        drafts=[
            RoundPlanDraftPublic(recipient=key, label=drafts[key][0], codes=sorted(drafts[key][1]))
            for key in _RECIPIENT_ORDER
            if key in drafts
        ],
        your_tasks=your_tasks,
        already_in_file=already,
        push_back=push_back,
        lender_doing_it=lender,
        needs_confirmation=confirm,
        blocking_codes=blockers,
    )


__all__ = [
    "ASK_DUE_BUSINESS_DAYS",
    "LenderConditionSettings",
    "PlanOutcome",
    "PlanRefused",
    "add_item",
    "build_plan",
    "carry_plan",
    "confirm_round_plan",
    "items_public_for_file",
    "lender_condition_settings",
    "recipient_for",
    "remove_item",
    "round_plan_blockers",
    "round_plan_summary",
    "set_lender_processing",
    "set_next_step",
    "update_item",
]
