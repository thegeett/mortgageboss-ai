"""The round's package for the lender (LP-925, S3-10): one PDF and one note per ready condition.

WHAT GOES IN. The newest imported round's conditions that are Ready to send, open with the lender and
not information-only — whatever their heading (S3-10 packages 0006). Prior-to-funding conditions not yet
ready are named in an info line: they go with the closing package. The documents are the
ones their items accepted (LP-923) plus a document an item found already in the file; they are merged
into `{code} - {Category}.pdf`, in item order. A condition with no document (a push-back) has no file,
and its note says why.

THE NOTES. Code writes a note for every row from the row's facts. One AI call then words them all; a
worded note is used only if every number in it appears in its row's facts (otherwise the code's note
stays). She edits any note and her edit is kept. Decision 4: the note is in the package and in "Copy all
notes".

MARK SUBMITTED moves the ticked conditions to Sent to lender through Stage 2's `move_prep_status` —
the one way our track moves — and freezes the rows as the record of what was sent. The lender's track is
never touched here. Nothing is uploaded or sent by the app.
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.conditions.library import load_library
from app.models.activity_log import ActivityType
from app.models.condition import (
    BucketKind,
    Condition,
    ConditionLenderStatus,
    ConditionPrepStatus,
)
from app.models.condition_evidence import ConditionEvidence
from app.models.condition_item import ConditionItem
from app.models.condition_package import ConditionPackage, PackageStatus
from app.models.condition_round import ConditionRound, ConditionRoundStatus
from app.models.condition_vocabulary import ConditionItemStatus, PlanOption
from app.models.document import Document
from app.models.lender import Lender
from app.models.loan_file import LoanFile

logger = structlog.get_logger(__name__)

PROMPT_PATH = "conditions/package_notes_v1.txt"
_MAX_TOKENS = 3000
_OPEN = (ConditionLenderStatus.OPEN, ConditionLenderStatus.NOT_CLEARED)
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_MONTH_NAMES = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
#: The letter's expiry kind for a document type (evidence expiring before close-by).
_EXPIRY_KIND = {"bank_statement": "asset", "investment_account": "asset", "pay_stub": "income"}


class PackageRefused(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# --------------------------------------------------------------------------------------------- #
# What goes in
# --------------------------------------------------------------------------------------------- #


async def newest_round(db: AsyncSession, loan_file_id: UUID) -> ConditionRound | None:
    return (
        await db.execute(
            select(ConditionRound)
            .where(
                ConditionRound.loan_file_id == loan_file_id,
                ConditionRound.status == ConditionRoundStatus.IMPORTED,
                ConditionRound.deleted_at.is_(None),
            )
            .order_by(ConditionRound.round_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _round_conditions(db: AsyncSession, round_: ConditionRound) -> list[Condition]:
    return list(
        (
            await db.execute(
                select(Condition)
                .where(Condition.last_seen_round_id == round_.id, Condition.deleted_at.is_(None))
                .order_by(Condition.sequence)
            )
        ).scalars()
    )


def _goes_in(condition: Condition) -> bool:
    """Ready to send and still open with the lender. A READY prior-to-funding condition goes in too
    (S3-10 packages 0006); only the prior-to-funding ones not yet ready wait for the closing package."""
    return (
        condition.prep_status is ConditionPrepStatus.READY
        and condition.lender_status in _OPEN
        and not condition.info_only
    )


def _category(condition: Condition) -> str:
    """`Assets`, `Disclosure`, `Invoice` — the library type's category, else the lender's own."""
    library_type = load_library().get(condition.canonical_type_id)
    if library_type is not None:
        return library_type.category.value.capitalize()
    return (condition.lender_category or "Condition").strip()


async def _documents(db: AsyncSession, condition: Condition) -> list[Document]:
    """The documents the condition's done items accepted, then any found already in the file."""
    from app.services.condition_evidence import counts_as_evidence

    items = list(
        (
            await db.execute(
                select(ConditionItem)
                .where(
                    ConditionItem.condition_id == condition.id, ConditionItem.deleted_at.is_(None)
                )
                .order_by(ConditionItem.sequence)
            )
        ).scalars()
    )
    ids: list[UUID] = []
    for item in items:
        if item.status is not ConditionItemStatus.DONE:
            continue
        evidence = (
            await db.execute(
                select(ConditionEvidence)
                .where(ConditionEvidence.item_id == item.id)
                .order_by(ConditionEvidence.created_at)
            )
        ).scalars()
        for row in evidence:
            if counts_as_evidence(row) and row.document_id not in ids:
                ids.append(row.document_id)
        if item.document_id and item.document_id not in ids:
            ids.append(item.document_id)
    if not ids:
        return []
    found = {
        d.id: d
        for d in (
            await db.execute(
                select(Document)
                .options(selectinload(Document.extractions))
                .where(Document.id.in_(ids), Document.deleted_at.is_(None))
            )
        ).scalars()
    }
    return [found[i] for i in ids if i in found]


