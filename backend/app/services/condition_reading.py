"""Reading each condition into items (LP-919, plan §5 LP-919): ONE AI call per round, checked by code.

THE ORDER OF AUTHORITY (principle 5, "the library beats the AI"):

1. **Her confirmed answer for this (lender, code)** (`lender_condition_codes.confirmed_reading`, S3-03).
   Used as is; the AI is not asked about that condition.
2. **The library type** (`canonical_type_id`) decides the ITEMS: keys, names, performers, options,
   documents and checks. The AI fills in specifics and may widen a performer the text names (0132's
   "signed by Borrower(s) and Loan Officer" makes item 1 Borrower + LO).
3. **The AI** proposes items only for a condition no library type covers.

WHAT CODE DOES, NOT THE AI (principle 1):

- An amount the AI returns must be written in the lender's text, or it is dropped. The figures a screen
  marks "computed by code" (7086's shortfall) come from `app.conditions.facts`.
- 6178's "may not apply" is decided by comparing two dates code read: the letter's Must Not Close Before
  and the policy date in the condition's own text.
- A last four is taken from the text by code; the AI's is ignored.
- The confidence bar (`settings.condition_reading_confidence_bar`) decides `ready` against
  `needs_confirmation`. Below it nothing is drafted for the condition (README rule 3).

THE ROUND IS NEVER STUCK. If the model fails or returns something unreadable, every condition gets its
library reading (or one generic item from its owner hint), marked `needs_confirmation`, and the failure
is recorded on `condition_rounds.reading_run`. Reading never raises into the import.

NO LOAN SNAPSHOT GOES IN (principle 7): the lender's text and notes, the library's items, and a short
file summary built here. NO NPI IN LOGS: counts, ids and model names only.

THE READING'S SHAPE (`conditions.reading`, JSONB):

    {"version": 1, "source": "ai" | "library" | "confirmed", "type_id": "AS-04" | null,
     "summary": str, "explanation": str | null, "information_only": bool,
     "lender_doing_it": bool, "note_meaning": str | null,
     "items": [{"key", "name", "acceptable", "performers": [..], "option", "documents": [..],
                "checks": [..], "specifics": {"amounts", "account_bank", "account_last4", "month",
                "names"}}],
     "figures": {"shortfall": {"required", "verified", "amount"}} | {},
     "push_back": {"must_not_close_before", "policy_starts"} | null,
     "confidence": float | null, "prompt_version": "read_v3" | null,
     "proposed_type_id": str | null}
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import AIClientError, complete
from app.ai.cost import estimate_cost
from app.ai.parsing import extract_json_object
from app.ai.prompt_loader import load_prompt
from app.conditions import facts
from app.conditions.library import ConditionType, LibraryItem, load_library
from app.core.config import settings
from app.models.condition import (
    BucketKind,
    Condition,
    ConditionLenderStatus,
    ConditionReadingSource,
    ConditionReadingStatus,
    OwnerHint,
)
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import ConditionRound
from app.models.condition_vocabulary import Performer, PlanOption
from app.models.lender import Lender
from app.models.lender_condition_code import LenderConditionCode
from app.models.loan_file import LoanFile

logger = structlog.get_logger(__name__)

PROMPT_PATH = "conditions/read_v3.txt"
READING_VERSION = "read_v3"
_MAX_TOKENS = 8192

_OWNER_TO_PERFORMER: dict[OwnerHint, Performer] = {
    OwnerHint.BORROWER: Performer.BORROWER,
    OwnerHint.TITLE: Performer.TITLE,
    OwnerHint.INSURANCE: Performer.INSURANCE,
    OwnerHint.LENDER: Performer.LENDER,
    OwnerHint.BROKER: Performer.LO,
    OwnerHint.PROCESSOR: Performer.PROCESSOR,
}


def option_for(performer: Performer) -> PlanOption:
    """The next step a performer implies when nothing better is known."""
    if performer is Performer.BORROWER:
        return PlanOption.ASK_BORROWER
    if performer is Performer.PROCESSOR:
        return PlanOption.I_WILL_DO_IT
    if performer is Performer.LENDER:
        return PlanOption.LENDER_DOING_IT
    return PlanOption.ASK_THIRD_PARTY


@dataclass
class RoundReading:
    """What `read_round` did, for the caller and for `reading_run`."""

    read: int = 0
    needs_confirmation: int = 0
    used_ai: bool = False
    fell_back: bool = False
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_estimate: float = 0.0
    error: str | None = None
    condition_ids: list[UUID] = field(default_factory=list)

    def as_run(self) -> dict[str, Any]:
        return {
            # LP-952 — the end-of-run record says it is the end: `condition_reading_state` reads it.
            "state": "done",
            "version": READING_VERSION,
            "read": self.read,
            "needs_confirmation": self.needs_confirmation,
            "used_ai": self.used_ai,
            "fell_back": self.fell_back,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_estimate": self.cost_estimate,
            "error": self.error,
            "read_at": datetime.now(UTC).isoformat(),
        }


# --------------------------------------------------------------------------------------------- #
# Items: from her confirmed answer, the library, the AI, or the owner hint
# --------------------------------------------------------------------------------------------- #


def _empty_specifics() -> dict[str, Any]:
    return {"amounts": [], "account_bank": None, "account_last4": None, "month": None, "names": []}


def _item_from_library(item: LibraryItem) -> dict[str, Any]:
    return {
        "key": item.key,
        "name": item.name,
        "acceptable": item.acceptable,
        "performers": [performer.value for performer in item.all_performers],
        "option": item.option.value,
        "documents": list(item.documents),
        "checks": [check.value for check in item.checks],
        "specifics": _empty_specifics(),
    }


def _items_from_confirmed(
    saved: dict[str, Any], condition_type: ConditionType | None
) -> list[dict[str, Any]]:
    library_items = {item.key: item for item in (condition_type.items if condition_type else ())}
    out: list[dict[str, Any]] = []
    for raw in saved.get("items") or []:
        performers = _performers(raw.get("performers"))
        if not performers:
            continue
        base = library_items.get(str(raw.get("key") or ""))
        item = (
            _item_from_library(base)
            if base
            else _generic_item(performers[0], str(raw.get("name") or ""))
        )
        item["name"] = str(raw.get("name") or item["name"])[:200]
        item["performers"] = [p.value for p in performers]
        item["option"] = str(raw.get("option") or option_for(performers[0]).value)
        out.append(item)
    return out


def _name_the_amount(item: dict[str, Any], condition_type: ConditionType | None) -> None:
    """S3-01's "Source of the $2,850.00": the library's template, filled by code with the lender's own
    amount (already checked against the text). The model never writes the figure into a name."""
    base = next(
        (i for i in (condition_type.items if condition_type else ()) if i.key == item["key"]), None
    )
    amounts = item["specifics"]["amounts"]
    if base is not None and base.name_with_amount and amounts:
        item["name"] = base.name_with_amount.replace("{amount}", amounts[0])


#: LP-950 — what a generic item (no library type) carries in place of a name and an acceptable form.
#: INTERNAL WORDS: they describe a gap, not a request, and may never reach an email. The email builders
#: use the lender's own words instead (`condition_drafts._plain_line`), and a guard test renders every
#: template and asserts neither string is in it.
GENERIC_NAME = "What the lender asks for"
GENERIC_ACCEPTABLE = "What the lender's words describe"


def _generic_item(performer: Performer, name: str = "") -> dict[str, Any]:
    return {
        "key": "request",
        "name": name or GENERIC_NAME,
        "acceptable": GENERIC_ACCEPTABLE,
        "performers": [performer.value],
        "option": option_for(performer).value,
        "documents": [],
        "checks": [],
        "specifics": _empty_specifics(),
    }


def _performers(raw: Any) -> list[Performer]:
    out: list[Performer] = []
    for value in raw if isinstance(raw, list) else []:
        try:
            performer = Performer(str(value))
        except ValueError:
            continue
        if performer not in out:
            out.append(performer)
    return out[:3]


def _checked_specifics(raw: Any, text: str) -> dict[str, Any]:
    """The AI's specifics, keeping only what the lender's text actually carries."""
    specifics = _empty_specifics()
    if not isinstance(raw, dict):
        raw = {}
    specifics["amounts"] = [
        str(amount) for amount in raw.get("amounts") or [] if facts.money_is_in(str(amount), text)
    ]
    # The last four is always code's, read from the text; the model's is never trusted for digits.
    specifics["account_last4"] = facts.last4_in(text)
    bank = raw.get("account_bank")
    specifics["account_bank"] = (
        str(bank) if isinstance(bank, str) and bank.lower() in text.lower() else facts.bank_in(text)
    )
    month = raw.get("month")
    specifics["month"] = month if isinstance(month, str) and len(month) == 7 else None
    specifics["names"] = [
        str(name)[:120]
        for name in raw.get("names") or []
        if isinstance(name, str) and name.lower() in text.lower()
    ]
    return specifics


# --------------------------------------------------------------------------------------------- #
# One condition's reading
# --------------------------------------------------------------------------------------------- #


def _must_not_close_before(round_: ConditionRound | None) -> date | None:
    value = (
        ((round_.header or {}).get("loan_facts") or {}).get("Must Not Close Before")
        if round_
        else None
    )
    found = facts.dates_in(str(value)) if value else []
    return found[0] if found else None


def _code_figures(condition: Condition, condition_type: ConditionType | None) -> dict[str, Any]:
    if condition_type is None or condition_type.id != "AS-10":
        return {}
    shortfall = facts.shortfall_in(condition.verbatim_text)
    if shortfall is None:
        return {}
    return {
        "shortfall": {
            "required": str(shortfall.required),
            "verified": str(shortfall.verified),
            "amount": str(shortfall.amount),
        }
    }


def _summary(
    condition: Condition,
    condition_type: ConditionType | None,
    figures: dict[str, Any],
    ai_summary: str | None,
) -> str:
    """The one-liner. Where code computed the figure, code writes the sentence around it."""
    shortfall = figures.get("shortfall")
    if shortfall:
        return (
            f"Show ${Decimal(shortfall['amount']):,.2f} more in assets "
            f"(required ${Decimal(shortfall['required']):,.2f}, "
            f"verified ${Decimal(shortfall['verified']):,.2f})"
        )
    if ai_summary:
        # Any amount the sentence states must be the lender's own; otherwise the library's name.
        amounts = facts.money_in(ai_summary)
        if all(amount in facts.money_in(condition.verbatim_text) for amount in amounts):
            return ai_summary.strip()[:300]
    if condition_type is not None:
        return condition_type.name
    return condition.verbatim_text.strip().split(".")[0][:200]


def _explanation(condition: Condition, ai_explanation: object) -> str | None:
    """The "How we read it" sentence (S3-01). The AI's, only if every amount in it is the lender's."""
    if not isinstance(ai_explanation, str) or not ai_explanation.strip():
        return None
    lender_amounts = facts.money_in(condition.verbatim_text)
    if all(amount in lender_amounts for amount in facts.money_in(ai_explanation)):
        return ai_explanation.strip()[:400]
    return None


def _note_meaning(condition: Condition) -> str | None:
    for note in condition.underwriter_notes or []:
        meaning = facts.note_meaning(str(note.get("text") or ""))
        if meaning:
            return meaning
    return None


def compose_reading(
    condition: Condition,
    *,
    condition_type: ConditionType | None,
    confirmed: dict[str, Any] | None,
    ai: dict[str, Any] | None,
    round_: ConditionRound | None,
) -> tuple[dict[str, Any], ConditionReadingSource, ConditionReadingStatus, Decimal | None]:
    """Build one condition's reading. Pure apart from reading `settings`; tested directly."""
    text = condition.verbatim_text
    figures = _code_figures(condition, condition_type)
    push_back = facts.date_push_back(text, _must_not_close_before(round_))
    info_only = bool(condition.info_only)
    confidence: Decimal | None = None

    if confirmed:
        items = _items_from_confirmed(confirmed, condition_type)
        source, status = ConditionReadingSource.CONFIRMED, ConditionReadingStatus.CONFIRMED
    else:
        if condition_type is not None:
            items = [_item_from_library(item) for item in condition_type.items]
        else:
            items = []
        if ai is not None:
            ai_items = [raw for raw in ai.get("items") or [] if isinstance(raw, dict)]
            if condition_type is not None:
                by_key = {str(raw.get("key")): raw for raw in ai_items}
                for item in items:
                    raw = by_key.get(item["key"])
                    if raw is None:
                        continue
                    item["specifics"] = _checked_specifics(raw.get("specifics"), text)
                    _name_the_amount(item, condition_type)
                    widened = _performers(raw.get("performers"))
                    if widened and Performer(item["performers"][0]) in widened:
                        item["performers"] = [p.value for p in widened]
                # LP-954 — A CLAUSE THE TYPE DOES NOT COVER becomes an item of its own, after the
                # library's (1228's "possibly a Change of Circumstance" is the LO's re-disclosure). The
                # library still decides its own items; these are additions, never replacements.
                library_keys = {item["key"] for item in items}
                for raw in ai_items[:6]:
                    key = re.sub(r"[^a-z0-9_]", "", str(raw.get("key") or "").lower())[:40]
                    performers = _performers(raw.get("performers"))
                    if not key or key in library_keys or not performers:
                        continue
                    extra = _generic_item(performers[0], str(raw.get("name") or "")[:200])
                    extra["key"] = key
                    extra["performers"] = [p.value for p in performers]
                    extra["specifics"] = _checked_specifics(raw.get("specifics"), text)
                    items.append(extra)
                    library_keys.add(key)
            else:
                for index, raw in enumerate(ai_items[:6]):
                    performers = _performers(raw.get("performers"))
                    if not performers:
                        continue
                    item = _generic_item(performers[0], str(raw.get("name") or "")[:200])
                    item["key"] = f"item_{index + 1}"
                    item["performers"] = [p.value for p in performers]
                    item["specifics"] = _checked_specifics(raw.get("specifics"), text)
                    items.append(item)
            info_only = info_only or bool(ai.get("information_only") and not items)
            try:
                confidence = Decimal(str(ai.get("confidence"))).quantize(Decimal("0.01"))
            except (ArithmeticError, ValueError):
                confidence = None
            if confidence is not None and not (Decimal(0) <= confidence <= Decimal(1)):
                confidence = None
            source = ConditionReadingSource.AI
        else:
            source = ConditionReadingSource.LIBRARY

        if not items and condition_type is None and not info_only:
            performer = _OWNER_TO_PERFORMER.get(condition.owner_hint)
            if performer is not None:
                items = [_generic_item(performer)]

        bar = Decimal(str(settings.condition_reading_confidence_bar))
        # LP-954 — A CONDITIONAL CLAUSE NOTHING COVERS puts the reading below the bar, so she confirms
        # it before anything is drafted: the clauses a processor misses are the ones the AI drops.
        uncovered = (
            uncovered_conditionals(text, ai, items) if source is ConditionReadingSource.AI else []
        )
        if uncovered and confidence is not None and confidence >= bar:
            confidence = (bar - Decimal("0.01")).quantize(Decimal("0.01"))
        ready = (
            source is ConditionReadingSource.AI
            and confidence is not None
            and confidence >= bar
            and not uncovered
        )
        status = (
            ConditionReadingStatus.READY if ready else ConditionReadingStatus.NEEDS_CONFIRMATION
        )

    if condition.bucket_kind is BucketKind.LENDER_TO_CLEAR or (
        condition_type is not None and condition_type.default_option is PlanOption.LENDER_DOING_IT
    ):
        default_option: PlanOption | None = PlanOption.LENDER_DOING_IT
    elif info_only or (
        condition_type is not None and condition_type.default_option is PlanOption.INFORMATION_ONLY
    ):
        default_option = PlanOption.INFORMATION_ONLY
    else:
        default_option = None

    reading: dict[str, Any] = {
        "version": 1,
        "source": source.value,
        "type_id": condition_type.id if condition_type else None,
        "summary": _summary(condition, condition_type, figures, (ai or {}).get("summary")),
        "explanation": _explanation(condition, (ai or {}).get("explanation")),
        "information_only": default_option is PlanOption.INFORMATION_ONLY,
        "lender_doing_it": default_option is PlanOption.LENDER_DOING_IT,
        "note_meaning": _note_meaning(condition),
        "items": items,
        "figures": figures,
        "push_back": (
            {
                "must_not_close_before": push_back.must_not_close_before.isoformat(),
                "policy_starts": push_back.policy_starts.isoformat(),
            }
            if push_back
            else None
        ),
        "confidence": float(confidence) if confidence is not None else None,
        "prompt_version": READING_VERSION if source is ConditionReadingSource.AI else None,
        # LP-949 — THE AI'S PROPOSED LIBRARY TYPE for an untyped condition, kept only when it names a
        # real type. A proposal: nothing here uses it. It reaches the lender's "Codes to review", and a
        # type is applied only when a person maps the code there (ADR-417).
        "proposed_type_id": _proposed_type(condition_type, confirmed, ai),
        # LP-954 — the conditional clauses ("possibly", "if applicable", "and/or") nothing covers, in
        # the lender's words, for the confirm screen. Empty when every one has an item or a note.
        "uncovered": uncovered if not confirmed else [],
    }
    return reading, source, status, confidence


