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
from typing import Annotated
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
from app.models.condition_round import (
    ConditionRound,
    ConditionRoundCompleteness,
    ConditionRoundStatus,
    ConditionSourceKind,
)
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.schemas.condition import (
    ConditionCreateRequest,
    ConditionDetailPublic,
    ConditionDraftUpdate,
    ConditionEnrichResult,
    ConditionEventPublic,
    ConditionImportResult,
    ConditionPasteRequest,
    ConditionPublic,
    ConditionRoundAppearancePublic,
    ConditionRoundPublic,
    ConditionSort,
    ConditionSummaryPublic,
    UnderwriterNotePublic,
)
from app.services.condition_enrich import RoundNotEnrichable, enrich_round_with_pdf
from app.services.condition_import import (
    RoundNotImportable,
    create_manual_condition,
    import_round,
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
    is_open,
    latest_imported_round,
    list_conditions_filtered,
    list_rounds,
    rows_on_sheet,
)
from app.services.loan_files import get_loan_file
from app.services.needs_engine import loan_file_needs_lock

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
    condition: Condition, *, round_numbers: list[int], today: date
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
    return [
        _condition_public(condition, round_numbers=numbers.get(condition.id, []), today=today)
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
    )


@conditions_by_id_router.get("/{condition_id}", response_model=ConditionDetailPublic)
async def get_condition(condition: ScopedCondition, db: DbSession) -> ConditionDetailPublic:
    """One condition with every round, and whether it was on each one (screen S2-03).

    NO NEW QUERY ANSWERS "WAS IT ON THIS SHEET". `appearances_for_file` already returns the round
    NUMBERS a condition appeared on, derived from its own events, and every imported round has a
    number — so membership is a lookup rather than a second derivation of the same fact. A draft or
    discarded round has no number and is therefore never "on the sheet", which is correct: its rows
    are not conditions yet.

    THE NOTE IS MATCHED TO THE ROUND THAT BROUGHT IT, through the note's `first_seen_round_id`, so a
    dated chip appears against the round it actually arrived in rather than against all of them.
    `first_seen_round_id` is stored as a string by the import, which is why it is compared as one.

    OLDEST FIRST, unlike the round strip: this reads as a history of one condition ("R1 08/28 ✓,
    R2 09/10 not on it"), where the strip answers "what is the newest sheet".

    THE HISTORY IS A SEPARATE CALL. `…/events` serves it, for the reason LP-909 gives about the
    round's: this response is fetched whenever the list refreshes, and the history is read only when
    somebody opens one sheet.
    """
    rounds = await list_rounds(db, loan_file_id=condition.loan_file_id)
    numbers, _ = await appearances_for_file(db, loan_file_id=condition.loan_file_id)
    seen_on = set(numbers.get(condition.id, []))
    notes_by_round = {
        str(note.get("first_seen_round_id")): note
        for note in (condition.underwriter_notes or [])
        if isinstance(note, dict) and note.get("first_seen_round_id")
    }

    appearances = [
        ConditionRoundAppearancePublic(
            round_id=round_.id,
            round_number=round_.round_number,
            round_date=round_.round_date,
            date_printed=round_.date_printed,
            completeness=round_.completeness,
            on_sheet=round_.round_number is not None and round_.round_number in seen_on,
            note=(
                UnderwriterNotePublic.model_validate(notes_by_round[str(round_.id)])
                if str(round_.id) in notes_by_round
                else None
            ),
        )
        # `list_rounds` is newest-first for the strip; a condition's own story reads forwards.
        for round_ in reversed(rounds)
    ]

    public = _condition_public(
        condition,
        round_numbers=sorted(seen_on),
        today=datetime.now(UTC).date(),
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

    Scoped by `get_scoped_condition`, which filters `company_id` inside its statement — so another
    tenant's condition is unfetchable rather than fetched and then refused.
    """
    events = await events_for_condition(db, condition_id=condition.id)
    return [ConditionEventPublic.from_model(event) for event in events]
