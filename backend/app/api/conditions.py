"""Condition rounds — the arriving sheet (LP-905, spec §6).

A thin boundary, as every router in this repo is: validate the edges, hand the work to
`app/services/condition_rounds.py`, enqueue the read, answer. The PDF is parsed by a Celery task
rather than in the request, which is the opposite of the MISMO import — MISMO is fast deterministic
lxml work, while reading a condition sheet rasterises pages and may call a model, so holding the
request open across it would block a worker on a lender's page count.

202, NOT 201, AND THE ROUND COMES BACK IMMEDIATELY. The processor sees the round in `PARSING`
(screen S1-02, "Reading…") and the UI polls it to `DRAFT` or `PARSE_FAILED`. Answering only when the
parse finished would make a slow lender's PDF look like a broken upload.

`company_id` is always the authenticated user's, never the body — and the loan file is loaded
scoped, so a round can only ever be opened on a file the caller's company owns.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

import structlog
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from kombu.exceptions import OperationalError
from sqlalchemy import select

from app.api.dependencies import CurrentUser
from app.core.config import settings
from app.core.database import DbSession
from app.models.condition import (
    BucketKind,
    Condition,
    ConditionLenderStatus,
    ConditionOrigin,
    ConditionPrepStatus,
    OwnerHint,
)
from app.models.condition_draft import ConditionDraft
from app.models.condition_item import ConditionItem
from app.models.condition_package import ConditionPackage
from app.models.condition_round import (
    ConditionRound,
    ConditionRoundCompleteness,
    ConditionRoundStatus,
    ConditionSourceKind,
)
from app.models.condition_vocabulary import PlanOption
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.schemas.condition import (
    BulkRefusalPublic,
    BulkRequest,
    BulkResultPublic,
    ConditionCreateRequest,
    ConditionDetailPublic,
    ConditionDraftPublic,
    ConditionDraftSummaryPublic,
    ConditionDraftUpdate,
    ConditionEnrichResult,
    ConditionEventPublic,
    ConditionEvidencePublic,
    ConditionImportResult,
    ConditionItemCreate,
    ConditionItemPublic,
    ConditionItemUpdate,
    ConditionPasteRequest,
    ConditionPublic,
    ConditionRoundAppearancePublic,
    ConditionRoundPublic,
    ConditionSort,
    ConditionSummaryPublic,
    ConfirmClearedRequest,
    DraftAddressRequest,
    DraftDueDateRequest,
    DraftFactWarningPublic,
    DraftPolishPublic,
    DraftTailPublic,
    DraftUsePolishRequest,
    EvidenceAcceptRequest,
    FiguresApplyRequest,
    FiguresCheckPublic,
    FindingAnswerRequest,
    LenderProcessingRequest,
    NextStepRequest,
    OwnerRequest,
    PackagePublic,
    PackageRowUpdate,
    PrepStatusRequest,
    ReadingConfirmRequest,
    ReopenRequest,
    RewordedDecisionRequest,
    RoundCompletenessUpdate,
    RoundPlanPublic,
    UnderwriterNotePublic,
    VerdictRequest,
    WithdrawnConditionPublic,
    WithdrawRequest,
)
from app.services import condition_drafts, condition_evidence
from app.services.condition_compare import (
    RoundComparisonRefused,
    confirm_probably_cleared,
    confirm_reworded,
    switch_completeness,
)
from app.services.condition_drafts import (
    DraftRefused,
    draft_view,
    drafts_for_file,
    question_tails_for_file,
    waiting_on_when_sent,
)
from app.services.condition_enrich import RoundNotEnrichable, enrich_round_with_pdf
from app.services.condition_evidence import EvidenceRefused, evidence_public_for_file
from app.services.condition_import import (
    RoundNotImportable,
    create_manual_condition,
    import_round,
)
from app.services.condition_plan import (
    PlanRefused,
    add_item,
    confirm_round_plan,
    items_public_for_file,
    remove_item,
    round_plan_summary,
    set_lender_processing,
    set_next_step,
    update_item,
)
from app.services.condition_reading import (
    ConfirmedItem,
    ReadingRefused,
    confirm_reading,
    use_library_default,
)
from app.services.condition_rounds import (
    ENQUEUE_FAILED_DETAIL,
    ConditionSheetRejected,
    RoundNotDiscardable,
    RoundNotEditable,
    RoundNotReparsable,
    SheetBytes,
    create_round_from_paste,
    create_round_from_sheet,
    discard_round,
    reparse_round,
    update_draft,
)
from app.services.condition_status import (
    ConditionRefused,
    apply_bulk,
    move_prep_status,
    record_verdict,
    reopen,
    set_owner,
)
from app.services.conditions import (
    MAX_CONDITIONS,
    ConditionFilters,
    appearances_for_file,
    condition_days_open,
    condition_summary,
    effective_owner,
    effective_owner_source,
    events_for_condition,
    events_for_round,
    import_counts,
    import_counts_for_file,
    imported_rounds_oldest_first,
    is_open,
    latest_imported_round,
    list_conditions_filtered,
    list_rounds,
    rows_on_sheet,
)
from app.services.loan_files import get_loan_file
from app.services.needs_engine import loan_file_needs_lock

# THE SHARED RESOLVER, NOT A SECOND ONE. `overlay_admin.py` already imports this for the same
# question — "what is this actor's display name" — and its own docstring gives the reason two
# lookups are not allowed to exist: "two lookups would eventually give one actor two names."
from app.services.override_attribution import resolve_user_names

router = APIRouter(prefix="/loan-files", tags=["conditions"])
#: A SECOND ROUTER, BECAUSE THE PATH CARRIES NO LOAN FILE. Spec §LP-907 writes
#: `POST /api/condition-rounds/{round_id}/attach-pdf`, and a round id is globally unique — so
#: `ScopedLoanFile`, the tenant gate every nested route uses, has nothing to gate on here. The
#: scoping moves into the lookup instead (`get_scoped_round`), which is the same shape
#: `documents.py` uses for its flat router.
rounds_router = APIRouter(prefix="/condition-rounds", tags=["conditions"])
#: A THIRD ROUTER, FOR THE SAME REASON THERE IS A SECOND. Spec §LP-911 puts the single condition at
#: `/api/conditions/{condition_id}`, which carries neither a loan file nor a round — so
#: `ScopedLoanFileById` has no file to scope and `ScopedRound` scopes the wrong row. The gate moves
#: into the lookup again (`get_scoped_condition`), and `tests/api/test_condition_route_gating.py`
#: gains this router in the SAME commit: its `_gate_map()` names routers by hand, so a new one is
#: invisible to the walk until it is listed, and "the fourth route someone adds in Stage 2 is the one
#: that ships open" is that file's own warning about exactly this moment.
conditions_by_id_router = APIRouter(prefix="/conditions", tags=["conditions"])

log = structlog.get_logger(__name__)

#: Read the upload a megabyte at a time, the same as the MISMO path.
_CHUNK = 1024 * 1024


def _enqueue_reading(round_id: UUID) -> None:
    from app.tasks.conditions import read_condition_round

    try:
        read_condition_round.delay(str(round_id))
    except Exception as exc:
        log.warning(
            "condition_read_not_queued", round_id=str(round_id), error_type=type(exc).__name__
        )


async def _enqueue_or_fail(
    db: DbSession,
    round_: ConditionRound,
    *,
    enqueue: Callable[[str], object],
    event: str,
) -> None:
    """Hand a round to a worker, and settle it FAILED if the broker will not take it.

    ONE BODY FOR BOTH DOORS, AND THE ARGUMENT FOR KEEPING THEM SEPARATE WAS ABOUT A DIFFERENT
    FUNCTION (LP-909 review). I defended the duplication by saying the two "genuinely differ — one
    mutates the ORM object and commits, the other settles through a compare-and-set". That describes
    `_queue_split_or_fail` in `app/tasks/conditions.py`, which is a THIRD handler and does differ.
    The two in THIS module were line-for-line identical apart from which task they import and the
    log event name, so the reasoning was about the wrong pair.

    Three broker handlers, two of them duplicates, is exactly how the third one goes wrong — and the
    third is the one whose difference is real and load-bearing (a task has no ORM object in hand and
    must not clobber a round a processor discarded meanwhile).

    `enqueue` IS THE BOUND `.delay`, RESOLVED BY THE CALLER. Passing the method rather than the
    task keeps the test seam where every condition test already puts it: `monkeypatch.setattr(
    task_module.<task>, "delay", ...)` still works, because the attribute is looked up when the
    caller runs, not when this module is imported.
    """
    try:
        enqueue(str(round_.id))
    except OperationalError:
        # kombu's, NOT `sqlalchemy.exc`'s — two unrelated classes share the name and `.delay()`
        # raises kombu's, so catching the other is a guard that never fires (LP-908 review).
        # Specific, never a bare `except Exception` (spec §9.8): this is the broker refusing the
        # message, the one failure the round must survive. Anything else is a bug and belongs in the
        # error handler, not filed as a parse failure that blames the lender's sheet.
        round_.status = ConditionRoundStatus.PARSE_FAILED
        # A NEW dict: SQLAlchemy does not track in-place mutation of JSONB, so an updated key on the
        # existing one would simply not be written.
        round_.parse_report = {
            **(round_.parse_report or {}),
            "failure_kind": "enqueue_failed",
            "failure_detail": ENQUEUE_FAILED_DETAIL,
        }
        await db.commit()
        await db.refresh(round_)
        # Ids and counts only (spec §9.5) — never the sheet's text.
        log.warning(event, round_id=str(round_.id))


async def _enqueue_split_or_fail(db: DbSession, round_: ConditionRound) -> None:
    """Queue the AI split, and mark the round failed if the broker will not take it.

    REPORTING THE OUTCOME RATHER THAN SWALLOWING IT, and this repo already learned which of those
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
    from app.tasks.conditions import split_condition_round

    await _enqueue_or_fail(
        db, round_, enqueue=split_condition_round.delay, event="condition_split_enqueue_failed"
    )