#: LP-954 — the owner's conditional words. A clause carrying one asks for something only sometimes, which
#: is exactly when it gets dropped. Whole words, case-insensitive.
CONDITIONAL = re.compile(r"\b(possibly|if applicable|and/or)\b", re.IGNORECASE)


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def uncovered_conditionals(
    text: str, ai: dict[str, Any] | None, items: list[dict[str, Any]]
) -> list[str]:
    """Each conditional clause in the lender's text that no item and no note covers. Code only.

    The AI says which item covers each clause it found (`clauses`). A conditional word is covered when a
    clause the AI quoted contains it, is really in the lender's text, SAYS MORE THAN THE WORD ITSELF, and
    names an item the reading has or a note saying why it asks for nothing. Anything else is reported in
    the lender's own words.

    WHAT THIS ESTABLISHES, AND WHAT IT CANNOT (LP-954 review). It catches the two failures that matter: a
    clause the model dropped, and a quote the lender never wrote. It cannot judge whether the named item
    really covers the clause — that is a reading, not a fact — so the floor is a real quote plus a real
    item key. The length test is what stops that floor falling to an echo of the word: quoting bare
    "possibly" and naming any existing item used to satisfy this. A clause that is nothing but the
    conditional phrase ("Provide X. If applicable.") now reads as uncovered, which asks her to look at a
    sentence no lender writes — the safe direction for a guard whose only cost is a confirmation.
    """
    plain_text = _plain(text)
    keys = {str(item.get("key")) for item in items}
    clauses = [c for c in (ai or {}).get("clauses") or [] if isinstance(c, dict)]
    out: list[str] = []
    for match in CONDITIONAL.finditer(text):
        word = match.group(0).casefold()
        covered = False
        for clause in clauses:
            quoted = _plain(str(clause.get("text") or ""))
            if not quoted or word not in quoted or quoted not in plain_text:
                continue
            if len(quoted) <= len(word):  # an echo of the word is not a clause (LP-954 review)
                continue
            if str(clause.get("item_key") or "") in keys or str(clause.get("note") or "").strip():
                covered = True
                break
        if not covered:
            start = max(0, match.start() - 40)
            out.append(re.sub(r"\s+", " ", text[start : match.end() + 40]).strip())
    return out