async def _pages(document: Document) -> int | None:
    """Pages from the stored PDF; else the extraction's deterministic count."""
    from app.services.condition_evidence import _extraction_data, _int, _value
    from app.services.pdf_utils import pdf_page_count
    from app.storage import get_storage_backend

    try:
        content = await get_storage_backend().read(document.storage_path)
        counted = await pdf_page_count(content)
        if counted:
            return counted
    except Exception:
        pass
    return _int(_value(_extraction_data(document) or {}, "page_count_present"))


# --------------------------------------------------------------------------------------------- #
# The notes: code writes every one; the AI may word them, numbers checked by code
# --------------------------------------------------------------------------------------------- #


def _money(value: Decimal) -> str:
    return f"${value:,.2f}"


async def _row_facts(
    db: AsyncSession, condition: Condition, documents: list[Document]
) -> tuple[dict[str, Any], str]:
    """`(facts for the model, the code's note)`. Every figure here is code's."""
    from app.services.condition_evidence import (
        _decimal,
        _extraction_data,
        _months_covered,
        statement_from,
    )

    facts: dict[str, Any] = {
        "code": condition.lender_code,
        "asked": (condition.reading or {}).get("summary") or "",
        "documents": [],
    }
    # THE AMOUNTS THE CONDITION ASKS ABOUT, in the reading's own form ("$2,850.00"). The summary says
    # "$2,850", and the number check compares tokens, so a note restating the lender's own figure
    # with cents was refused and replaced by the plainer code note.
    asked_amounts = [
        amount
        for read in (condition.reading or {}).get("items") or []
        for amount in ((read or {}).get("specifics") or {}).get("amounts") or []
        if isinstance(amount, str)
    ]
    if asked_amounts:
        facts["amounts_asked"] = list(dict.fromkeys(asked_amounts))
    bank_documents = [d for d in documents if d.document_type == "bank_statement"]
    statements = [statement_from(_extraction_data(d)) for d in bank_documents]
    for s in statements:
        months = sorted(_months_covered(s))
        facts["documents"].append(
            {
                "kind": "bank statement",
                "bank": s.bank,
                "ending": s.last4,
                "months": [_MONTH_NAMES[int(m[5:]) - 1] for m in months],
                "pages": s.pages_present,
            }
        )
    others = [d for d in documents if d.document_type != "bank_statement"]
    for document in others:
        facts["documents"].append({"kind": document.document_type, "name": document.document_name})

    shortfall = ((condition.reading or {}).get("figures") or {}).get("shortfall") or {}
    evidence = list(
        (
            await db.execute(
                select(ConditionEvidence).where(ConditionEvidence.condition_id == condition.id)
            )
        ).scalars()
    )
    verified = None
    if statements:
        from app.services.condition_evidence import _verified

        verified = _verified(list(zip(bank_documents, statements, strict=True)))
    required = _decimal(shortfall.get("required"))
    if verified is not None and required is not None:
        facts["verified"] = _money(verified)
        facts["required"] = _money(required)
    # From documents that are evidence, once per deposit: an answer reaches the same deposit on every
    # statement of the account (Stage 3B acceptance), so the rejected copy must not say it twice.
    from app.services.condition_evidence import counts_as_evidence

    explained = list(
        {
            (f.get("date"), f.get("amount")): f
            for e in evidence
            if counts_as_evidence(e)
            for f in (e.findings or [])
            if f.get("status") == "explained"
        }.values()
    )
    if explained:
        facts["deposits_sourced"] = [
            {"date": f.get("date"), "amount": _money(Decimal(f["amount"])), "how": f.get("reason")}
            for f in explained
        ]
    push_back = (condition.reading or {}).get("push_back") or {}
    if not documents and push_back.get("must_not_close_before"):
        facts["must_not_close_before"] = _us(push_back["must_not_close_before"])
        facts["policy_starts"] = _us(push_back.get("policy_starts") or "")
    return facts, _code_note(condition, facts, statements)


