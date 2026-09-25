"""Attaching a lender's PDF to a round that was pasted (LP-907 section 2, spec §LP-907).

The processor pasted what they could see in the portal; the letter itself arrives later. It must
enrich THE SAME ROUND — a second round would make round 2 appear twice on the strip and split one
sheet's conditions across two of them.

⚠️ THIS DOES NOT REUSE THE PARSE TASK'S COMPARE-AND-SET, AND THAT IS THE CENTRAL DECISION HERE.
`app/tasks/conditions.py` settles a parse with one conditional UPDATE guarded on `status = PARSING`.
Moving a round back to `PARSING` so that machinery could re-read it would break the very property it
was built for: the guard could no longer tell "a retry of the parse that created this round" from "a
re-parse of a round a processor is already reviewing", because both would be `PARSING`. Worse, it
would make a re-parse — which that module deliberately requires as an explicit, auditable act,
precisely so a re-enqueue cannot silently overwrite a DRAFT under review — into something a file
upload does silently through a different door.

So enrich has its own transition, guarded on the round's CURRENT status.

⚠️ THE GUARD IS "AN ACTIVE ROUND WITH NO PDF SOURCE YET", NOT "status = DRAFT". Spec §LP-907 says the
merge "works for DRAFT and IMPORTED rounds", and screen S1-08 puts the "Attach the lender's PDF"
button on an imported round card. One predicate covers both statuses AND makes attaching twice
refuse, the same way the forward door now refuses a second forward of one attachment.

⚠️ ADDITIVE ONLY, AND THAT RULE IS OURS RATHER THAN THE SPEC'S. The spec says to fill MISSING code,
category and bucket on matched rows, add unmatched PDF rows, and keep unmatched pasted ones with a
warning. It is silent on what happens when a PDF row's code CONTRADICTS a pasted row's rather than
filling a hole. The rule taken here: the PDF may fill a hole, never overwrite a value a processor can
already see, and `verbatim_text` is never touched by a merge — it is the lender's words either way,
and overwriting reviewed content is the one thing that loses work. A full re-read stays a separate,
explicit act. Stated so a later reader does not assume the spec settled it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.conditions.fingerprint import fingerprint
from app.conditions.readers.model import ParsedRow, ParsedSheet
from app.conditions.sheet_read import header_with_clause, sheet_from_bytes
from app.models.base import utcnow
from app.models.condition import Condition
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import (
    ConditionRound,
    ConditionRoundStatus,
    ConditionSheetFormat,
    ConditionSourceKind,
)
from app.models.helpers import only_active
from app.schemas.condition import DraftRowPublic
from app.services.condition_rounds import (
    ConditionSheetRejected,
    draft_rows_json,
    parse_report_for,
    reject_unless_pdf,
)
from app.storage import get_storage_backend

#: The statuses a round may be enriched in. `PARSING` is excluded because the parse task owns that
#: state; `PARSE_FAILED` and `DISCARDED` because there is nothing to merge into.
ENRICHABLE = (ConditionRoundStatus.DRAFT, ConditionRoundStatus.IMPORTED)


class RoundNotEnrichable(Exception):
    """The round cannot take a PDF, with the reason a processor can act on."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class EnrichResult:
    """What the merge did, for the response, the event and screen S1-09's success callout."""

    round_: ConditionRound
    filled_header: bool = False
    filled_expiry: bool = False
    filled_date_printed: bool = False
    #: Rows that already existed and gained a code, category or bucket from the PDF.
    matched: int = 0
    #: PDF rows the paste did not carry — new conditions in THIS round.
    added: int = 0
    #: ⚠️ Pasted rows the PDF does not contain. KEPT, never removed (ADR-404: a partial source may
    #: add and update, never remove or clear), and surfaced as a warning so the processor can look.
    unmatched_existing: list[str] = field(default_factory=list)

    @property
    def warnings(self) -> list[str]:
        if not self.unmatched_existing:
            return []
        return [
            f"{len(self.unmatched_existing)} pasted condition(s) are not on the lender's PDF; "
            f"they were kept, not removed"
        ]