def _proposed_type(
    condition_type: ConditionType | None,
    confirmed: dict[str, Any] | None,
    ai: dict[str, Any] | None,
) -> str | None:
    if condition_type is not None or confirmed or ai is None:
        return None
    proposed = ai.get("library_type")
    if isinstance(proposed, str) and load_library().get(proposed) is not None:
        return proposed
    return None


# --------------------------------------------------------------------------------------------- #
# The round: one call, then every condition composed and recorded
# --------------------------------------------------------------------------------------------- #


def _file_summary(
    loan_file: LoanFile, lender: Lender | None, round_: ConditionRound
) -> dict[str, Any]:
    """The short summary principle 7 allows: never the snapshot, never a full number."""
    loan_facts = (round_.header or {}).get("loan_facts") or {}
    return {
        "borrowers": [b.first_name for b in (loan_file.borrowers or []) if not b.is_deleted][:4],
        "lender": lender.name if lender else None,
        "must_not_close_before": loan_facts.get("Must Not Close Before"),
        "earnest_money": loan_facts.get("Earnest Money Deposit"),
        "loan_purpose": loan_file.loan_purpose.value if loan_file.loan_purpose else None,
    }


def _ai_input(
    pending: list[tuple[int, Condition, ConditionType | None]],
    summary: dict[str, Any],
) -> str:
    conditions = []
    for ref, condition, condition_type in pending:
        entry: dict[str, Any] = {
            "ref": str(ref),
            "code": condition.lender_code or "",
            "text": condition.verbatim_text,
            "notes": [str(note.get("text") or "") for note in condition.underwriter_notes or []],
        }
        if condition_type is not None:
            entry["type"] = {
                "id": condition_type.id,
                "name": condition_type.name,
                "items": [
                    {"key": item.key, "name": item.name, "performer": item.performer.value}
                    for item in condition_type.items
                ],
            }
        conditions.append(entry)
    request: dict[str, Any] = {"file": summary, "conditions": conditions}
    if any(condition_type is None for _, _, condition_type in pending):
        # LP-949 — only when a condition has no type, so the model has something to propose from.
        request["library"] = [
            {"id": each.id, "name": each.name}
            for each in sorted(load_library().types.values(), key=lambda t: t.id)
        ]
    return json.dumps(request)


