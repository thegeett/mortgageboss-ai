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

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.api.dependencies import CurrentUser
from app.core.config import settings
from app.core.database import DbSession
from app.models.condition_round import ConditionRoundCompleteness, ConditionSourceKind
from app.schemas.condition import ConditionPasteRequest, ConditionRoundPublic
from app.services.condition_rounds import (
    ConditionSheetRejected,
    SheetBytes,
    create_round_from_paste,
    create_round_from_sheet,
)
from app.services.loan_files import get_loan_file

router = APIRouter(prefix="/loan-files", tags=["conditions"])

#: Read the upload a megabyte at a time, the same as the MISMO path.
_CHUNK = 1024 * 1024


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
    return ConditionRoundPublic.from_model(round_)