def _has_pdf_source(round_: ConditionRound) -> bool:
    """Has a PDF already been merged into this round?

    Keyed on `storage_path` rather than on `kind`, deliberately: a round created by upload or by
    forward carries stored bytes, a pasted one does not, and it is the BYTES that make a second
    attach meaningless. `kind` would need a list of three values kept in step with the enum.
    """
    return any(source.get("storage_path") for source in (round_.sources or []))


def _match_key(code: str | None, text: str) -> tuple[str | None, str]:
    return (code or None, fingerprint(text))


def _merge_row(existing: dict[str, Any], pdf_row: ParsedRow) -> bool:
    """Fill what the paste could not carry. Returns whether anything changed.

    ⚠️ `verbatim_text` IS NEVER TOUCHED, and neither is any value already present. The paste is what
    the processor typed and may have edited on the review screen; the PDF fills holes.
    """
    changed = False
    for field_name, value in (
        ("lender_code", pdf_row.lender_code),
        ("lender_category", pdf_row.lender_category),
        ("bucket_heading", pdf_row.bucket_heading),
    ):
        if value and not existing.get(field_name):
            existing[field_name] = value
            changed = True
    if pdf_row.bucket_kind and existing.get("bucket_kind") in (None, "", "unknown"):
        existing["bucket_kind"] = pdf_row.bucket_kind.value
        changed = True
    return changed


def _merge_draft_rows(round_: ConditionRound, sheet: ParsedSheet, result: EnrichResult) -> None:
    """Merge into a DRAFT round's `draft_rows`, which are JSON and have no identity yet."""
    rows: list[dict[str, Any]] = list(round_.draft_rows or [])
    # ⚠️ CAPTURED BEFORE ANYTHING IS APPENDED. "Pasted rows the PDF did not carry" must not include
    # rows the PDF itself just added — they are unmatched by construction, and counting them would
    # report every new condition as a missing one in the same breath.
    was_already_here = {id(row) for row in rows}
    by_key = {_match_key(row.get("lender_code"), row.get("verbatim_text", "")): row for row in rows}
    # The second pass the spec asks for: "(code, fingerprint), then fingerprint alone". A pasted row
    # usually has NO code, so the fingerprint-only pass is the one that does the work here.
    by_text = {fingerprint(row.get("verbatim_text", "")): row for row in rows}

    matched_rows: set[int] = set()
    for pdf_row in sheet.rows:
        target = by_key.get(_match_key(pdf_row.lender_code, pdf_row.verbatim_text)) or by_text.get(
            fingerprint(pdf_row.verbatim_text)
        )
        if target is None:
            rows.append(
                DraftRowPublic.model_validate(pdf_row, from_attributes=True).model_dump(mode="json")
            )
            result.added += 1
            continue
        matched_rows.add(id(target))
        if _merge_row(target, pdf_row):
            result.matched += 1

    result.unmatched_existing = [
        row.get("verbatim_text", "")[:80]
        for row in rows
        if id(row) in was_already_here and id(row) not in matched_rows
    ]
    # Re-sequence so the review screen reads in sheet order with the added rows in place.
    for index, row in enumerate(rows, start=1):
        row["sequence"] = index
    round_.draft_rows = rows


