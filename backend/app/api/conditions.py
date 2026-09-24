"""Condition rounds — the arriving sheet (LP-905, spec §6).

A thin boundary, as every router in this repo is: validate the edges, hand the work to
`app/services/condition_rounds.py`, enqueue the read, answer. The PDF is parsed by a Celery task
rather than in the request, which is the opposite of the MISMO import — MISMO is fast deterministic
lxml work, while reading a condition sheet rasterises pages and may call a model, so holding the
request open across it would block a worker on a lender's page count.

⚠️ 202, NOT 201, AND THE ROUND COMES BACK IMMEDIATELY. The processor sees the round in `PARSING`
(screen S1-02, "Reading…") and the UI polls it to `DRAFT` or `PARSE_FAILED`. Answering only when the
parse finished would make a slow lender's PDF look like a broken upload.

`company_id` is always the authenticated user's, never the body — and the loan file is loaded
scoped, so a round can only ever be opened on a file the caller's company owns.
"""

from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from kombu.exceptions import OperationalError
from sqlalchemy import select

from app.api.dependencies import CurrentUser
from app.core.config import settings
from app.core.database import DbSession
from app.models.condition_round import (
    ConditionRound,
    ConditionRoundCompleteness,
    ConditionRoundStatus,
    ConditionSourceKind,
)
from app.models.helpers import only_active
from app.schemas.condition import (
    ConditionEnrichResult,
    ConditionPasteRequest,
    ConditionRoundPublic,
)
from app.services.condition_enrich import RoundNotEnrichable, enrich_round_with_pdf
from app.services.condition_rounds import (
    ConditionSheetRejected,
    SheetBytes,
    create_round_from_paste,
    create_round_from_sheet,
)
from app.services.loan_files import get_loan_file

router = APIRouter(prefix="/loan-files", tags=["conditions"])
#: ⚠️ A SECOND ROUTER, BECAUSE THE PATH CARRIES NO LOAN FILE. Spec §LP-907 writes
#: `POST /api/condition-rounds/{round_id}/attach-pdf`, and a round id is globally unique — so
#: `ScopedLoanFile`, the tenant gate every nested route uses, has nothing to gate on here. The
#: scoping moves into the lookup instead (`get_scoped_round`), which is the same shape
#: `documents.py` uses for its flat router.
rounds_router = APIRouter(prefix="/condition-rounds", tags=["conditions"])

log = structlog.get_logger(__name__)

#: Read the upload a megabyte at a time, the same as the MISMO path.
_CHUNK = 1024 * 1024

#: What a processor is told when the broker would not take the round. Composed, never quoted from
#: the paste: `failure_detail` is stored inside `parse_report`, which the readonly layer DROPS
#: WHOLE rather than scrubs, so NPI quoted here would sit at rest in a column nobody can inspect to
#: find it (spec §9.5).
_ENQUEUE_FAILED_DETAIL = (
    "These conditions could not be queued for reading. Nothing was lost — try again in a moment."
)


async def _enqueue_split_or_fail(db: DbSession, round_: ConditionRound) -> None:
    """Queue the AI split, and mark the round failed if the broker will not take it.

    ⚠️ REPORTING THE OUTCOME RATHER THAN SWALLOWING IT, and this repo already learned which of those
    is right here. `documents.py` carries both shapes: `_enqueue_reprocess` logs and moves on,
    because the document is fine either way; `_enqueue_full_reprocess` REPORTS, because its callers
    set a blocking state first and, in the LP-637 review's words, "a swallowed failure made that
    permanent: a FAILED document became a PENDING one with a type and no error, which reads as
    healthy, is invisible in the UI".

    A round stuck in `PARSING` is that same shape — healthy-looking and invisible. The row is
    committed BEFORE `.delay()` is reached (correctly: a worker that picked it up first would find
    no row), so a broker that is down leaves a round nothing will ever move and a processor watching
    screen S1-02 indefinitely. That is LP-905's recorded stranded-round gap, and reverting the paste
    door to `PARSING` put it on the one door a person actually waits at.

    A typed `PARSE_FAILED` is something they can act on. A spinner with no end is not.
    """
    try:
        from app.tasks.conditions import split_condition_round

        split_condition_round.delay(str(round_.id))
    except OperationalError:
        # ⚠️ SPECIFIC, NEVER A BARE `except Exception` (spec §9.8). This is the broker refusing the
        # message — the one failure the round must survive. Anything else is a bug and belongs in
        # the error handler, not filed as a parse failure that blames the lender's sheet.
        round_.status = ConditionRoundStatus.PARSE_FAILED
        # A NEW dict: SQLAlchemy does not track in-place mutation of JSONB, so an updated key on the
        # existing one would simply not be written.
        round_.parse_report = {
            **(round_.parse_report or {}),
            "failure_kind": "enqueue_failed",
            "failure_detail": _ENQUEUE_FAILED_DETAIL,
        }
        await db.commit()
        await db.refresh(round_)
        # Ids and counts only (spec §9.5) — never the pasted text.
        log.warning("condition_split_enqueue_failed", round_id=str(round_.id))