def _us(iso: str) -> str:
    try:
        return date.fromisoformat(iso[:10]).strftime("%m/%d/%Y")
    except ValueError:
        return iso


def _code_note(condition: Condition, facts: dict[str, Any], statements: list[Any]) -> str:
    """The note code writes: plain, every figure from `facts`."""
    parts: list[str] = []
    for doc in facts["documents"]:
        if doc["kind"] == "bank statement":
            months = (
                " and ".join(m[:3] for m in doc["months"])
                if len(doc["months"]) > 1
                else (doc["months"][0] if doc["months"] else "")
            )
            noun = "statements" if len(doc["months"]) > 1 else "statement"
            pages = f", all {doc['pages']} pages" if doc.get("pages") else ""
            parts.append(
                f"{doc['bank']} ··{doc['ending']} {months} {noun}{pages}".replace("  ", " ")
            )
        else:
            parts.append(f"{doc.get('name') or doc['kind'].replace('_', ' ')} attached")
    if "verified" in facts:
        parts.append(f"{facts['verified']} verified against {facts['required']} required")
    for deposit in facts.get("deposits_sourced", []):
        on = deposit["date"][5:].replace("-", "/") if deposit.get("date") else ""
        parts.append(f"{on} deposit sourced".strip())
    if not facts["documents"] and "must_not_close_before" in facts:
        return (
            f"No document — the lender's letter shows Must Not Close Before "
            f"{facts['must_not_close_before']}, the policy's start date."
        )
    if not parts:
        return "No document."
    return "; ".join(parts) + "."


async def _word_notes(rows: list[dict[str, Any]]) -> dict[str, str]:
    """One model call for every row's note. Returns only notes whose numbers code confirmed."""
    from app.ai.client import complete
    from app.ai.finding_prose import unsupported_numbers_in
    from app.ai.parsing import extract_json_object
    from app.ai.prompt_loader import load_prompt
    from app.core.config import settings

    payload = [
        {"code": r["code"], "facts": r["_facts"], "plain_note": r["note"]}
        for r in rows
        if r.get("_facts")
    ]
    if not payload:
        return {}
    try:
        result = await complete(
            model=settings.anthropic_model_reasoning,
            system=load_prompt(PROMPT_PATH),
            messages=[{"role": "user", "content": json.dumps(payload)}],
            max_tokens=_MAX_TOKENS,
            temperature=0.0,
        )
        # `extract_json_object` returns the JSON TEXT, not a dict (the first version treated it as one,
        # so no worded note was ever used — caught by the test that expects one).
        parsed: Any = json.loads(extract_json_object(result.text or "") or "{}")
    except Exception:
        logger.info("package_notes_unavailable")
        return {}
    notes = parsed.get("notes") if isinstance(parsed, dict) else None
    if not isinstance(notes, dict):
        return {}
    out: dict[str, str] = {}
    for row in payload:
        text = notes.get(row["code"])
        if not isinstance(text, str) or not text.strip() or len(text) > 400:
            continue
        # NUMBERS ARE CODE'S: every number in the worded note must be in this row's own facts.
        if unsupported_numbers_in(json.dumps(row["facts"]), text):
            continue
        out[row["code"]] = text.strip()
    logger.info("package_notes_worded", rows=len(payload), used=len(out))
    return out


# --------------------------------------------------------------------------------------------- #
# Building, editing, submitting
# --------------------------------------------------------------------------------------------- #