async def _ask_model(prompt_input: str, outcome: RoundReading) -> dict[str, dict[str, Any]] | None:
    """The one call. Returns ref → the model's entry, or None (and records why) when it cannot."""
    try:
        result = await complete(
            model=settings.anthropic_model_extraction,
            system=load_prompt(PROMPT_PATH),
            messages=[{"role": "user", "content": prompt_input}],
            max_tokens=_MAX_TOKENS,
            temperature=0.0,
        )
    except AIClientError as exc:
        outcome.error = type(exc).__name__
        return None
    outcome.model = result.model
    outcome.input_tokens = result.input_tokens
    outcome.output_tokens = result.output_tokens
    outcome.cost_estimate = estimate_cost(
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cache_read_tokens=result.cache_read_tokens,
        cache_write_tokens=result.cache_write_tokens,
    )
    snippet = extract_json_object(result.text)
    try:
        payload = json.loads(snippet) if snippet else None
    except (json.JSONDecodeError, ValueError):
        payload = None
    if not isinstance(payload, dict) or not isinstance(payload.get("conditions"), list):
        outcome.error = "unreadable_response"
        return None
    return {
        str(entry.get("ref")): entry
        for entry in payload["conditions"]
        if isinstance(entry, dict) and entry.get("ref") is not None
    }