async def _merge_conditions(
    db: AsyncSession,
    round_: ConditionRound,
    sheet: ParsedSheet,
    result: EnrichResult,
    *,
    actor_user_id: UUID | None = None,
) -> None:
    """Merge into an IMPORTED round's `conditions`, which are real rows with identity."""
    existing = list(
        (
            await db.scalars(
                only_active(
                    select(Condition).where(Condition.last_seen_round_id == round_.id), Condition
                )
            )
        ).all()
    )
    by_key = {_match_key(c.lender_code, c.verbatim_text): c for c in existing}
    by_text = {c.text_fingerprint: c for c in existing}

    matched: set[UUID] = set()
    for pdf_row in sheet.rows:
        target = by_key.get(_match_key(pdf_row.lender_code, pdf_row.verbatim_text)) or by_text.get(
            fingerprint(pdf_row.verbatim_text)
        )
        if target is None:
            created = Condition(
                company_id=round_.company_id,
                loan_file_id=round_.loan_file_id,
                lender_id=round_.lender_id,
                first_round_id=round_.id,
                last_seen_round_id=round_.id,
                sequence=pdf_row.sequence,
                lender_code=pdf_row.lender_code,
                lender_category=pdf_row.lender_category,
                bucket_heading=pdf_row.bucket_heading,
                bucket_kind=pdf_row.bucket_kind,
                verbatim_text=pdf_row.verbatim_text,
                text_fingerprint=fingerprint(pdf_row.verbatim_text),
                underwriter_notes=[
                    {"date": n.date.isoformat() if n.date else None, "text": n.text}
                    for n in pdf_row.underwriter_notes
                ],
                owner_hint=pdf_row.owner_hint,
                owner_hint_source=pdf_row.owner_hint_source,
            )
            db.add(created)
            # ⚠️ THE EVENT IS NOT DECORATION HERE — IT IS THE ONLY RECORD THAT THIS CONDITION WAS ON
            # THIS SHEET, and an earlier version of this branch omitted it.
            #
            # Import is not the only writer of conditions; this is the second. "Which rounds did a
            # condition appear on" is derived from `CONDITION_CREATED` / `CONDITION_SEEN_AGAIN`
            # events (spec §LP-909), so a condition created without one gets NO round chips at all
            # — while its own `first_round_id` and `last_seen_round_id` both point at this very
            # round — and the round's own count undercounts by exactly the number added here.
            #
            # Reachable rather than theoretical: it is the paste-then-attach-PDF flow on an already
            # imported round, which is precisely what `attach-pdf` was built for.
            #
            # `flush` first, because the event needs the condition's id and `db.add` alone does not
            # assign one.
            await db.flush()
            db.add(
                ConditionEvent(
                    company_id=round_.company_id,
                    loan_file_id=round_.loan_file_id,
                    round_id=round_.id,
                    condition_id=created.id,
                    kind=ConditionEventKind.CONDITION_CREATED,
                    actor_user_id=actor_user_id,
                    # Counts, codes and names only — never the lender's wording (spec §9.5).
                    detail={"source": "attach_pdf", "lender_code": created.lender_code},
                )
            )
            result.added += 1
            continue

        matched.add(target.id)
        changed = False
        if pdf_row.lender_code and not target.lender_code:
            target.lender_code = pdf_row.lender_code
            changed = True
        if pdf_row.lender_category and not target.lender_category:
            target.lender_category = pdf_row.lender_category
            changed = True
        if pdf_row.bucket_heading and not target.bucket_heading:
            target.bucket_heading = pdf_row.bucket_heading
            changed = True
        if changed:
            result.matched += 1
            db.add(
                ConditionEvent(
                    company_id=round_.company_id,
                    loan_file_id=round_.loan_file_id,
                    round_id=round_.id,
                    condition_id=target.id,
                    kind=ConditionEventKind.CONDITION_EDITED,
                    detail={"filled_from": "pdf", "lender_code": target.lender_code},
                )
            )

    result.unmatched_existing = [c.verbatim_text[:80] for c in existing if c.id not in matched]