async def get_scoped_round(
    round_id: UUID, db: DbSession, current_user: CurrentUser
) -> ConditionRound:
    """The round in the path, scoped to the caller's company.

    ⚠️ THE SCOPE IS IN THE QUERY, NOT IN A CHECK AFTER IT. Fetching by id and then comparing
    `company_id` gives the same answer but a different failure: for the window between the two the
    row is in hand, and any code added later that touches it before the check leaks another tenant's
    data. Filtering in the statement makes a mismatched (company, round) pair unfetchable rather than
    merely rejected — the same reasoning `get_loan_file` uses, and the reason the forward door's
    404 is indistinguishable from a missing id.
    """
    round_ = await db.scalar(
        only_active(
            select(ConditionRound).where(
                ConditionRound.id == round_id,
                ConditionRound.company_id == current_user.company_id,
            ),
            ConditionRound,
        )
    )
    if round_ is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Round not found.")
    return round_


ScopedRound = Annotated[ConditionRound, Depends(get_scoped_round)]


async def _read_capped(upload: UploadFile, *, max_bytes: int) -> bytes:
    """Read an upload into memory, aborting (413) once it exceeds ``max_bytes``.

    ⚠️ CHUNKED, NOT `await upload.read()` THEN `len()`. Reading the whole body and measuring it
    afterwards means a 2 GB upload is already in memory by the time it is refused, which makes the
    cap a formality rather than a defence.
    """
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(_CHUNK):
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(f"The condition sheet exceeds the {max_bytes // (1024 * 1024)} MB limit."),
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post(
    "/{loan_file_id}/condition-rounds/uploads",
    response_model=ConditionRoundPublic,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_condition_sheet(
    loan_file_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
    file: Annotated[UploadFile, File(description="The lender's condition sheet, as a PDF")],
    completeness: Annotated[ConditionRoundCompleteness, Form()] = (ConditionRoundCompleteness.FULL),
) -> ConditionRoundPublic:
    """Upload a lender's condition sheet → a `PARSING` round, read in the background.

    `completeness` defaults to FULL: a processor uploading the lender's letter is giving us the whole
    list unless they say otherwise. It is load-bearing rather than descriptive — ADR-404 lets only a
    FULL round's absences mean anything, and a PARTIAL one may add and update but never remove.
    """
    # `identifier` is a str accepting a UUID *or* a display_id — the repo's one scoped read for a
    # loan file. It returns None when the file belongs to another company, so tenancy is enforced
    # by the lookup rather than by a check after it.
    loan_file = await get_loan_file(
        db, company_id=current_user.company_id, identifier=str(loan_file_id)
    )
    if loan_file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan file not found.")

    content = await _read_capped(file, max_bytes=settings.condition_sheet_max_bytes)
    if not content:
        raise HTTPException(status_code=422, detail="No file provided.")

    try:
        round_ = await create_round_from_sheet(
            db,
            loan_file=loan_file,
            sheet=SheetBytes(
                content=content,
                source_kind=ConditionSourceKind.PDF_UPLOAD,
                # What the BROWSER declared in the multipart part header. Passed through rather
                # than assumed, so a mismatch message quotes what the sender actually claimed.
                declared_content_type=file.content_type,
            ),
            completeness=completeness,
            actor_user_id=current_user.id,
        )
    except ConditionSheetRejected as exc:
        # ⚠️ THE SERVICE'S OWN REASON, NOT A GENERIC ONE. "That is not a PDF" and "the PDF is
        # password-protected" lead to different next actions for the processor (spec §9.8).
        raise HTTPException(status_code=422, detail=exc.reason) from exc

    await db.commit()
    await db.refresh(round_)

    # Enqueued AFTER the commit, deliberately: a worker that picked the round up before the
    # transaction landed would find no row. The same ordering every enqueue in this repo uses.
    # ⚠️ UNGUARDED, AND THAT IS A DECISION RATHER THAN AN OVERSIGHT — see `_enqueue_split_or_fail`
    # above, which DOES guard the same call. This door has the identical exposure: the round is
    # committed in `PARSING` before `.delay()` is reached, so a broker that is down strands it.
    # It is left alone because this is LP-905's surface with its own test coverage, and changing a
    # shipped door inside an AI-split ticket is how a ticket becomes a refactor. The mitigation is
    # available and belongs with the reaper (LP-908 review).
    from app.tasks.conditions import parse_condition_round

    parse_condition_round.delay(str(round_.id))

    return ConditionRoundPublic.from_model(round_)


@router.post(
    "/{loan_file_id}/condition-rounds/paste",
    response_model=ConditionRoundPublic,
    status_code=status.HTTP_201_CREATED,
)
async def paste_conditions(
    loan_file_id: UUID,
    payload: ConditionPasteRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> ConditionRoundPublic:
    """Paste conditions copied from the lender's portal → a round holding what the rules read.

    ⚠️ 201 AND A FINISHED ROUND, WHERE THE UPLOAD ANSWERS 202 AND A `PARSING` ONE. The two doors
    differ because the work does: an upload has bytes to fetch and pages to rasterise, while a paste
    is text already in memory. The processor goes straight to the review screen instead of watching
    a progress state for work that finished inside the request.

    ⚠️ `completeness` IS REQUIRED AND THE API REFUSES TO GUESS IT. The UI defaults the control to
    "just some" — the answer that can never remove anything — but a default HERE would decide the
    file's history on the processor's behalf, and ADR-404 lets only a FULL round's absences mean
    anything later.

    The 100,000-character ceiling is enforced by the request schema, so an oversized paste is refused
    before it reaches a reader rather than after.
    """
    loan_file = await get_loan_file(
        db, company_id=current_user.company_id, identifier=str(loan_file_id)
    )
    if loan_file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan file not found.")

    round_ = await create_round_from_paste(
        db,
        loan_file=loan_file,
        text=payload.text,
        completeness=payload.completeness,
        round_date=payload.round_date,
        actor_user_id=current_user.id,
    )

    await db.commit()
    await db.refresh(round_)

    # ⚠️ ENQUEUED ONLY WHEN THE RULES GAVE UP, and after the commit for the reason every enqueue in
    # this repo uses: a worker that picked the round up before the transaction landed would find no
    # row. A round the rules read is already DRAFT and has nothing to queue.
    if round_.status is ConditionRoundStatus.PARSING:
        await _enqueue_split_or_fail(db, round_)

    return ConditionRoundPublic.from_model(round_)


@rounds_router.post(
    "/{round_id}/attach-pdf",
    response_model=ConditionEnrichResult,
    status_code=status.HTTP_200_OK,
)
async def attach_pdf(
    round_: ScopedRound,
    db: DbSession,
    current_user: CurrentUser,
    file: Annotated[UploadFile, File(description="The lender's condition sheet, as a PDF")],
) -> ConditionEnrichResult:
    """Attach the lender's PDF to a round that was pasted → merge into THE SAME round (S1-09).

    ⚠️ 200, NOT 201 OR 202, AND THAT IS THE CONTRACT THIS TICKET EXISTS TO STATE. Nothing is created:
    no second round, and — when the PDF carries the conditions the paste already had — no new
    conditions either. A 201 would say something was created and invite a client to expect a new id.

    The merge runs IN THE REQUEST rather than on a worker, unlike the upload door. The reason is the
    same one the paste endpoint gives from the other side: the upload door answers before the parse
    so the UI can poll a `PARSING` round, but an enrich has a round on screen already, and moving it
    back to `PARSING` to reuse that machinery is exactly what the service refuses to do — it would
    make a re-parse something a file upload does silently. The processor gets the merged result, or
    a refusal naming the reason.
    """
    content = await _read_capped(file, max_bytes=settings.condition_sheet_max_bytes)
    if not content:
        raise HTTPException(status_code=422, detail="No file provided.")

    try:
        result = await enrich_round_with_pdf(
            db,
            round_=round_,
            content=content,
            declared_content_type=file.content_type,
            actor_user_id=current_user.id,
        )
    except RoundNotEnrichable as exc:
        # 409: the round exists and the caller may see it — it is the round's STATE that refuses.
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc
    except ConditionSheetRejected as exc:
        raise HTTPException(status_code=422, detail=exc.reason) from exc

    await db.commit()
    await db.refresh(round_)

    return ConditionEnrichResult(
        round_id=round_.id,
        round_number=round_.round_number,
        status=round_.status,
        sheet_format=round_.sheet_format,
        filled_header=result.filled_header,
        filled_expiry=result.filled_expiry,
        filled_date_printed=result.filled_date_printed,
        matched=result.matched,
        added=result.added,
        # ⚠️ A COUNT, NOT THE TEXTS. Those are the lender's words (ADR-405) and the rows themselves
        # come back on the round; a response does not need to restate them to report a number.
        unmatched_existing=len(result.unmatched_existing),
        warnings=result.warnings,
    )