async def _confirmed_by_code(db: AsyncSession, lender_id: UUID | None) -> dict[str, dict[str, Any]]:
    if lender_id is None:
        return {}
    rows = (
        await db.execute(
            select(LenderConditionCode.code, LenderConditionCode.confirmed_reading).where(
                LenderConditionCode.lender_id == lender_id,
                LenderConditionCode.confirmed_reading.is_not(None),
            )
        )
    ).all()
    return {code: saved for code, saved in rows if saved}


async def read_round(db: AsyncSession, *, round_id: UUID, use_ai: bool = True) -> RoundReading:
    """Read every not-yet-read condition on this round's file. Flushes; the caller commits.

    CONDITIONS ALREADY READ ARE LEFT ALONE: a condition seen again keeps its reading and its plan (plan
    §4a change 3). Only `unread` conditions go to the model, in ONE call.
    """
    outcome = RoundReading()
    round_ = await db.get(ConditionRound, round_id)
    if round_ is None:
        return outcome
    loan_file = await db.get(LoanFile, round_.loan_file_id)
    if loan_file is None:
        return outcome
    await db.refresh(loan_file, ["borrowers"])
    lender = await db.get(Lender, loan_file.lender_id) if loan_file.lender_id else None

    unread = list(
        (
            await db.execute(
                select(Condition)
                .where(
                    Condition.loan_file_id == loan_file.id,
                    Condition.reading_status == ConditionReadingStatus.UNREAD,
                    Condition.lender_status != ConditionLenderStatus.SUPERSEDED,
                    Condition.deleted_at.is_(None),
                )
                .order_by(Condition.sequence, Condition.created_at)
            )
        )
        .scalars()
        .all()
    )
    if not unread:
        round_.reading_run = outcome.as_run()
        return outcome

    library = load_library()
    confirmed = await _confirmed_by_code(db, loan_file.lender_id)
    pending: list[tuple[int, Condition, ConditionType | None]] = []
    for ref, condition in enumerate(unread, start=1):
        if condition.lender_code and condition.lender_code in confirmed:
            continue
        pending.append((ref, condition, library.get(condition.canonical_type_id)))

    answers: dict[str, dict[str, Any]] | None = None
    if use_ai and pending:
        outcome.used_ai = True
        answers = await _ask_model(
            _ai_input(pending, _file_summary(loan_file, lender, round_)), outcome
        )
    outcome.fell_back = outcome.used_ai and answers is None

    for ref, condition in enumerate(unread, start=1):
        condition_type = library.get(condition.canonical_type_id)
        saved = confirmed.get(condition.lender_code or "")
        ai_entry = (answers or {}).get(str(ref)) if answers is not None else None
        reading, source, status, confidence = compose_reading(
            condition,
            condition_type=condition_type,
            confirmed=saved,
            ai=ai_entry if not saved else None,
            round_=round_,
        )
        condition.reading = reading
        condition.reading_source = source
        condition.reading_status = status
        condition.reading_confidence = confidence
        db.add(
            ConditionEvent(
                company_id=condition.company_id,
                loan_file_id=condition.loan_file_id,
                condition_id=condition.id,
                round_id=round_.id,
                kind=ConditionEventKind.CONDITION_READ,
                detail={
                    "source": source.value,
                    "type_id": reading["type_id"],
                    "status": status.value,
                    "confidence": reading["confidence"],
                    "items": len(reading["items"]),
                },
            )
        )
        outcome.read += 1
        outcome.condition_ids.append(condition.id)
        if status is ConditionReadingStatus.NEEDS_CONFIRMATION:
            outcome.needs_confirmation += 1

    if loan_file.lender_id is not None:
        # LP-949 — an unmapped code's proposal goes to that lender's review queue, for a person.
        from app.services.condition_lender import record_proposals

        await record_proposals(
            db,
            lender_id=loan_file.lender_id,
            conditions=[c for c in unread if c.lender_id == loan_file.lender_id],
        )
    round_.reading_run = outcome.as_run()
    await db.flush()
    logger.info(
        "condition_round_read",
        round_id=str(round_.id),
        read=outcome.read,
        needs_confirmation=outcome.needs_confirmation,
        used_ai=outcome.used_ai,
        fell_back=outcome.fell_back,
        model=outcome.model,
    )
    return outcome