async def _enqueue_parse_or_fail(db: DbSession, round_: ConditionRound) -> None:
    """Queue the read, and mark the round failed if the broker will not take it.

    THE SPLIT'S TWIN, AND THE UPLOAD DOOR DELIBERATELY HAS NO SUCH GUARD. That door's bare
    `.delay()` carries a comment calling the exposure a decision rather than an oversight, on the
    grounds that changing a shipped door inside another ticket is how a ticket becomes a refactor.

    Reparse does not get to inherit that. The round is committed `PARSING` BEFORE this is reached,
    so a broker that is down leaves exactly the permanent-`PARSING` round this stage has now fixed
    twice — and a processor who pressed "Try again" watching it strand a second time is the worst
    version of it, because they asked for the recovery and the recovery is what failed.

    AND A FAILED REPARSE MUST NOT LOOK LIKE A FAILED SHEET. `failure_kind` is `enqueue_failed`,
    whose sentence says the conditions could not be QUEUED and nothing was lost — never a reason
    that blames the lender's PDF, which was read fine or was never read at all.
    """
    from app.tasks.conditions import parse_condition_round

    await _enqueue_or_fail(
        db, round_, enqueue=parse_condition_round.delay, event="condition_reparse_enqueue_failed"
    )


async def get_scoped_round(
    round_id: UUID, db: DbSession, current_user: CurrentUser
) -> ConditionRound:
    """The round in the path, scoped to the caller's company.

    THE SCOPE IS IN THE QUERY, NOT IN A CHECK AFTER IT. Fetching by id and then comparing
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


async def get_scoped_condition(
    condition_id: UUID, db: DbSession, current_user: CurrentUser
) -> Condition:
    """The condition in the path, scoped to the caller's company.

    THE SCOPE IS IN THE QUERY, the same as `get_scoped_round` above — and deliberately written that
    way rather than through `scope_to_company`, which is this repo's greppable helper for the same
    filter. Two idioms one function apart would be worse than one unfashionable one: the two gates in
    this module should read identically, because the thing a reader must be able to check at a glance
    is that BOTH of them filter inside the statement rather than after it.

    `Condition.company_id` is on the row for exactly this (`models/condition.py`: "a condition is
    reached directly by id, so the scoping filter needs a column here"), and soft-deleted rows are
    excluded — a deleted condition is not found rather than found and refused.

    404, NEVER 403. Confirming that an id exists would be an oracle over another tenant's rows, which
    is why this is indistinguishable from a missing id.
    """
    condition = await db.scalar(
        only_active(
            select(Condition).where(
                Condition.id == condition_id,
                Condition.company_id == current_user.company_id,
            ),
            Condition,
        )
    )
    if condition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Condition not found.")
    return condition


ScopedCondition = Annotated[Condition, Depends(get_scoped_condition)]


async def get_scoped_loan_file_by_id(
    loan_file_id: str, db: DbSession, current_user: CurrentUser
) -> LoanFile:
    """The loan file in the path, scoped to the caller's company.

    A DEPENDENCY RATHER THAN THE SAME SIX LINES IN EVERY HANDLER, which is what this router had.
    Both POSTs opened by calling `get_loan_file` and raising 404 themselves; §1 adds three reads, and
    five copies of a tenant gate is how one of them eventually ships without it. Every other nested
    router in this repo declares `ScopedLoanFile` for exactly this reason — the file is fetched and
    company-checked *before* the handler body runs, so a handler cannot forget.

    IT IS NOT `ScopedLoanFile` ITSELF BECAUSE THIS ROUTER'S PATH IS DIFFERENT. That dependency
    reads `file_identifier` from a `/loan-files/{file_identifier}/...` prefix; spec §LP-905/907 fix
    these paths as `/loan-files/{loan_file_id}/condition-rounds/...`, LP-905 and LP-907 shipped them,
    and three test files plus the tenancy test hardcode that shape. Renaming the segment to reuse the
    dependency would churn shipped URLs to save a wrapper, so the wrapper is the smaller change.

    THE SEGMENT IS A `str`, A UUID *OR* A `display_id`, THE SAME AS `ScopedLoanFile`. It was typed
    `UUID` on the premise that these ids come from the API's own responses; they do not. The
    conditions tab passes its URL's `[id]` segment, and the dashboard and intake navigate by display
    id (`/loan-files/LF-XXXX`), so every real visit was a 422 raised before this body ran: no log
    line, and "The conditions couldn't be loaded" on staging. The tenant gate is `get_loan_file`'s
    `company_id` filter, not the path type, so accepting either form widens nothing.
    """
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=loan_file_id)
    if loan_file is None:
        # The same 404 as a missing file: distinguishing them would confirm the id exists, an oracle
        # over another tenant's rows.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan file not found.")
    return loan_file


ScopedLoanFileById = Annotated[LoanFile, Depends(get_scoped_loan_file_by_id)]


async def _read_capped(upload: UploadFile, *, max_bytes: int) -> bytes:
    """Read an upload into memory, aborting (413) once it exceeds ``max_bytes``.

    CHUNKED, NOT `await upload.read()` THEN `len()`. Reading the whole body and measuring it
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
    loan_file: ScopedLoanFileById,
    db: DbSession,
    current_user: CurrentUser,
    file: Annotated[UploadFile, File(description="The lender's condition sheet, as a PDF")],
    completeness: Annotated[ConditionRoundCompleteness, Form()] = (ConditionRoundCompleteness.FULL),
) -> ConditionRoundPublic:
    """Upload a lender's condition sheet → a `PARSING` round, read in the background.

    `completeness` defaults to FULL: a processor uploading the lender's letter is giving us the whole
    list unless they say otherwise. It is load-bearing rather than descriptive — ADR-404 lets only a
    FULL round's absences mean anything, and a PARTIAL one may add and update but never remove.

    Tenancy is the dependency's: the file is fetched company-scoped before this body runs, so a
    mismatched (company, file) pair is unfetchable rather than rejected after the fact.
    """
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
        # THE SERVICE'S OWN REASON, NOT A GENERIC ONE. "That is not a PDF" and "the PDF is
        # password-protected" lead to different next actions for the processor (spec §9.8).
        raise HTTPException(status_code=422, detail=exc.reason) from exc

    await db.commit()
    await db.refresh(round_)

    # Enqueued AFTER the commit, deliberately: a worker that picked the round up before the
    # transaction landed would find no row. The same ordering every enqueue in this repo uses.
    # UNGUARDED, AND THAT IS A DECISION RATHER THAN AN OVERSIGHT — see `_enqueue_split_or_fail`
    # above, which DOES guard the same call. This door has the identical exposure: the round is
    # committed in `PARSING` before `.delay()` is reached, so a broker that is down strands it.
    # It is left alone because this is LP-905's surface with its own test coverage, and changing a
    # shipped door inside an AI-split ticket is how a ticket becomes a refactor. The mitigation is
    # available and belongs with the reaper (LP-908 review).
    from app.tasks.conditions import parse_condition_round

    parse_condition_round.delay(str(round_.id))

    return ConditionRoundPublic.from_model(round_)


def _round_public(
    round_: ConditionRound,
    *,
    per_round: dict[UUID, int],
    imports: dict[UUID, tuple[int, int]],
) -> ConditionRoundPublic:
    """One round as the wire sees it, with every derived count filled in.

    ONE PLACE, BECAUSE THESE DEFAULTS DO NOT FAIL LOUDLY. `_round_card` below already records
    what happens otherwise: `condition_count` "defaults to 0 and must be supplied, which is easy to
    forget precisely because forgetting it looks like data rather than like a bug" — and
    `paste_conditions` forgets it to this day, answering "0 on sheet" for a round it just filled.
    Adding `created` and `seen_again` as two more optional aggregates across three separate call
    sites would triple that surface, so the call sites now ASK for a round rather than assemble one.

    The counts still arrive as arguments rather than being fetched here: both are one-query-per-file
    aggregates, and fetching inside this function would turn the round strip into an N+1 — the exact
    thing `appearances_for_file` exists to prevent.
    """
    created, seen_again = import_counts(round_, imports)
    return ConditionRoundPublic.from_model(
        round_,
        condition_count=rows_on_sheet(round_, per_round),
        created=created,
        seen_again=seen_again,
    )


@router.get("/{loan_file_id}/condition-rounds", response_model=list[ConditionRoundPublic])
async def list_condition_rounds(
    loan_file: ScopedLoanFileById, db: DbSession
) -> list[ConditionRoundPublic]:
    """Every round on this file, newest first — the round strip above the conditions list (S1-05).

    `condition_count` GETS ITS FIRST PRODUCER HERE. It has defaulted to 0 since LP-904 with
    nothing filling it, so a round card would have read "0 on sheet" for as long as anyone looked.
    The count comes from a different place depending on status — a draft counts the rows it holds, an
    imported round counts the conditions that appeared on it — which is what `rows_on_sheet` decides.

    ONE events query for the whole strip, never one per card: `appearances_for_file` is the
    `_completed_documents` shape ("loaded once, LP-109, no N+1").
    """
    rounds = await list_rounds(db, loan_file_id=loan_file.id)
    _, per_round = await appearances_for_file(db, loan_file_id=loan_file.id)
    # A SECOND whole-file aggregate, on the same rule as the first: one query for the strip, never
    # one per card. The counts live in each round's `ROUND_IMPORTED` event, not on the row.
    imports = await import_counts_for_file(db, loan_file_id=loan_file.id)
    return [_round_public(round_, per_round=per_round, imports=imports) for round_ in rounds]


@rounds_router.get("/{round_id}/plan", response_model=RoundPlanPublic)
async def get_round_plan(round_: ScopedRound, db: DbSession) -> RoundPlanPublic:
    """S3-02's heading and pills for this round's plan."""
    summary: RoundPlanPublic = await round_plan_summary(db, round_=round_)
    return summary


@rounds_router.post("/{round_id}/plan/confirm", response_model=RoundPlanPublic)
async def confirm_plan(
    round_: ScopedRound, db: DbSession, current_user: CurrentUser
) -> RoundPlanPublic:
    """S3-02's "Confirm plan…". Refused, with the sentence, while any reading still needs her."""
    try:
        await confirm_round_plan(db, round_=round_, actor_user_id=current_user.id)
    except PlanRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc
    await db.commit()
    summary: RoundPlanPublic = await round_plan_summary(db, round_=round_)
    return summary