async def enrich_round_with_pdf(
    db: AsyncSession,
    *,
    round_: ConditionRound,
    content: bytes,
    declared_content_type: str | None = None,
    actor_user_id: UUID | None = None,
) -> EnrichResult:
    """Merge a lender's PDF into an existing round. Never creates a second round.

    The caller owns the transaction, as every service here does.
    """
    if round_.status not in ENRICHABLE:
        raise RoundNotEnrichable(
            f"A round that is {round_.status.value} cannot take a PDF. "
            "Only a draft or an imported round can be enriched."
        )
    if _has_pdf_source(round_):
        raise RoundNotEnrichable(
            "This round already has the lender's PDF. Attaching a second one would merge the same "
            "sheet twice."
        )

    reject_unless_pdf(content, declared_content_type=declared_content_type)
    # ⚠️ THE SOURCE TEXT IS DELIBERATELY DISCARDED HERE, and that is not the same decision the parse
    # task makes. `sheet_from_bytes` now returns the lender's page so a PDF round can be AI-split
    # (LP-908 review), and the parse task persists it to `raw_text`. This is an ENRICH: it merges a
    # SECOND PDF into a round that already exists, and for a pasted round `raw_text` is the page the
    # processor actually pasted — the exact string §9.3's substring check validates the model's rows
    # against. Overwriting it with a later PDF's text would quietly change what "AI only splits" is
    # checked against, on a round whose rows a processor may already be reviewing.
    #
    # Named with `_` rather than ignored, so the next reader sees a choice instead of an oversight.
    reader, sheet, _source_text = sheet_from_bytes(content)

    storage_path = f"condition-sheets/{round_.company_id}/{round_.loan_file_id}/{uuid4().hex}.pdf"
    await get_storage_backend().save_at(storage_path=storage_path, content=content)

    result = EnrichResult(round_=round_)

    # ⚠️ FILL, NEVER REPLACE. A pasted round has no letterhead, so these are holes; a round that
    # somehow has them keeps what it has.
    # ⚠️ THE CLAUSE COMES WITH IT, AND THIS IS THE PATH THAT MATTERS MOST FOR IT. S1-09 shows the
    # mortgagee clause on the round-details sheet AFTER a PDF is attached to a pasted round — which
    # is exactly this branch — so dropping it here would leave the screen it was drawn for empty.
    header = header_with_clause(sheet)
    if header and not round_.header:
        round_.header = header
        result.filled_header = True
    if sheet.expiry_dates and not round_.expiry_dates:
        round_.expiry_dates = {
            key: value.isoformat() if value else None for key, value in sheet.expiry_dates.items()
        }
        result.filled_expiry = True
    if sheet.date_printed and not round_.date_printed:
        round_.date_printed = sheet.date_printed
        result.filled_date_printed = True
    # The PDF names the layout with certainty; a pasted round's format was inferred from row shapes.
    if round_.sheet_format is ConditionSheetFormat.PASTED_TEXT:
        round_.sheet_format = sheet.sheet_format

    if round_.status is ConditionRoundStatus.IMPORTED:
        await _merge_conditions(db, round_, sheet, result, actor_user_id=actor_user_id)
    else:
        _merge_draft_rows(round_, sheet, result)

    now = utcnow()
    source: dict[str, object] = {
        "kind": ConditionSourceKind.PDF_UPLOAD.value,
        "at": now.isoformat(),
        "storage_path": storage_path,
    }
    if actor_user_id is not None:
        source["user_id"] = str(actor_user_id)
    # A new list rather than `.append`: SQLAlchemy does not track in-place mutation of a JSONB list,
    # and an appended element would simply not be written.
    round_.sources = [*(round_.sources or []), source]

    report = parse_report_for(reader, sheet)
    report["warnings"] = [*report.get("warnings", []), *result.warnings]
    round_.parse_report = report

    db.add(
        ConditionEvent(
            company_id=round_.company_id,
            loan_file_id=round_.loan_file_id,
            round_id=round_.id,
            kind=ConditionEventKind.ROUND_ENRICHED,
            actor_user_id=actor_user_id,
            # Counts and names only — never the sheet's text (spec §9.5).
            detail={
                "reader": reader,
                "matched": result.matched,
                "added": result.added,
                "unmatched_existing": len(result.unmatched_existing),
                "filled_header": result.filled_header,
                "filled_expiry": result.filled_expiry,
            },
        )
    )
    await db.flush()
    return result


__all__ = [
    "ENRICHABLE",
    "ConditionSheetRejected",
    "EnrichResult",
    "RoundNotEnrichable",
    "draft_rows_json",
    "enrich_round_with_pdf",
]