class ReadingRefused(Exception):
    """A confirm the reading cannot take; `reason` is shown to her."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ConfirmedItem:
    """One item as she confirmed it on S3-03: the wording she left, and who acts."""

    name: str
    performers: tuple[Performer, ...]
    key: str | None = None


def _confirmed_items(
    items: list[ConfirmedItem], condition_type: ConditionType | None
) -> list[dict[str, Any]]:
    library_items = {item.key: item for item in (condition_type.items if condition_type else ())}
    out: list[dict[str, Any]] = []
    for index, confirmed in enumerate(items, start=1):
        name = confirmed.name.strip()
        if not name:
            raise ReadingRefused("Each item needs a few words saying what it is.")
        if not confirmed.performers:
            raise ReadingRefused("Each item needs someone to act on it.")
        base = library_items.get(confirmed.key or "")
        item = _item_from_library(base) if base else _generic_item(confirmed.performers[0], name)
        item["key"] = base.key if base else (confirmed.key or f"item_{index}")
        item["name"] = name[:200]
        item["performers"] = [performer.value for performer in confirmed.performers][:3]
        if base is None:
            item["option"] = option_for(confirmed.performers[0]).value
        out.append(item)
    if not out:
        raise ReadingRefused("A condition needs at least one item. Remove the condition instead.")
    return out


async def _record_confirmed(
    db: AsyncSession,
    *,
    condition: Condition,
    items: list[dict[str, Any]],
    actor_user_id: UUID,
    saved_for_code: bool,
    how: str,
) -> None:
    reading = dict(condition.reading or {})
    reading.update({"items": items, "source": ConditionReadingSource.CONFIRMED.value})
    reading.setdefault("summary", condition.verbatim_text.strip().split(".")[0][:200])
    condition.reading = reading
    condition.reading_source = ConditionReadingSource.CONFIRMED
    condition.reading_status = ConditionReadingStatus.CONFIRMED
    db.add(
        ConditionEvent(
            company_id=condition.company_id,
            loan_file_id=condition.loan_file_id,
            condition_id=condition.id,
            round_id=condition.last_seen_round_id,
            kind=ConditionEventKind.CONDITION_READING_CONFIRMED,
            actor_user_id=actor_user_id,
            detail={"how": how, "items": len(items), "saved_for_code": saved_for_code},
        )
    )
    await db.flush()


async def confirm_reading(
    db: AsyncSession,
    *,
    condition: Condition,
    items: list[ConfirmedItem],
    actor_user_id: UUID,
) -> None:
    """S3-03's "This is right": her items replace the reading, and are saved for this lender code.

    SAVED WITHOUT SPECIFICS. What is remembered for the code is each item's key, name, performers and
    option — never an amount, an account or a person — so the next file's reading carries her split,
    not this borrower's data.
    """
    condition_type = load_library().get(condition.canonical_type_id)
    built = _confirmed_items(items, condition_type)
    # Keep this file's specifics on items she kept, matched by key.
    previous = {str(item.get("key")): item for item in (condition.reading or {}).get("items") or []}
    for item in built:
        if item["key"] in previous:
            item["specifics"] = previous[item["key"]].get("specifics") or _empty_specifics()
    saved = False
    if condition.lender_id is not None and condition.lender_code:
        code_row = await db.scalar(
            select(LenderConditionCode).where(
                LenderConditionCode.lender_id == condition.lender_id,
                LenderConditionCode.code == condition.lender_code,
            )
        )
        if code_row is not None:
            code_row.confirmed_reading = {
                "items": [
                    {
                        "key": item["key"],
                        "name": item["name"],
                        "performers": item["performers"],
                        "option": item["option"],
                    }
                    for item in built
                ]
            }
            saved = True
    await _record_confirmed(
        db,
        condition=condition,
        items=built,
        actor_user_id=actor_user_id,
        saved_for_code=saved,
        how="edited",
    )


async def use_library_default(
    db: AsyncSession, *, condition: Condition, actor_user_id: UUID
) -> None:
    """S3-03's "Use the library default": the library type's own items, confirmed as they stand."""
    condition_type = load_library().get(condition.canonical_type_id)
    if condition_type is None or not condition_type.items:
        raise ReadingRefused(
            "The library has no items for this condition. Edit the reading and confirm it instead."
        )
    items = [_item_from_library(item) for item in condition_type.items]
    await _record_confirmed(
        db,
        condition=condition,
        items=items,
        actor_user_id=actor_user_id,
        saved_for_code=False,
        how="library",
    )


__all__ = [
    "PROMPT_PATH",
    "READING_VERSION",
    "ConfirmedItem",
    "ReadingRefused",
    "RoundReading",
    "compose_reading",
    "confirm_reading",
    "option_for",
    "read_round",
    "use_library_default",
]