@router.put("/{loan_file_id}/lender-processing", status_code=status.HTTP_204_NO_CONTENT)
async def set_file_lender_processing(
    loan_file: ScopedLoanFileById,
    payload: LenderProcessingRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> None:
    """ "Lender is processing this file" (§4a change 8): third-party asks not yet sent follow it."""
    await set_lender_processing(
        db, loan_file=loan_file, on=payload.on, actor_user_id=current_user.id
    )
    await db.commit()


@rounds_router.get("/{round_id}", response_model=ConditionRoundPublic)
async def get_condition_round(round_: ScopedRound, db: DbSession) -> ConditionRoundPublic:
    """One round: its draft rows or its imported count, header, expiry dates and parse report.

    THE FIRST GET ON THIS ROUTER, and the schema it returns carries a trap worth naming at the
    call site: `draft_rows` being PRESENT does not mean a processor may act on them. A `PARSING`
    round awaiting the AI split carries the rules-read rows too, and screen S1-02 renders skeletons
    and polls rather than showing them. Read `status`, never the presence of rows.

    Scoped by `get_scoped_round`, which filters `company_id` inside the statement — so another
    tenant's round is unfetchable rather than fetched and then refused.
    """
    _, per_round = await appearances_for_file(db, loan_file_id=round_.loan_file_id)
    imports = await import_counts_for_file(db, loan_file_id=round_.loan_file_id)
    return _round_public(round_, per_round=per_round, imports=imports)


def _condition_public(
    condition: Condition,
    *,
    round_numbers: list[int],
    today: date,
    items: list[ConditionItemPublic] | None = None,
    question_draft: DraftTailPublic | None = None,
    evidence: list[ConditionEvidencePublic] | None = None,
) -> ConditionPublic:
    """One condition as the wire sees it, with the SERVICE's rules supplying the derived fields.

    ONE PLACE, BECAUSE THE SCHEMA DELIBERATELY CANNOT COMPUTE THEM. `ConditionPublic.from_model`
    requires `effective_owner`, `is_open` and the day count rather than deriving them, so that the
    row can never disagree with the filter that selected it — and the only way that guarantee is worth
    anything is if every caller routes through one helper instead of each answering for itself.

    `today` IS THREADED IN RATHER THAN READ PER ROW. A list that called `date.today()` once per
    condition would disagree with itself across midnight, and the last row of a long response would
    count a different number of days from the first.
    """
    return ConditionPublic.from_model(
        condition,
        round_numbers=round_numbers,
        effective_owner=effective_owner(condition),
        effective_owner_source=effective_owner_source(condition),
        is_open=is_open(condition),
        days_open=condition_days_open(condition, today=today),
        items=items,
        question_draft=question_draft,
        evidence=evidence,
        # LP-947: the server's rule for who the next send waits on, not a client copy of it.
        waiting_on_when_sent=waiting_on_when_sent(condition.next_step, items or []),
    )


#: Set when the read hit `MAX_CONDITIONS`, so a client can tell a full page from a truncated one.
#:
#: A HEADER RATHER THAN A FIELD, AND THE SHAPE IS WHY. Spec §LP-911 says to "cap at 500 and say so in
#: the response", and its Done-when also requires that "the Stage 1 imported list still works
#: unchanged, since its default response shape is kept". Wrapping the array in an object to carry a
#: flag would break the second to satisfy the first; a header is part of the response and costs the
#: existing client nothing.
CAPPED_HEADER = "X-Conditions-Capped"


@router.get("/{loan_file_id}/conditions", response_model=list[ConditionPublic])
async def list_file_conditions(
    loan_file: ScopedLoanFileById,
    db: DbSession,
    response: Response,
    round_number: Annotated[
        int | None, Query(alias="round", description="Only conditions on the sheet of this round")
    ] = None,
    lender_status: Annotated[list[ConditionLenderStatus] | None, Query()] = None,
    prep_status: Annotated[list[ConditionPrepStatus] | None, Query()] = None,
    owner: Annotated[
        list[OwnerHint] | None, Query(description="The EFFECTIVE owner, not the raw hint")
    ] = None,
    bucket_kind: Annotated[list[BucketKind] | None, Query()] = None,
    lender_code: Annotated[
        str | None, Query(description="Exact, as printed — 0006 is not 6")
    ] = None,
    category: Annotated[str | None, Query()] = None,
    info_only: Annotated[bool | None, Query()] = None,
    origin: Annotated[ConditionOrigin | None, Query()] = None,
    next_step: Annotated[
        list[PlanOption] | None,
        Query(description="An open step of these options, the condition's own or an item's"),
    ] = None,
    check: Annotated[
        Literal["failed"] | None,
        Query(description="`failed`: a failed, unaccepted evidence check (S3-12)"),
    ] = None,
    q: Annotated[str | None, Query(description="Text search in the wording and the code")] = None,
    sort: Annotated[ConditionSort, Query()] = ConditionSort.SHEET,
) -> list[ConditionPublic]:
    """The file's imported conditions, filtered and sorted, each with the rounds it appeared on.

    THE DEFAULT RESPONSE IS STAGE 1'S, UNCHANGED. Every filter is optional and `sort` defaults to
    sheet order, so a caller that passes nothing gets exactly what LP-909 served — which is a
    Done-when of this ticket, not a courtesy: the Stage 1 imported list is still in the tree and still
    reads this route.

    `round_numbers` GETS ITS FIRST PRODUCER HERE — the `R1 R2` chips, which have defaulted to `[]`
    since LP-904. It is derived from each condition's `CONDITION_CREATED` / `CONDITION_SEEN_AGAIN`
    events rather than from `first_round_id` / `last_seen_round_id`, because two columns cannot
    express "appeared on R1 and R3 but not R2" — which is the whole point of the chips.

    That derivation is only as good as the enumeration of who writes conditions, which is why every
    writer emits `CONDITION_CREATED` (LP-907's enrich did not, and its conditions were chipless until
    that was fixed). The `round` FILTER asks the same question, which is why it is answered from that
    map rather than from a column.

    `q` IS NEVER LOGGED. It searches `verbatim_text` — the lender's words, and NPI (ADR-405) — so the
    log line below carries the filter NAMES and the row count and nothing else. `ConditionFilters`
    holds `names()` for exactly this.
    """
    filters = ConditionFilters(
        round_number=round_number,
        lender_status=tuple(lender_status or ()),
        prep_status=tuple(prep_status or ()),
        owner=tuple(owner or ()),
        bucket_kind=tuple(bucket_kind or ()),
        lender_code=lender_code,
        category=category,
        info_only=info_only,
        origin=origin,
        next_step=tuple(next_step or ()),
        failed_check=check == "failed",
        q=q,
    )
    numbers, _ = await appearances_for_file(db, loan_file_id=loan_file.id)
    conditions, capped = await list_conditions_filtered(
        db,
        loan_file_id=loan_file.id,
        filters=filters,
        sort=sort,
        round_numbers=numbers,
    )
    if capped:
        response.headers[CAPPED_HEADER] = "true"
        # IDS AND COUNTS ONLY (spec §9.5). A cap being hit on a real file would mean something is
        # wrong with the file rather than with the request, so it is worth a line — but never the
        # search term.
        log.warning(
            "conditions_read_capped",
            loan_file_id=str(loan_file.id),
            limit=MAX_CONDITIONS,
        )

    # THE FILTER NAMES AND THE COUNT, NEVER A VALUE (ADR-405). `q` searches `verbatim_text`, so
    # logging what was searched for would put the lender's words in the log to record that somebody
    # looked for them — and a search term is often a borrower's account ending or employer, which is
    # exactly what that ADR exists to keep out of the analytics path. `names()` is on
    # `ConditionFilters` so this line cannot accidentally reach for a value.
    log.info(
        "conditions_listed",
        loan_file_id=str(loan_file.id),
        filters=filters.names(),
        sort=sort.value,
        returned=len(conditions),
    )

    today = datetime.now(UTC).date()
    # LP-920 — every condition's items in ONE query for the whole file, not one per row.
    items = await items_public_for_file(db, loan_file_id=loan_file.id)
    questions = await question_tails_for_file(db, loan_file_id=loan_file.id)
    evidence = await evidence_public_for_file(db, loan_file_id=loan_file.id)
    return [
        _condition_public(
            condition,
            round_numbers=numbers.get(condition.id, []),
            today=today,
            items=items.get(condition.id, []),
            question_draft=questions.get(condition.id),
            evidence=evidence.get(condition.id, []),
        )
        for condition in conditions
    ]


@router.get("/{loan_file_id}/conditions/summary", response_model=ConditionSummaryPublic)
async def get_conditions_summary(
    loan_file: ScopedLoanFileById, db: DbSession
) -> ConditionSummaryPublic:
    """The counts the summary bar and the file rail read (screens S2-01, S2-02).

    PATH ORDER MATTERS AND FASTAPI DOES NOT WARN. `/conditions/summary` is declared AFTER
    `/conditions` and both are GETs on the same router, which is fine because they are different
    paths — but if a `/conditions/{condition_id}` route were ever added to THIS router it would have
    to come after this one, or "summary" would be matched as an id and 422 on the UUID parse. The
    single-condition read deliberately lives on its own router (no loan file in its path), so the
    collision does not arise today; this comment is here so it does not arise tomorrow either.

    COUNTS, NEVER ROWS. This is the one response the file rail fetches on every visit, and putting
    conditions in it would carry the lender's words onto a screen that only ever shows numbers.
    """
    summary = await condition_summary(db, loan_file_id=loan_file.id)
    latest = await latest_imported_round(db, loan_file_id=loan_file.id)
    return ConditionSummaryPublic(
        total=summary.total,
        open=summary.open,
        cleared=summary.cleared,
        waived=summary.waived,
        not_cleared=summary.not_cleared,
        superseded=summary.superseded,
        info_only=summary.info_only,
        by_prep_status=summary.by_prep_status,
        by_owner=summary.by_owner,
        by_bucket_kind=summary.by_bucket_kind,
        open_prior_to_docs=summary.open_prior_to_docs,
        open_prior_to_funding=summary.open_prior_to_funding,
        pending_suggestions=summary.pending_suggestions,
        waiting_on_others=summary.waiting_on_others,
        your_tasks=summary.your_tasks,
        ready_to_send=summary.ready_to_send,
        failed_check=summary.failed_check,
        has_plan=summary.has_plan,
        latest_round=(await _round_card(db, latest) if latest is not None else None),
    )


@router.post(
    "/{loan_file_id}/condition-rounds/paste",
    response_model=ConditionRoundPublic,
    status_code=status.HTTP_201_CREATED,
)
async def paste_conditions(
    loan_file: ScopedLoanFileById,
    payload: ConditionPasteRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> ConditionRoundPublic:
    """Paste conditions copied from the lender's portal → a round holding what the rules read.

    201 AND A FINISHED ROUND, WHERE THE UPLOAD ANSWERS 202 AND A `PARSING` ONE. The two doors
    differ because the work does: an upload has bytes to fetch and pages to rasterise, while a paste
    is text already in memory. The processor goes straight to the review screen instead of watching
    a progress state for work that finished inside the request.

    `completeness` IS REQUIRED AND THE API REFUSES TO GUESS IT. The UI defaults the control to
    "just some" — the answer that can never remove anything — but a default HERE would decide the
    file's history on the processor's behalf, and ADR-404 lets only a FULL round's absences mean
    anything later.

    The 100,000-character ceiling is enforced by the request schema, so an oversized paste is refused
    before it reaches a reader rather than after.
    """
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

    # ENQUEUED ONLY WHEN THE RULES GAVE UP, and after the commit for the reason every enqueue in
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

    200, NOT 201 OR 202, AND THAT IS THE CONTRACT THIS TICKET EXISTS TO STATE. Nothing is created:
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
        # A COUNT, NOT THE TEXTS. Those are the lender's words (ADR-405) and the rows themselves
        # come back on the round; a response does not need to restate them to report a number.
        unmatched_existing=len(result.unmatched_existing),
        warnings=result.warnings,
    )


async def _round_card(db: DbSession, round_: ConditionRound) -> ConditionRoundPublic:
    """One round with its count filled in.

    `condition_count` DEFAULTS TO 0 AND MUST BE SUPPLIED, which is easy to forget precisely
    because forgetting it looks like data rather than like a bug. `paste_conditions` does forget it
    today: it answers `from_model(round_)` for a round it just filled with rows, so the response
    says "0 on sheet". That is LP-907's shipped door and widening this ticket into it would be a
    refactor, but it is the reason this helper exists rather than three more call sites that each
    have to remember.

    `upload_condition_sheet` HAS THE IDENTICAL SHAPE AND IS CORRECT — do not "fix" it by copying
    this. `create_round_from_sheet` opens a `PARSING` round and assigns no `draft_rows` at all, so an
    upload genuinely holds no rows when it answers and its zero is the truth. Paste stores its rows
    synchronously, which is why only paste reports a number it can see is wrong. Routing upload
    through here would add a query whose answer is already known (raised in review, where the two
    call sites looked like one defect).
    """
    _, per_round = await appearances_for_file(db, loan_file_id=round_.loan_file_id)
    # THE IMPORT ENDPOINT ANSWERS THROUGH HERE, WHICH IS WHERE THESE COUNTS FIRST EXIST. The
    # import writes `ROUND_IMPORTED` and returns; without this the one response that could report
    # what the import just did would be the only one that could not.
    imports = await import_counts_for_file(db, loan_file_id=round_.loan_file_id)
    return _round_public(round_, per_round=per_round, imports=imports)


@rounds_router.post(
    "/{round_id}/import",
    response_model=ConditionImportResult,
    status_code=status.HTTP_200_OK,
)
async def import_condition_round(
    round_: ScopedRound, db: DbSession, current_user: CurrentUser
) -> ConditionImportResult:
    """Turn a reviewed draft into the file's conditions (spec §LP-909 steps 1-5).

    200, NOT 201, THOUGH CONDITIONS ARE CREATED. The resource this call addresses is the ROUND,
    and the round already existed — it is settled in place, from DRAFT to IMPORTED. A 201 would
    invite a client to look for a new id in a `Location` header that names nothing new.

    THE LOCK IS TAKEN HERE AND NOT IN THE SERVICE, AND THAT PLACEMENT IS THE WHOLE POINT. An
    `async with loan_file_needs_lock(...)` inside `import_round` would release when the service
    returned — before this handler commits — leaving the commit outside the window the lock exists
    to cover. It is the repo's first handler-level use of it; every other call site is a task or a
    service that owns its own transaction.

    AND IT IS ADVISORY, NOT MUTUAL EXCLUSION. It yields `bool(acquired)` and every caller in this
    repo proceeds either way, and its 30-second timeout auto-expires a HELD lock, so a slow import
    can lose it mid-transaction. What actually prevents two rounds sharing a number is
    `uq_condition_rounds_file_number`; the service catches that violation and recomputes. The lock
    narrows the window, it does not close it, and nothing here may assume otherwise.
    """
    async with loan_file_needs_lock(round_.loan_file_id):
        try:
            outcome = await import_round(db, round_=round_, actor_user_id=current_user.id)
        except RoundNotImportable as exc:
            # 409, like the enrich door: the round exists and the caller may see it — it is the
            # round's STATE that refuses, and the reason says which state it is in.
            raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc
        await db.commit()

    # LP-919 — read the new conditions into items, after the commit so the worker sees them. A broker
    # that will not take it leaves them `unread`; the import itself has already succeeded and stays so.
    _enqueue_reading(round_.id)

    return ConditionImportResult(
        round_id=round_.id,
        round_number=outcome.round_number,
        created=outcome.created,
        seen_again=outcome.seen_again,
        # Codes, never wording. The code map is explicitly not NPI (LP-904); the conditions are.
        unmapped_codes=outcome.unmapped_codes,
    )


@rounds_router.post(
    "/{round_id}/discard",
    response_model=ConditionRoundPublic,
    status_code=status.HTTP_200_OK,
)
async def discard_condition_round(
    round_: ScopedRound, db: DbSession, current_user: CurrentUser
) -> ConditionRoundPublic:
    """Throw a draft away. It stays on the round strip, marked discarded.

    AN IMPORTED ROUND IS REFUSED, and the service's docstring carries the argument: its conditions
    survive by ADR-404 and it keeps its number by LP-904's index, so "discarded" would mean one thing
    for a draft and a different thing for an imported round, shown in the same strip under one word.

    No lock: nothing here assigns a number or touches a cross-row invariant. The round is scoped by
    `get_scoped_round`, which filters `company_id` inside the statement.
    """
    try:
        await discard_round(db, round_=round_, actor_user_id=current_user.id)
    except RoundNotDiscardable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc

    await db.commit()
    await db.refresh(round_)
    return await _round_card(db, round_)


@rounds_router.get("/{round_id}/events", response_model=list[ConditionEventPublic])
async def list_round_events(round_: ScopedRound, db: DbSession) -> list[ConditionEventPublic]:
    """One round's history, oldest first — the History section of the round-details sheet (S1-09).

    THE READER LP-904 BUILT AN INDEX FOR AND NOBODY WROTE. `ix_condition_events_round_occurred`
    has carried the comment "One round's history in time order — the shape the round-details sheet
    reads (S1-09)" since the table was created, and no route, schema or service ever read it. So the
    index paid a write on every event insert — per created condition, per seen-again, per note, per
    round transition — to serve a query that did not exist. This is that query.

    ITS SIBLING IS STILL UNJUSTIFIED, AND SAYING SO IS THE POINT.
    `ix_condition_events_condition_occurred` is `(condition_id, occurred_at)` — one CONDITION's
    history — which nothing in this codebase asks for. It does not inherit this route's justification.
    Either something reads it, or it should go in a follow-up migration; it is named here so the next
    person does not read this route as covering both.

    `detail` DOES NOT TRAVEL. `ConditionEventPublic` projects named scalars only — the column is
    classified NPI ("what changed, which is the lender's text"), `readonly.condition_events` drops it
    whole rather than scrubbing it, and `condition_import.py` states the rule at its own write site.
    A history panel is not a reason to open a door the readonly layer deliberately closed.

    Scoped by `get_scoped_round`, which filters `company_id` inside the statement — so another
    tenant's round is unfetchable rather than fetched and then refused.
    """
    events = await events_for_round(db, round_id=round_.id)
    return [ConditionEventPublic.from_model(event) for event in events]


@rounds_router.post(
    "/{round_id}/reparse",
    response_model=ConditionRoundPublic,
    status_code=status.HTTP_200_OK,
)
async def reparse_condition_round(
    round_: ScopedRound, db: DbSession, current_user: CurrentUser
) -> ConditionRoundPublic:
    """Read a stored sheet again — screen S1-03's "Try again" and S1-02's stranded state.

    200, NOT 202, THOUGH A TASK IS QUEUED. The round already existed and is settled in place back
    to `PARSING`; nothing is created. A 202 would invite a client to look for a new id. The same
    argument `import` and `discard` make on this router.

    NO REQUEST BODY AT ALL, which is why there is no defaulted-singleton parameter here.
    `documents.py` needs `body: DocumentReprocessRequest = _DEFAULT_REPROCESS_REQUEST` because
    FastAPI makes a Pydantic body REQUIRED even when every field on it has a default, so a body-less
    POST would 422. A reparse takes no options, so declaring an empty model to then default it would
    be machinery standing in for nothing.

    THE ENQUEUE IS AFTER THE COMMIT AND IS GUARDED. Before it, a worker could pick the round up
    and find the old row; unguarded, a broker that is down strands the round the processor just
    asked to rescue.

    WHAT IT REFUSES, and each with its own sentence (spec §9.8): an imported round, a discarded one,
    a draft that was read fine, a round whose only source is a paste and so has no PDF to re-read,
    and a `PARSING` round that has not yet been waiting long enough to count as abandoned. That last
    one is also what makes a double-press safe — the second is refused rather than queueing a second
    reader.
    """
    try:
        await reparse_round(db, round_=round_, actor_user_id=current_user.id)
    except RoundNotReparsable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc

    await db.commit()
    await db.refresh(round_)
    await _enqueue_parse_or_fail(db, round_)
    return await _round_card(db, round_)


@rounds_router.put(
    "/{round_id}/draft",
    response_model=ConditionRoundPublic,
    status_code=status.HTTP_200_OK,
)
async def update_condition_draft(
    round_: ScopedRound, payload: ConditionDraftUpdate, db: DbSession
) -> ConditionRoundPublic:
    """Replace a draft's rows, completeness and date before import (screen S1-04).

    THE EDITED TEXT IS WHAT IMPORTS. Spec §8's frontend test is "editing a row and importing sends
    the edited text", so what a processor writes here is stored verbatim and is what the fingerprint
    is taken of — which means an edited row may match a different condition, or none. That is correct
    rather than unfortunate: the fingerprint is of what is imported, not of what was read.

    409 ON A STALE `expected_updated_at`, RATHER THAN A SILENT LAST-WRITE-WINS. Two tabs on one
    draft is the case the spec names, but the same check also refuses a tab whose rows were changed
    by an enrich or a re-parse — both are the same hazard, overwriting work the caller never saw.

    No `current_user` parameter: nothing here is attributed to a person in an event, because a draft
    is not yet the file's record. The tenant gate is `get_scoped_round`, exactly as on the other
    round routes, and the gating test walks this router by dependency identity.
    """
    try:
        await update_draft(db, round_=round_, payload=payload)
    except RoundNotEditable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc

    await db.commit()
    await db.refresh(round_)
    return await _round_card(db, round_)


@rounds_router.post(
    "/{round_id}/confirm-cleared",
    response_model=ConditionRoundPublic,
    status_code=status.HTTP_200_OK,
)
async def confirm_round_suggestions(
    round_: ScopedRound,
    payload: ConfirmClearedRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> ConditionRoundPublic:
    """Record the ticked suggestions as cleared (screens S2-06 and S2-07).

    THE PATH IS MINE: §LP-915 describes the button and the verdict it writes but names no endpoint.
    `confirm-cleared` sits on the round because the suggestion belongs to the round — it is that
    sheet's evidence — and because the panel already holds the round id it is looking at.

    TWO REFUSAL SHAPES, BECAUSE TWO DIFFERENT THINGS CAN SAY NO. `RoundComparisonRefused` is the
    round's state (nothing pending among those ids) and carries a sentence; `ConditionRefused` comes
    from `record_verdict` deeper down and carries a sentence AND a typed code — an information-only
    line, or a condition that was replaced since the panel was drawn. Both are 409, and `_refused`
    keeps the second one's code intact rather than flattening it to prose.

    IT ANSWERS WITH THE ROUND, so the panel can redraw itself: after a confirm the round has no
    pending suggestions at all, and that emptiness is the state the client has to see.
    """
    try:
        await confirm_probably_cleared(
            db,
            round_=round_,
            condition_ids=payload.condition_ids,
            actor_user_id=current_user.id,
            resolve_rest=payload.resolve_rest,
        )
    except RoundComparisonRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc
    except ConditionRefused as exc:
        raise _refused(exc) from exc

    await db.commit()
    await db.refresh(round_)
    return await _round_card(db, round_)


@rounds_router.post(
    "/{round_id}/reworded",
    response_model=ConditionRoundPublic,
    status_code=status.HTTP_200_OK,
)
async def resolve_reworded_pair(
    round_: ScopedRound,
    payload: RewordedDecisionRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> ConditionRoundPublic:
    """Answer S2-08's *Same condition* / *Different conditions*.

    ONE ENDPOINT WITH A BOOLEAN, NOT TWO PATHS. The two buttons answer one question about one pair,
    and the interesting half of the request is WHICH pair — so `same` is a field rather than a verb in
    the URL. "Nothing happens until you choose" is the screen's own line, and this is the choosing.

    THE PATH IS MINE, as with `confirm-cleared`: the spec names the buttons and their effects, not a
    route.
    """
    try:
        await confirm_reworded(
            db,
            round_=round_,
            old_id=payload.old_id,
            new_id=payload.new_id,
            same=payload.same,
            actor_user_id=current_user.id,
        )
    except RoundComparisonRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc

    await db.commit()
    await db.refresh(round_)
    return await _round_card(db, round_)


@rounds_router.put(
    "/{round_id}/completeness",
    response_model=ConditionRoundPublic,
    status_code=status.HTTP_200_OK,
)
async def switch_round_completeness(
    round_: ScopedRound,
    payload: RoundCompletenessUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> ConditionRoundPublic:
    """Switch an imported round between *Full list* and *Just some* (A7, screen S2-10).

    THE ONE PATH THE SPEC DOES GIVE: `PUT /api/condition-rounds/{id}/completeness`. Its body is
    written there as `{completeness, updated_at}`; the field is `expected_updated_at` here, for the
    reason `RoundCompletenessUpdate` records — every other concurrent write in this feature spells it
    that way.

    THIS IS THE DOOR S2-10'S **Switch to Full list** KNOCKS ON, and switching is what makes absence
    mean something: the comparison is recomputed on the way to *Full list*, and on the way back the
    unconfirmed suggestions are withdrawn while recorded verdicts stay.
    """
    try:
        await switch_completeness(
            db,
            round_=round_,
            completeness=payload.completeness,
            expected_updated_at=payload.expected_updated_at,
            actor_user_id=current_user.id,
        )
    except RoundComparisonRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc

    await db.commit()
    await db.refresh(round_)
    return await _round_card(db, round_)


@router.post(
    "/{loan_file_id}/conditions",
    response_model=ConditionPublic,
    status_code=status.HTTP_201_CREATED,
)
async def add_condition_by_hand(
    loan_file: ScopedLoanFileById,
    payload: ConditionCreateRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> ConditionPublic:
    """Add one condition by hand (screen S1-12).

    201, UNLIKE THE OTHER THREE, because this one genuinely creates a resource with a new id.

    IT TAKES THE LOCK BECAUSE IT MAY CREATE ROUND 1. On a file that has never imported a sheet
    there is no round to file this into, so the service opens one with source `MANUAL` and assigns
    it a number — the same race the import has, and therefore the same narrowing. On a file that has
    imported, it joins the latest imported round and the lock costs nothing.

    THE ROUND IT JOINS IS `PARTIAL`, ALWAYS. A round holding hand-typed conditions is not a claim
    that the lender's list is complete, and ADR-404 lets only a FULL round's absences mean anything —
    so marking it FULL would let Stage 2 later propose that everything nobody typed had been cleared.

    The condition comes back with its round chips, which for a manual condition name the round it was
    filed into rather than a sheet it was printed on; `origin` is the column that keeps those
    distinguishable.
    """
    async with loan_file_needs_lock(loan_file.id):
        condition = await create_manual_condition(
            db, loan_file=loan_file, payload=payload, actor_user_id=current_user.id
        )
        await db.commit()

    await db.refresh(condition)
    numbers, _ = await appearances_for_file(db, loan_file_id=loan_file.id)
    return _condition_public(
        condition,
        round_numbers=numbers.get(condition.id, []),
        today=datetime.now(UTC).date(),
        items=(await items_public_for_file(db, loan_file_id=condition.loan_file_id)).get(
            condition.id, []
        ),
        question_draft=(await question_tails_for_file(db, loan_file_id=condition.loan_file_id)).get(
            condition.id
        ),
        evidence=(await evidence_public_for_file(db, loan_file_id=condition.loan_file_id)).get(
            condition.id, []
        ),
    )


def _refused(exc: ConditionRefused) -> HTTPException:
    """A refusal as the 409 the client reads, carrying the code AND the sentence.

    409, LIKE EVERY OTHER REFUSAL ON THIS FEATURE. Nothing about the request is malformed — a backward
    move without a reason is a well-formed request the condition's STATE declines, which is the same
    translation `import`, `discard`, `enrich` and `reparse` already make. A 422 would say the caller
    sent the wrong shape, and the caller did not.

    A DICT DETAIL, BECAUSE THE CODE HAS TO SURVIVE THE BOUNDARY. `http_exception_handler` passes a dict
    `detail` through as `error.data` and uses its `message` as the envelope's message — the mechanism
    LP-850 added when it found a structured refusal being flattened to "Request failed" and every test
    asserting on the exception object rather than the response. So the UI gets the sentence to show
    (spec §6 rule 5) and the code to branch on, without a second error shape being invented.
    """
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"message": exc.message, "code": exc.code.value},
    )


async def _condition_response(
    db: DbSession, condition: Condition, *, commit: bool = True
) -> ConditionPublic:
    """Commit the write and answer with the condition as the list renders it.

    THE WHOLE ROW COMES BACK, not a bare 204, so the client can replace its copy without a second
    request — and `updated_at` moves on every write, which is the value the NEXT optimistic write has
    to echo. Answering 204 would leave a client holding a stale timestamp and unable to write again
    without refetching.
    """
    if commit:
        await db.commit()
        await db.refresh(condition)
    numbers, _ = await appearances_for_file(db, loan_file_id=condition.loan_file_id)
    return _condition_public(
        condition,
        round_numbers=numbers.get(condition.id, []),
        today=datetime.now(UTC).date(),
        items=(await items_public_for_file(db, loan_file_id=condition.loan_file_id)).get(
            condition.id, []
        ),
        question_draft=(await question_tails_for_file(db, loan_file_id=condition.loan_file_id)).get(
            condition.id
        ),
        evidence=(await evidence_public_for_file(db, loan_file_id=condition.loan_file_id)).get(
            condition.id, []
        ),
    )


async def _scoped_item(db: DbSession, condition: Condition, item_id: UUID) -> ConditionItem:
    """An item of THIS condition — the condition is already tenant-scoped, and the item is looked up
    only under it, so another file's item id answers 404 like a missing one."""
    item = await db.scalar(
        select(ConditionItem).where(
            ConditionItem.id == item_id,
            ConditionItem.condition_id == condition.id,
            ConditionItem.deleted_at.is_(None),
        )
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Item not found.")
    return item


@conditions_by_id_router.put("/{condition_id}/next-step", response_model=ConditionPublic)
async def set_condition_next_step(
    condition: ScopedCondition, payload: NextStepRequest, db: DbSession, current_user: CurrentUser
) -> ConditionPublic:
    """The whole condition's step (S3-02's select), or null to let its items carry their own."""
    await set_next_step(
        db, condition=condition, next_step=payload.next_step, actor_user_id=current_user.id
    )
    return await _condition_response(db, condition)


@conditions_by_id_router.post("/{condition_id}/items", response_model=ConditionPublic)
async def add_condition_item(
    condition: ScopedCondition,
    payload: ConditionItemCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> ConditionPublic:
    """S3-01's "Add an item"."""
    try:
        await add_item(
            db,
            condition=condition,
            name=payload.name,
            performers=payload.performers,
            option=payload.option,
            actor_user_id=current_user.id,
        )
    except PlanRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc
    return await _condition_response(db, condition)


@conditions_by_id_router.patch("/{condition_id}/items/{item_id}", response_model=ConditionPublic)
async def update_condition_item(
    condition: ScopedCondition,
    item_id: UUID,
    payload: ConditionItemUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> ConditionPublic:
    """Change one item's option, wording, who acts or due date."""
    item = await _scoped_item(db, condition, item_id)
    try:
        await update_item(
            db,
            condition=condition,
            item=item,
            option=payload.option,
            name=payload.name,
            performers=payload.performers,
            due_date=payload.due_date,
            actor_user_id=current_user.id,
            status=payload.status,
        )
    except PlanRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc
    return await _condition_response(db, condition)


@conditions_by_id_router.delete("/{condition_id}/items/{item_id}", response_model=ConditionPublic)
async def remove_condition_item(
    condition: ScopedCondition, item_id: UUID, db: DbSession, current_user: CurrentUser
) -> ConditionPublic:
    item = await _scoped_item(db, condition, item_id)
    await remove_item(db, condition=condition, item=item, actor_user_id=current_user.id)
    return await _condition_response(db, condition)


@conditions_by_id_router.post("/{condition_id}/reading/confirm", response_model=ConditionPublic)
async def confirm_condition_reading(
    condition: ScopedCondition,
    payload: ReadingConfirmRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> ConditionPublic:
    """S3-03's "This is right": her items become the reading and are saved for this lender code."""
    try:
        await confirm_reading(
            db,
            condition=condition,
            items=[
                ConfirmedItem(name=item.name, performers=tuple(item.performers), key=item.key)
                for item in payload.items
            ],
            actor_user_id=current_user.id,
        )
    except ReadingRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc
    return await _condition_response(db, condition)


@conditions_by_id_router.post(
    "/{condition_id}/reading/library-default", response_model=ConditionPublic
)
async def use_condition_library_default(
    condition: ScopedCondition,
    db: DbSession,
    current_user: CurrentUser,
) -> ConditionPublic:
    """S3-03's "Use the library default": the library type's items, confirmed as they stand."""
    try:
        await use_library_default(db, condition=condition, actor_user_id=current_user.id)
    except ReadingRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc
    return await _condition_response(db, condition)


@conditions_by_id_router.post("/{condition_id}/prep-status", response_model=ConditionPublic)
async def move_condition_prep_status(
    condition: ScopedCondition,
    payload: PrepStatusRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> ConditionPublic:
    """Move our track (ADR-408, screen S2-05 for the backward case).

    Forward needs nothing; backward needs a reason, and the refusal says so in the spec's own words.
    """
    try:
        await move_prep_status(
            db, condition=condition, payload=payload, actor_user_id=current_user.id
        )
    except ConditionRefused as exc:
        raise _refused(exc) from exc
    return await _condition_response(db, condition)


@conditions_by_id_router.post("/{condition_id}/verdict", response_model=ConditionPublic)
async def record_condition_verdict(
    condition: ScopedCondition,
    payload: VerdictRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> ConditionPublic:
    """Record what the lender said (screen S2-04). The ONLY route to `cleared` or `waived`.

    `source_date` IS THE LENDER'S DATE and the schema gives it no default, so a client that omits it is
    refused rather than silently credited with today. That is the one thing this endpoint exists to
    make impossible (ADR-404).
    """
    try:
        await record_verdict(
            db, condition=condition, payload=payload, actor_user_id=current_user.id
        )
    except ConditionRefused as exc:
        raise _refused(exc) from exc
    return await _condition_response(db, condition)


@conditions_by_id_router.post("/{condition_id}/reopen", response_model=ConditionPublic)
async def reopen_condition(
    condition: ScopedCondition,
    payload: ReopenRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> ConditionPublic:
    """Put a cleared or waived condition back to open, with a reason (S2-05, retitled).

    The old verdict stays in the history — this records that it was overruled, not that it never
    happened, which is what makes the endpoint safe for both a misclick and a re-issue.
    """
    try:
        await reopen(db, condition=condition, payload=payload, actor_user_id=current_user.id)
    except ConditionRefused as exc:
        raise _refused(exc) from exc
    return await _condition_response(db, condition)


@conditions_by_id_router.put("/{condition_id}/owner", response_model=ConditionPublic)
async def set_condition_owner(
    condition: ScopedCondition,
    payload: OwnerRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> ConditionPublic:
    """Set or clear who it is waiting on (A2).

    PUT RATHER THAN POST, AND THE SPEC WRITES IT THAT WAY FOR A REASON: this is the only one of the
    five that SETS a value rather than recording an event about a transition, and sending it twice
    leaves the same state. `owner: null` means "back to the hint", not "nobody".
    """
    try:
        await set_owner(db, condition=condition, payload=payload, actor_user_id=current_user.id)
    except ConditionRefused as exc:
        raise _refused(exc) from exc
    return await _condition_response(db, condition)


@router.post("/{loan_file_id}/conditions/bulk", response_model=BulkResultPublic)
async def bulk_update_conditions(
    loan_file: ScopedLoanFileById,
    payload: BulkRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> BulkResultPublic:
    """One write applied to many conditions, refusing the rows that may not have it.

    200 WITH BOTH HALVES, NOT A 409. Partial success is the expected outcome here rather than an error:
    the UI's line is "4 marked cleared · 1 skipped: information only", so the refusals are DATA. A 409
    would throw away the four that worked, and a 200 listing only the successes would leave a processor
    to work out which row did not move — which is the silent skip this shape exists to prevent.

    THE LOCK IS TAKEN HERE AND IT IS NOT MUTUAL EXCLUSION. `import` takes it at the boundary so it
    spans the commit, and this follows that placement for the same reason. But it yields
    `bool(acquired)`, every caller in this repo proceeds either way, and its 30-second timeout
    auto-expires a HELD lock — so what actually protects a row from a concurrent write is the
    optimistic check on `updated_at`, per row. The lock narrows the window; nothing here may read it as
    closing one.
    """
    async with loan_file_needs_lock(loan_file.id):
        outcome = await apply_bulk(
            db, loan_file_id=loan_file.id, payload=payload, actor_user_id=current_user.id
        )
        await db.commit()

    return BulkResultPublic(
        applied=outcome.applied,
        refused=[
            BulkRefusalPublic(condition_id=condition_id, code=code.value, message=message)
            for condition_id, code, message in outcome.refused
        ],
    )


def _first_arrival(round_: ConditionRound) -> ConditionSourceKind | None:
    """How a round first reached us, or None when its first source names no known kind."""
    first = round_.sources[0] if round_.sources else None
    kind = first.get("kind") if isinstance(first, dict) else None
    try:
        return ConditionSourceKind(kind) if isinstance(kind, str) else None
    except ValueError:
        return None


@conditions_by_id_router.get("/{condition_id}", response_model=ConditionDetailPublic)
async def get_condition(condition: ScopedCondition, db: DbSession) -> ConditionDetailPublic:
    """One condition with every round, and whether it was on each one (screen S2-03).

    NO NEW QUERY ANSWERS "WAS IT ON THIS SHEET". `appearances_for_file` already returns the round
    NUMBERS a condition appeared on, derived from its own events, and every imported round has a
    number — so membership is a lookup rather than a second derivation of the same fact. A draft or
    discarded round has no number and is therefore never "on the sheet", which is correct: its rows
    are not conditions yet.

    THE NOTES ARE MATCHED TO THE ROUND THAT BROUGHT THEM, through each note's `first_seen_round_id`,
    so a dated chip appears against the round it actually arrived in rather than against all of them.
    `first_seen_round_id` is stored as a string by the import, which is why it is compared as one.
    EVERY note of a round, not one: a sheet can carry two notes on one condition, and the first
    version kept only the last (LP-911 review).

    IMPORTED ROUNDS ONLY, OLDEST FIRST BY ROUND NUMBER (spec §LP-916, "one line per imported round").
    The first version walked `list_rounds`, which also returns drafts, failed parses and discarded
    sheets, so a draft under review read as a round this condition was "not on".

    THE HISTORY IS A SEPARATE CALL. `…/events` serves it, for the reason LP-909 gives about the
    round's: this response is fetched whenever the list refreshes, and the history is read only when
    somebody opens one sheet.
    """
    rounds = await imported_rounds_oldest_first(db, loan_file_id=condition.loan_file_id)
    numbers, _ = await appearances_for_file(db, loan_file_id=condition.loan_file_id)
    seen_on = set(numbers.get(condition.id, []))
    notes_by_round: dict[str, list[UnderwriterNotePublic]] = {}
    for note in condition.underwriter_notes or []:
        if isinstance(note, dict) and note.get("first_seen_round_id"):
            notes_by_round.setdefault(str(note["first_seen_round_id"]), []).append(
                UnderwriterNotePublic.model_validate(note)
            )

    appearances = [
        ConditionRoundAppearancePublic(
            round_id=round_.id,
            round_number=round_.round_number,
            round_date=round_.round_date,
            date_printed=round_.date_printed,
            completeness=round_.completeness,
            arrived_as=_first_arrival(round_),
            on_sheet=round_.round_number is not None and round_.round_number in seen_on,
            notes=notes_by_round.get(str(round_.id), []),
        )
        for round_ in rounds
    ]

    public = _condition_public(
        condition,
        round_numbers=sorted(seen_on),
        today=datetime.now(UTC).date(),
        items=(await items_public_for_file(db, loan_file_id=condition.loan_file_id)).get(
            condition.id, []
        ),
        question_draft=(await question_tails_for_file(db, loan_file_id=condition.loan_file_id)).get(
            condition.id
        ),
        evidence=(await evidence_public_for_file(db, loan_file_id=condition.loan_file_id)).get(
            condition.id, []
        ),
    )
    # BUILT FROM THE ROW'S OWN PROJECTION rather than assembled a second time. `ConditionDetailPublic`
    # extends `ConditionPublic` precisely so the sheet cannot carry a different set of fields than the
    # row, and re-listing all twenty here would be the drift that inheritance exists to prevent.
    return ConditionDetailPublic(**public.model_dump(), rounds=appearances)


@conditions_by_id_router.get("/{condition_id}/events", response_model=list[ConditionEventPublic])
async def list_condition_events(
    condition: ScopedCondition, db: DbSession
) -> list[ConditionEventPublic]:
    """One condition's history, newest first — the History section of the detail sheet (S2-03).

    THIS IS THE READER `ix_condition_events_condition_occurred` HAS LACKED SINCE LP-904, and LP-909
    left the question open in as many words: "either something reads it, or it should go in a
    follow-up migration". It is answered here, and no migration is needed.

    WHAT IT CARRIES TODAY IS THIN, AND THAT IS HONEST RATHER THAN BROKEN. `ConditionEventPublic`
    projects a closed set of named scalars, and the ones it names are the ROUND-level keys
    (`rows`, `created`, `seen_again`, …). A condition-level event stores `source`, `lender_code`,
    `changed` and `possible_match`, none of which are projected — `detail` is NPI and the readonly
    layer drops it whole, so opening a door for it here would undo that deliberately. So a caller gets
    `kind`, `occurred_at` and `actor_user_id`, which is exactly what a plain-words sentence needs:
    LP-916 composes "Seen again in round 2" from the KIND, and adds whichever scalars its sentences
    turn out to need, each with the same closed-vocabulary treatment.

    IT IS NO LONGER THIN, AND THE PARAGRAPH ABOVE USED TO SAY IT WAS. LP-916 projects the
    condition-level scalars S2-03's sentences actually need — both status tracks' from→to pairs, a
    verdict's source and the lender's date, and a note COUNT — each drawn from a closed vocabulary
    exactly like the round-level keys. `detail` itself still never travels.

    THE LENDER'S WORDS ARE STILL NOT HERE, AND ONE DESIGN LINE IS POORER FOR IT. S2-03 draws
    "Underwriter note added in round 1: “8/28 Not in Upload”". That quote is the lender's text —
    NPI by rule 7, dropped whole from `readonly.condition_events` — so the sentence ships without it.
    Recorded as a decision in `docs/tickets/LP-916.md` rather than quietly rendered.

    TWO LOOKUPS, NOT TWO PER LINE. A name lives in `users` and a condition event's round is
    `round_id` on the event, so both are resolved for the whole history at once — a per-event query
    would be a query per history line on a sheet that opens constantly.

    Scoped by `get_scoped_condition`, which filters `company_id` inside its statement — so another
    tenant's condition is unfetchable rather than fetched and then refused.
    """
    events = await events_for_condition(db, condition_id=condition.id)

    actor_ids = {event.actor_user_id for event in events if event.actor_user_id is not None}
    names = await resolve_user_names(db, actor_ids)

    round_ids = {event.round_id for event in events if event.round_id is not None}
    numbers: dict[UUID, int] = {}
    if round_ids:
        rows = await db.execute(
            select(ConditionRound.id, ConditionRound.round_number).where(
                ConditionRound.id.in_(round_ids),
                ConditionRound.round_number.is_not(None),
            )
        )
        numbers = {row_id: number for row_id, number in rows.tuples().all() if number is not None}

    return [
        ConditionEventPublic.from_model(
            event,
            actor_name=names.get(event.actor_user_id) if event.actor_user_id else None,
            round_number=numbers.get(event.round_id) if event.round_id else None,
        )
        for event in events
    ]


# --------------------------------------------------------------------------- #
# LP-922 — the round's draft emails. Drafts only: nothing here sends anything.
# --------------------------------------------------------------------------- #


async def _scoped_draft(db: DbSession, loan_file: LoanFile, draft_id: UUID) -> ConditionDraft:
    """A draft of THIS file — the file is tenant-scoped, and the draft is looked up under it."""
    draft = await db.get(ConditionDraft, draft_id)
    if draft is None or draft.loan_file_id != loan_file.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such draft on this file.")
    return draft


@router.get("/{loan_file_id}/condition-drafts", response_model=list[ConditionDraftSummaryPublic])
async def list_condition_drafts(
    loan_file: ScopedLoanFileById, db: DbSession
) -> list[ConditionDraftSummaryPublic]:
    """Every draft the plan made on this file, sent or not ("Drafts for round 1")."""
    rows = await drafts_for_file(db, loan_file_id=loan_file.id)
    return [ConditionDraftSummaryPublic.model_validate(row) for row in rows]


@router.get("/{loan_file_id}/condition-drafts/{draft_id}", response_model=ConditionDraftPublic)
async def get_condition_draft(
    loan_file: ScopedLoanFileById, draft_id: UUID, db: DbSession, current_user: CurrentUser
) -> ConditionDraftPublic:
    """One draft as S3-04 to S3-06 draw it."""
    draft = await _scoped_draft(db, loan_file, draft_id)
    view = await draft_view(db, loan_file=loan_file, draft=draft, actor_user_id=current_user.id)
    return ConditionDraftPublic.model_validate(view)


@router.post(
    "/{loan_file_id}/condition-drafts/{draft_id}/mark-sent", response_model=ConditionDraftPublic
)
async def mark_condition_draft_as_sent(
    loan_file: ScopedLoanFileById, draft_id: UUID, db: DbSession, current_user: CurrentUser
) -> ConditionDraftPublic:
    """She sent it from her own mail. Records it, and moves the conditions to Waiting on …."""
    from app.services.email_send import CannotSendError

    draft = await _scoped_draft(db, loan_file, draft_id)
    try:
        await condition_drafts.mark_sent(
            db, loan_file=loan_file, draft=draft, actor_user_id=current_user.id
        )
    except (DraftRefused, CannotSendError) as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=getattr(exc, "reason", None) or str(exc)
        ) from exc
    await db.commit()
    view = await draft_view(db, loan_file=loan_file, draft=draft, actor_user_id=current_user.id)
    return ConditionDraftPublic.model_validate(view)


@router.delete(
    "/{loan_file_id}/condition-drafts/{draft_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_condition_draft_route(
    loan_file: ScopedLoanFileById, draft_id: UUID, db: DbSession
) -> None:
    """Delete draft. Its items wait for a new draft; nothing moves."""
    draft = await _scoped_draft(db, loan_file, draft_id)
    try:
        await condition_drafts.delete(db, loan_file=loan_file, draft=draft)
    except DraftRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc
    await db.commit()


@router.put(
    "/{loan_file_id}/condition-drafts/{draft_id}/address", response_model=ConditionDraftPublic
)
async def set_condition_draft_address_route(
    loan_file: ScopedLoanFileById,
    draft_id: UUID,
    payload: DraftAddressRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> ConditionDraftPublic:
    """A missing address, given once and remembered on the file."""
    draft = await _scoped_draft(db, loan_file, draft_id)
    await condition_drafts.set_address(
        db,
        loan_file=loan_file,
        draft=draft,
        email=str(payload.email),
        name=payload.name,
        actor_user_id=current_user.id,
    )
    await db.commit()
    view = await draft_view(db, loan_file=loan_file, draft=draft, actor_user_id=current_user.id)
    return ConditionDraftPublic.model_validate(view)


@router.put(
    "/{loan_file_id}/condition-drafts/{draft_id}/due-date", response_model=ConditionDraftPublic
)
async def set_condition_draft_due_date(
    loan_file: ScopedLoanFileById,
    draft_id: UUID,
    payload: DraftDueDateRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> ConditionDraftPublic:
    """The due date the email asks for, edited in the draft."""
    draft = await _scoped_draft(db, loan_file, draft_id)
    try:
        await condition_drafts.set_due_date(
            db,
            loan_file=loan_file,
            draft=draft,
            due=payload.due_date,
            actor_user_id=current_user.id,
        )
    except DraftRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc
    await db.commit()
    view = await draft_view(db, loan_file=loan_file, draft=draft, actor_user_id=current_user.id)
    return ConditionDraftPublic.model_validate(view)


@router.post("/{loan_file_id}/condition-drafts/{draft_id}/polish", response_model=DraftPolishPublic)
async def polish_condition_draft(
    loan_file: ScopedLoanFileById, draft_id: UUID, db: DbSession
) -> DraftPolishPublic:
    """ "Polish with AI" (LP-922 follow-up): a proposal and the facts it changed. Stores nothing."""
    draft = await _scoped_draft(db, loan_file, draft_id)
    try:
        proposal = await condition_drafts.propose_polish(db, loan_file=loan_file, draft=draft)
    except DraftRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc
    return DraftPolishPublic(
        polished_html=proposal.html,
        warnings=[
            DraftFactWarningPublic(kind=w.kind, fact=w.fact, sentence=w.sentence)
            for w in proposal.warnings
        ],
        refusal=proposal.refusal,
    )


@router.put("/{loan_file_id}/condition-drafts/{draft_id}/body", response_model=ConditionDraftPublic)
async def use_condition_draft_polish(
    loan_file: ScopedLoanFileById,
    draft_id: UUID,
    payload: DraftUsePolishRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> ConditionDraftPublic:
    """ "Use this": the AI's polished body replaces the draft's, sanitised and marked as AI-polished."""
    draft = await _scoped_draft(db, loan_file, draft_id)
    try:
        await condition_drafts.use_polish(
            db,
            loan_file=loan_file,
            draft=draft,
            body_html=payload.body_html,
            warnings_accepted=payload.warnings_accepted,
            actor_user_id=current_user.id,
        )
    except DraftRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc
    await db.commit()
    view = await draft_view(db, loan_file=loan_file, draft=draft, actor_user_id=current_user.id)
    return ConditionDraftPublic.model_validate(view)


# --------------------------------------------------------------------------- #
# LP-923 — her answers to what the evidence check found (S3-07, S3-08)
# --------------------------------------------------------------------------- #


@conditions_by_id_router.post(
    "/{condition_id}/evidence/{evidence_id}/accept", response_model=ConditionPublic
)
async def accept_condition_evidence(
    condition: ScopedCondition,
    evidence_id: UUID,
    payload: EvidenceAcceptRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> ConditionPublic:
    """ "Accept anyway…": a failed check accepted with a reason, kept in the history."""
    try:
        await condition_evidence.accept_anyway(
            db,
            condition=condition,
            evidence_id=evidence_id,
            reason=payload.reason,
            actor_user_id=current_user.id,
        )
    except EvidenceRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc
    return await _condition_response(db, condition)


@conditions_by_id_router.post(
    "/{condition_id}/evidence/{evidence_id}/reask", response_model=ConditionPublic
)
async def reask_condition_evidence(
    condition: ScopedCondition, evidence_id: UUID, db: DbSession, current_user: CurrentUser
) -> ConditionPublic:
    """ "Add 'please send page 6' to the borrower email"."""
    try:
        await condition_evidence.reask(
            db, condition=condition, evidence_id=evidence_id, actor_user_id=current_user.id
        )
    except EvidenceRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc
    return await _condition_response(db, condition)


@conditions_by_id_router.post(
    "/{condition_id}/evidence/{evidence_id}/finding", response_model=ConditionPublic
)
async def answer_condition_finding(
    condition: ScopedCondition,
    evidence_id: UUID,
    payload: FindingAnswerRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> ConditionPublic:
    """S3-08: "Ask the borrower to explain it" or "It's already explained…"."""
    try:
        await condition_evidence.answer_finding(
            db,
            condition=condition,
            evidence_id=evidence_id,
            index=payload.index,
            answer=payload.answer,
            reason=payload.reason,
            actor_user_id=current_user.id,
        )
    except EvidenceRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc
    return await _condition_response(db, condition)


# --------------------------------------------------------------------------- #
# LP-924 — the figures check (S3-09). Proposes; applies only when she says so.
# --------------------------------------------------------------------------- #


@router.get("/{loan_file_id}/figures-check", response_model=FiguresCheckPublic)
async def get_figures_check(loan_file: ScopedLoanFileById, db: DbSession) -> FiguresCheckPublic:
    """What the file's accepted evidence changes: computed by code, nothing applied."""
    from app.services import figures_check

    check = await figures_check.figures_check(db, loan_file=loan_file)
    return FiguresCheckPublic.model_validate(figures_check.as_dict(check))


@router.post("/{loan_file_id}/figures-check/apply", response_model=FiguresCheckPublic)
async def apply_figures_check(
    loan_file: ScopedLoanFileById,
    payload: FiguresApplyRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> FiguresCheckPublic:
    """ "Apply N changes to the file's figures" — through the existing edits, with the evidence named."""
    from app.services import figures_check

    try:
        check = await figures_check.apply(
            db,
            loan_file=loan_file,
            expected=[row.model_dump() for row in payload.changes],
            actor_user_id=current_user.id,
        )
    except figures_check.FiguresChanged as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    return FiguresCheckPublic.model_validate(figures_check.as_dict(check))


# --------------------------------------------------------------------------- #
# LP-925 — the package for the lender (S3-10). Nothing is uploaded or sent by the app.
# --------------------------------------------------------------------------- #


async def _package_public(db: DbSession, loan_file: LoanFile) -> PackagePublic | None:
    from dataclasses import asdict

    from app.services import condition_package

    view = await condition_package.view(db, loan_file=loan_file)
    return PackagePublic.model_validate(asdict(view)) if view is not None else None


async def _open_package(db: DbSession, loan_file: LoanFile) -> ConditionPackage:
    from app.services import condition_package

    round_ = await condition_package.newest_round(db, loan_file.id)
    package = await condition_package.open_package(db, round_) if round_ is not None else None
    if package is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Build the package first.")
    return package


@router.get("/{loan_file_id}/condition-package", response_model=PackagePublic | None)
async def get_condition_package(
    loan_file: ScopedLoanFileById, db: DbSession
) -> PackagePublic | None:
    """The newest round's package, or what would go in it."""
    return await _package_public(db, loan_file)


@router.post("/{loan_file_id}/condition-package/build", response_model=PackagePublic)
async def build_condition_package(
    loan_file: ScopedLoanFileById, db: DbSession, current_user: CurrentUser
) -> PackagePublic:
    """Build (or rebuild) the package: one PDF and one note per ready condition; her notes kept."""
    from app.services import condition_package

    try:
        await condition_package.build(db, loan_file=loan_file, actor_user_id=current_user.id)
    except condition_package.PackageRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc
    await db.commit()
    public = await _package_public(db, loan_file)
    assert public is not None
    return public


@router.patch("/{loan_file_id}/condition-package/rows/{condition_id}", response_model=PackagePublic)
async def update_condition_package_row(
    loan_file: ScopedLoanFileById, condition_id: UUID, payload: PackageRowUpdate, db: DbSession
) -> PackagePublic:
    """Her edit to one row: the note, whether it is ticked, a lender field."""
    from app.services import condition_package

    package = await _open_package(db, loan_file)
    try:
        await condition_package.update_row(
            db,
            package=package,
            condition_id=condition_id,
            note=payload.note,
            included=payload.included,
            fields=payload.fields,
        )
    except condition_package.PackageRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc
    await db.commit()
    public = await _package_public(db, loan_file)
    assert public is not None
    return public


@router.post("/{loan_file_id}/condition-package/du-rerun-done", response_model=PackagePublic)
async def mark_condition_package_du_done(
    loan_file: ScopedLoanFileById, db: DbSession
) -> PackagePublic:
    """ "Mark DU re-run done": the warning the figures check raised is cleared for this package."""
    from app.services import condition_package

    package = await _open_package(db, loan_file)
    await condition_package.mark_du_rerun_done(db, package=package)
    await db.commit()
    public = await _package_public(db, loan_file)
    assert public is not None
    return public


@router.post("/{loan_file_id}/condition-package/submit", response_model=PackagePublic)
async def submit_condition_package(
    loan_file: ScopedLoanFileById, db: DbSession, current_user: CurrentUser
) -> PackagePublic:
    """ "Mark submitted": the ticked conditions move to Sent to lender; the package is the record."""
    from app.services import condition_package

    package = await _open_package(db, loan_file)
    try:
        await condition_package.submit(
            db, loan_file=loan_file, package=package, actor_user_id=current_user.id
        )
    except condition_package.PackageRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc
    await db.commit()
    public = await _package_public(db, loan_file)
    assert public is not None
    return public


@router.get("/{loan_file_id}/condition-package/download")
async def download_condition_package(loan_file: ScopedLoanFileById, db: DbSession) -> Response:
    """The zip: one merged PDF per condition, and `notes.txt`. A document that could not be read is
    named in the `X-Package-Missing` header rather than silently left out."""
    from app.services import condition_package

    package = await _open_package(db, loan_file)
    content, missing = await condition_package.download(db, package=package)
    name = f"{loan_file.display_id} package.zip"
    headers = {"Content-Disposition": f'attachment; filename="{name}"'}
    if missing:
        headers["X-Package-Missing"] = str(len(missing))
    return Response(content=content, media_type="application/zip", headers=headers)


# --------------------------------------------------------------------------------------------- #
# LP-940 — withdraw a hand-added condition entered in error (ADR-404 as amended)
# --------------------------------------------------------------------------------------------- #


def _withdraw_refused(exc: Any) -> HTTPException:
    """409 with the sentence, the shape every refusal on this feature uses."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"message": exc.reason, "code": "withdraw_refused"},
    )


@conditions_by_id_router.post("/{condition_id}/withdraw", response_model=WithdrawnConditionPublic)
async def withdraw_condition(
    condition: ScopedCondition,
    payload: WithdrawRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> WithdrawnConditionPublic:
    """Withdraw a condition she added by hand. Refused for a sheet condition, one the lender answered
    on, and one sent in a submitted package; the reason is required and kept in the history."""
    from app.services import condition_withdraw

    loan_file_id = condition.loan_file_id
    try:
        await condition_withdraw.withdraw(
            db, condition=condition, reason=payload.reason, actor_user_id=current_user.id
        )
    except condition_withdraw.WithdrawRefused as exc:
        raise _withdraw_refused(exc) from exc
    await db.commit()
    rows = await condition_withdraw.withdrawn_for_file(db, loan_file_id=loan_file_id)
    (row,) = [r for r in rows if r.id == condition.id]
    return WithdrawnConditionPublic.model_validate(row, from_attributes=True)


@router.post("/{loan_file_id}/conditions/{condition_id}/restore", response_model=ConditionPublic)
async def restore_condition(
    loan_file: ScopedLoanFileById,
    condition_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> ConditionPublic:
    """Undo a withdrawal. Behind the FILE's gate: a withdrawn condition is not found by
    `get_scoped_condition`, by design, so it is looked up on the scoped file, deleted rows included."""
    from app.services import condition_withdraw

    condition = await db.scalar(
        select(Condition).where(
            Condition.id == condition_id, Condition.loan_file_id == loan_file.id
        )
    )
    if condition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Condition not found")
    try:
        await condition_withdraw.restore(db, condition=condition, actor_user_id=current_user.id)
    except condition_withdraw.WithdrawRefused as exc:
        raise _withdraw_refused(exc) from exc
    return await _condition_response(db, condition)


@router.get("/{loan_file_id}/withdrawn-conditions", response_model=list[WithdrawnConditionPublic])
async def list_withdrawn_conditions(
    loan_file: ScopedLoanFileById, db: DbSession
) -> list[WithdrawnConditionPublic]:
    """The list's collapsed "Withdrawn (n)" section, the latest withdrawal first."""
    from app.services import condition_withdraw

    rows = await condition_withdraw.withdrawn_for_file(db, loan_file_id=loan_file.id)
    return [WithdrawnConditionPublic.model_validate(r, from_attributes=True) for r in rows]