async def open_package(db: AsyncSession, round_: ConditionRound) -> ConditionPackage | None:
    return (
        await db.execute(
            select(ConditionPackage)
            .where(ConditionPackage.round_id == round_.id)
            .order_by(ConditionPackage.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def build(
    db: AsyncSession, *, loan_file: LoanFile, actor_user_id: UUID, use_ai: bool = True
) -> ConditionPackage:
    """Build (or rebuild) the round's package: her edited notes are kept; newly ready rows are added."""
    from app.services.activity_log import log_activity
    from app.services.condition_plan import lender_condition_settings

    round_ = await newest_round(db, loan_file.id)
    if round_ is None:
        raise PackageRefused("There is no imported round to package.")
    package = await open_package(db, round_)
    if package is not None and package.status is PackageStatus.SUBMITTED:
        raise PackageRefused("This round's package was already submitted.")
    kept = {r["condition_id"]: r for r in (package.rows if package else [])}
    lender = await db.get(Lender, loan_file.lender_id) if loan_file.lender_id else None
    fields_asked = set(lender_condition_settings(lender).upload_fields)

    rows: list[dict[str, Any]] = []
    for condition in await _round_conditions(db, round_):
        if not _goes_in(condition):
            continue
        documents = await _documents(db, condition)
        facts, note = await _row_facts(db, condition, documents)
        pages = [await _pages(d) for d in documents]
        previous = kept.get(str(condition.id))
        row: dict[str, Any] = {
            "condition_id": str(condition.id),
            "code": condition.lender_code or "",
            "file_name": f"{condition.lender_code} - {_category(condition)}.pdf"
            if documents
            else None,
            "document_ids": [str(d.id) for d in documents],
            "pages": sum(p or 0 for p in pages) if documents else 0,
            "note": note,
            "note_source": "code",
            "fields": _fields(fields_asked, documents),
            "included": True,
            "_facts": facts,
        }
        if previous is not None and previous.get("note_source") == "edited":
            row["note"], row["note_source"] = previous["note"], "edited"
        if previous is not None:
            row["included"] = previous.get("included", True)
        rows.append(row)

    if use_ai:
        worded = await _word_notes([r for r in rows if r["note_source"] != "edited"])
        for row in rows:
            if row["note_source"] != "edited" and row["code"] in worded:
                row["note"], row["note_source"] = worded[row["code"]], "ai"
    for row in rows:
        row.pop("_facts", None)

    if package is None:
        package = ConditionPackage(
            company_id=loan_file.company_id,
            loan_file_id=loan_file.id,
            round_id=round_.id,
            rows=rows,
        )
        db.add(package)
    else:
        package.rows = rows
    await db.flush()
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.FILE_UPDATED,
        summary=f"Package built: {len(rows)} condition{'s' if len(rows) != 1 else ''}",
        actor_user_id=actor_user_id,
        detail={"section": "condition_package", "action": "build", "rows": len(rows)},
    )
    logger.info("condition_package_built", loan_file_id=str(loan_file.id), rows=len(rows))
    return package


def _fields(asked: set[str], documents: list[Document]) -> dict[str, str | None]:
    """Sun West's "Name of source" and "Date verified", filled by code when the lender asks (§4a 7)."""
    from app.services.condition_evidence import _extraction_data, _value

    out: dict[str, str | None] = {}
    if "name_of_source" in asked:
        names = [
            str(_value(_extraction_data(d) or {}, "bank_name") or d.document_name or "")
            for d in documents
        ]
        out["name_of_source"] = ", ".join(n for n in dict.fromkeys(names) if n) or None
    if "date_verified" in asked:
        out["date_verified"] = datetime.now(UTC).date().isoformat() if documents else None
    return out


async def update_row(
    db: AsyncSession,
    *,
    package: ConditionPackage,
    condition_id: UUID,
    note: str | None,
    included: bool | None,
    fields: dict[str, str | None] | None,
) -> None:
    """Her edit: a note (then marked hers), whether it is ticked, a lender field."""
    if package.status is PackageStatus.SUBMITTED:
        raise PackageRefused(
            "This package was submitted; it is kept as the record of what was sent."
        )
    rows = [dict(r) for r in package.rows]
    for row in rows:
        if row["condition_id"] != str(condition_id):
            continue
        if note is not None:
            if not note.strip():
                raise PackageRefused("A note cannot be empty.")
            row["note"], row["note_source"] = note.strip()[:600], "edited"
        if included is not None:
            row["included"] = included
        if fields:
            row["fields"] = {**(row.get("fields") or {}), **fields}
        package.rows = rows
        await db.flush()
        return
    raise PackageRefused("That condition is not in this package.")


async def mark_du_rerun_done(db: AsyncSession, *, package: ConditionPackage) -> None:
    package.du_rerun_done_at = datetime.now(UTC)
    await db.flush()


async def submit(
    db: AsyncSession, *, loan_file: LoanFile, package: ConditionPackage, actor_user_id: UUID
) -> list[str]:
    """ "Mark submitted": the ticked conditions to Sent to lender, and the rows frozen as the record."""
    from app.schemas.condition import PrepStatusRequest
    from app.services.activity_log import log_activity
    from app.services.condition_status import move_prep_status

    if package.status is PackageStatus.SUBMITTED:
        raise PackageRefused("This package was already submitted.")
    now = datetime.now(UTC)
    moved: list[str] = []
    # THE RECORD IS WHAT WAS SENT (LP-940 review). A condition withdrawn while the package was only built
    # is not sent, so it is not frozen into the record either; otherwise its refusal would later say it
    # "went to the lender", and an Undo could never be withdrawn again. Her reason is in its event.
    sent = await live_rows(db, package)
    for row in sent:
        if not row.get("included", True):
            continue
        condition = await db.get(Condition, UUID(row["condition_id"]))
        if condition is None or not _goes_in(condition):
            raise PackageRefused(
                f"{row['code']} is no longer ready to send — build the package again."
            )
        await move_prep_status(
            db,
            condition=condition,
            payload=PrepStatusRequest(to=ConditionPrepStatus.WITH_UNDERWRITER, sent_at=now),
            actor_user_id=actor_user_id,
        )
        moved.append(row["code"])
    if not moved:
        raise PackageRefused("Tick at least one condition to submit.")
    package.rows = sent
    package.status = PackageStatus.SUBMITTED
    package.submitted_at = now
    package.submitted_by_user_id = actor_user_id
    await db.flush()
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.FILE_UPDATED,
        summary=f"Package submitted: {len(moved)} condition{'s' if len(moved) != 1 else ''} sent to lender",
        actor_user_id=actor_user_id,
        detail={"section": "condition_package", "action": "submit", "codes": moved},
    )
    logger.info("condition_package_submitted", loan_file_id=str(loan_file.id), moved=len(moved))
    return moved


async def download(db: AsyncSession, *, package: ConditionPackage) -> tuple[bytes, list[str]]:
    """The zip: one merged PDF per included row with documents, and `notes.txt`. Returns (zip, missing)."""
    from app.services.pdf_utils import merge_pdfs
    from app.storage import get_storage_backend

    storage = get_storage_backend()
    buffer = io.BytesIO()
    missing: list[str] = []
    lines: list[str] = []
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for row in await live_rows(db, package):
            if not row.get("included", True):
                continue
            extra = "".join(
                f"\n  {label}: {row['fields'][key]}"
                for key, label in (
                    ("name_of_source", "Name of source"),
                    ("date_verified", "Date verified"),
                )
                if (row.get("fields") or {}).get(key)
            )
            lines.append(f"{row['code']} — {row['note']}{extra}")
            if not row.get("file_name"):
                continue
            parts: list[bytes] = []
            names: list[str] = []
            for document_id in row["document_ids"]:
                document = await db.get(Document, UUID(document_id))
                names.append(document.original_filename if document else document_id)
                try:
                    parts.append(await storage.read(document.storage_path) if document else b"")
                except Exception:
                    parts.append(b"")
            merged, unreadable = await merge_pdfs(parts)
            missing.extend(f"{row['code']}: {names[i]}" for i in unreadable)
            if merged is not None:
                archive.writestr(row["file_name"], merged)
        archive.writestr("notes.txt", "\n".join(lines) + "\n")
    return buffer.getvalue(), missing


# --------------------------------------------------------------------------------------------- #
# Read side
# --------------------------------------------------------------------------------------------- #


@dataclass
class PackageView:
    lender_short: str
    round_number: int | None
    status: str | None
    package_id: UUID | None
    rows: list[dict[str, Any]] = field(default_factory=list)
    ready_count: int = 0
    warnings: list[dict[str, str]] = field(default_factory=list)
    later_codes: list[str] = field(default_factory=list)
    cutoff: str | None = None
    cutoff_tz: str | None = None
    upload_fields: list[str] = field(default_factory=list)
    du_rerun_open: bool = False
    submitted_at: datetime | None = None


async def live_rows(db: AsyncSession, package: ConditionPackage) -> list[dict[str, Any]]:
    """The package's rows WITHOUT a withdrawn condition (LP-940). A built package stores its rows; a
    condition she withdraws afterwards leaves the view, the download and Mark submitted, and the stored
    rows are not rewritten. A submitted package is the record of what was sent: its rows are all live,
    because a condition in one cannot be withdrawn."""
    ids = [UUID(r["condition_id"]) for r in package.rows or []]
    if not ids:
        return []
    withdrawn = set(
        (
            await db.execute(
                select(Condition.id).where(Condition.id.in_(ids), Condition.deleted_at.is_not(None))
            )
        ).scalars()
    )
    return [dict(r) for r in package.rows if UUID(r["condition_id"]) not in withdrawn]


async def view(db: AsyncSession, *, loan_file: LoanFile) -> PackageView | None:
    """S3-10's panel: the package (or what would go in), its warnings, and the lender's cutoff."""
    from app.services import figures_check
    from app.services.condition_plan import lender_condition_settings

    round_ = await newest_round(db, loan_file.id)
    if round_ is None:
        return None
    lender = await db.get(Lender, loan_file.lender_id) if loan_file.lender_id else None
    settings = lender_condition_settings(lender)
    short = (lender.canonical_lender_key or "").upper() if lender is not None else ""
    package = await open_package(db, round_)
    conditions = await _round_conditions(db, round_)
    ready = [c for c in conditions if _goes_in(c)]
    out = PackageView(
        lender_short=short or (lender.name if lender is not None else "the lender"),
        round_number=round_.round_number,
        status=package.status.value if package else None,
        package_id=package.id if package else None,
        rows=await live_rows(db, package) if package else [],
        ready_count=len(ready),
        cutoff=settings.upload_cutoff,
        cutoff_tz=settings.upload_cutoff_tz,
        upload_fields=list(settings.upload_fields),
        submitted_at=package.submitted_at if package else None,
    )
    for condition in conditions:
        if condition.lender_status not in _OPEN or condition.info_only:
            continue
        if condition.bucket_kind is BucketKind.PRIOR_TO_FUNDING:
            if not _goes_in(condition):
                out.later_codes.append(condition.lender_code or "—")
            continue
        if condition.bucket_kind is BucketKind.PRIOR_TO_DOCS and not _goes_in(condition):
            out.warnings.append(
                {
                    "kind": "open_prior_to_docs",
                    "code": condition.lender_code or "—",
                    "text": _why_open(condition),
                }
            )
    out.warnings.extend(await _expiry_warnings(db, round_, out.rows))
    check = await figures_check.figures_check(db, loan_file=loan_file)
    out.du_rerun_open = check.du_rerun and not (package and package.du_rerun_done_at)
    if out.du_rerun_open:
        out.warnings.append(
            {"kind": "du_rerun", "code": "", "text": "The figures check says DU must be re-run."}
        )
    return out


def _why_open(condition: Condition) -> str:
    if condition.next_step is PlanOption.LENDER_DOING_IT:
        library_type = load_library().get(condition.canonical_type_id)
        what = (library_type.name if library_type else "it").lower()
        return f"the {what} is ordered through the lender and not back yet"
    return {
        ConditionPrepStatus.TO_DO: "nothing has been asked for yet",
        ConditionPrepStatus.WAITING: "we are still waiting for it",
        ConditionPrepStatus.WITH_UNDERWRITER: "it is with the underwriter",
    }.get(condition.prep_status, "it is not ready")


async def _expiry_warnings(
    db: AsyncSession, round_: ConditionRound, rows: list[dict[str, Any]]
) -> list[dict[str, str]]:
    """Evidence whose kind the letter says expires before the close-by date."""
    dates = round_.expiry_dates or {}
    close_by = _date(dates.get("close_by"))
    if close_by is None:
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        for document_id in row.get("document_ids", []):
            document = await db.get(Document, UUID(document_id))
            kind = _EXPIRY_KIND.get(document.document_type or "") if document else None
            expires = _date(dates.get(kind)) if kind else None
            if kind and expires and expires < close_by and kind not in seen:
                seen.add(kind)
                out.append(
                    {
                        "kind": "expiring",
                        "code": row["code"],
                        "text": f"{kind.capitalize()} documents expire {expires.strftime('%m/%d/%Y')}, "
                        f"before the close-by date {close_by.strftime('%m/%d/%Y')}",
                    }
                )
    return out


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None
