"""Extraction-bench dev API — DEV-ONLY, gated so it cannot be reached in production.

⚠️ THE GATE (env check, not obscurity): the router is INCLUDED in the app ONLY when
``settings.is_development`` (see ``main.py``), AND every handler also depends on
:func:`_require_dev`, which 404s under staging/production. Two independent checks — the mount and
the guard — so a misconfigured mount still cannot serve it in prod.

⚠️ ARBITRARY LOCAL PATH, NO AUTH — bind LOCALHOST only. ``/preview`` and ``/start`` take a
caller-supplied ``root`` and walk/read every readable file under it, sending each to the model
(spending money). That arbitrary-path reach is the tool's PURPOSE (a dev points it at their own
corpus), so it is intentionally not confined — which means the dev server that mounts it MUST bind
127.0.0.1, never 0.0.0.0: on a reachable host an unauthenticated caller could read arbitrary files
and spend. The is_development gate keeps it out of staging/prod; the localhost bind is the operator's
responsibility here.

It measures COVERAGE, not accuracy. It writes JSON to disk; it persists NOTHING to the database.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import resolve_requests_per_minute, settings
from app.dev.bench.engine import RunProgress, preview, run_one, walk_documents
from app.dev.bench.findings import finalize_output, load_records, write_record
from app.dev.bench.redact import redact_string

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/dev/extraction-bench", tags=["dev-extraction-bench"])

# In-memory only (dev tool, nothing persisted). run_id -> state; capped so a long-lived dev server
# doesn't accumulate run state unboundedly (the heavy `records` list is also dropped post-write).
_RUNS: dict[str, RunProgress] = {}
_MAX_RUNS = 50
#: Abort the run after this many CONSECUTIVE throttled documents — that is almost certainly the rate
#: limit, and continuing would only write false schema findings (throttles read as coverage gaps).
_THROTTLE_ABORT_STREAK = 3
# INSIDE the storage dir (not a sibling) so it inherits storage's gitignore — bench output derived from
# borrower documents can never be accidentally committed (LP review). Not web-served: the download
# endpoint serves by DB storage_path, and these files have no DB row.
_OUTPUT_ROOT = Path(settings.storage_local_path).resolve() / "bench_output"
_TASKS: set[asyncio.Task[None]] = (
    set()
)  # keep strong refs so a background run isn't GC'd mid-flight


def _require_dev() -> None:
    if not settings.is_development:
        raise HTTPException(status_code=404, detail="not found")


def _require_paced() -> None:
    """REFUSE (not warn) to start an UNPACED batch under Bedrock. The account's Bedrock quota is ~10
    requests/min; the bench makes 2 calls per document, so an unpaced 200-document run would be throttled
    within seconds and its findings corrupted by rate-limit failures. An accidental unpaced run is exactly
    the mistake worth making impossible."""
    if settings.ai_provider == "bedrock" and resolve_requests_per_minute() is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Refusing to start: AI_PROVIDER=bedrock but no client-side rate limit is set "
                "(AI_REQUESTS_PER_MINUTE_BEDROCK is unset = unlimited). A batch run would exceed the "
                "account's Bedrock quota and be throttled. Set AI_REQUESTS_PER_MINUTE_BEDROCK (e.g. 8 "
                "requests/min = 4 docs/min) and retry."
            ),
        )


class RootRequest(BaseModel):
    root: str


class PreviewResponse(BaseModel):
    preview: dict[str, Any]


@router.post("/preview", response_model=PreviewResponse)
def bench_preview(req: RootRequest) -> PreviewResponse:
    """PREVIEW — counts, breakdown, unreadable files, and an estimated cost. Nothing runs; no model call."""
    _require_dev()
    root = Path(req.root).expanduser()
    if not root.is_dir():
        raise HTTPException(status_code=400, detail=f"not a directory: {root}")
    return PreviewResponse(preview=preview(root).__dict__)


class StartRequest(BaseModel):
    root: str
    #: resume an interrupted run by its id — its output dir is reused, already-done documents skipped
    resume_run_id: str | None = None


class StartResponse(BaseModel):
    run_id: str
    output_dir: str
    to_run: int
    resumed: bool


@router.post("/start", response_model=StartResponse)
async def bench_start(req: StartRequest) -> StartResponse:
    """START — launches the run as a background task. Returns immediately with a run_id to poll. Nothing
    runs until this is called (the UI shows the preview first and requires an explicit press).

    Pass ``resume_run_id`` to CONTINUE an interrupted run: its output dir is reused, documents already on
    disk are skipped, and the final findings still aggregate the whole corpus. A 50-90 min Bedrock run
    must never be all-or-nothing."""
    _require_dev()
    _require_paced()
    root = Path(req.root).expanduser()
    if not root.is_dir():
        raise HTTPException(status_code=400, detail=f"not a directory: {root}")
    all_readable = [f for f in walk_documents(root) if f.media_type is not None]

    if req.resume_run_id:
        run_id = req.resume_run_id
        out_dir = _OUTPUT_ROOT / run_id
        if not out_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"no run to resume: {run_id}")
        prior = load_records(out_dir)
        done_names = {
            r["source_filename"] for r in prior
        }  # dedup by name (dev tool; rare collisions ok)
        to_run = [f for f in all_readable if f.path.name not in done_names]
        progress = RunProgress(total=len(all_readable))
        progress.records = prior
        progress.done = len(prior)
        progress.rate_limited = sum(1 for r in prior if r.get("rate_limited"))
        progress.cost_so_far = sum(
            (r.get("extraction") or {}).get("cost_estimate") or 0 for r in prior
        )
        start_index = len(prior)
    else:
        run_id = uuid4().hex[:12]
        out_dir = _OUTPUT_ROOT / run_id
        to_run = all_readable
        progress = RunProgress(total=len(all_readable))
        start_index = 0

    while (
        len(_RUNS) >= _MAX_RUNS
    ):  # evict the oldest (insertion order) — its output is already on disk
        _RUNS.pop(next(iter(_RUNS)))
    _RUNS[run_id] = progress
    task = asyncio.create_task(_run(run_id, root, to_run, out_dir, progress, start_index))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return StartResponse(
        run_id=run_id, output_dir=str(out_dir), to_run=len(to_run), resumed=bool(req.resume_run_id)
    )


async def _run(
    run_id: str,
    root: Path,
    readable: list[Any],
    out_dir: Path,
    progress: RunProgress,
    start_index: int,
) -> None:
    index = start_index
    consecutive_throttled = 0
    for f in readable:
        if progress.cancelled:
            break
        progress.current = f.path.name
        try:
            record = await run_one(f)
        except Exception as exc:  # a single document must never abort the whole run
            record = {
                "source_filename": f.path.name,
                "classified_type": "error",
                # redact the exception too — a parse/validation error can echo document content, and the
                # success path already scrubs (mirror it here so the error path isn't a leak).
                "error": redact_string(str(exc))[0][:200],
            }
            logger.warning("bench_document_failed", file=f.path.name, error_type=type(exc).__name__)
        progress.records.append(record)
        write_record(out_dir, record, index)  # incremental: a crash loses at most this one document
        index += 1
        progress.cost_so_far += (record.get("extraction") or {}).get("cost_estimate") or 0
        progress.done += 1
        # A run of throttled documents is almost certainly the rate limit, not the corpus — abort rather
        # than keep writing records that would read as coverage gaps.
        if record.get("rate_limited"):
            progress.rate_limited += 1
            consecutive_throttled += 1
            if consecutive_throttled >= _THROTTLE_ABORT_STREAK:
                progress.aborted_reason = "rate_limited"
                logger.warning("bench_aborted_throttling", run_id=run_id, done=progress.done)
                break
        else:
            consecutive_throttled = 0
    progress.current = None
    if progress.records:
        finalize_output(root, progress.records, out_dir, aborted_reason=progress.aborted_reason)
        progress.records = []  # output is on disk; free the heavy per-document records (status needs only counts)


class StatusResponse(BaseModel):
    run_id: str
    total: int
    done: int
    current: str | None
    cost_so_far: float
    cancelled: bool
    finished: bool
    output_dir: str
    #: documents throttled (infrastructure failures, NOT coverage gaps) — surfaced so a rate-limit
    #: problem is never mistaken for a schema/network finding
    rate_limited: int
    #: set when the run stopped itself, e.g. "rate_limited"; resume to finish the corpus
    aborted_reason: str | None


@router.get("/status/{run_id}", response_model=StatusResponse)
def bench_status(run_id: str) -> StatusResponse:
    _require_dev()
    p = _RUNS.get(run_id)
    if p is None:
        raise HTTPException(status_code=404, detail="unknown run")
    return StatusResponse(
        run_id=run_id,
        total=p.total,
        done=p.done,
        current=p.current,
        cost_so_far=round(p.cost_so_far, 4),
        cancelled=p.cancelled,
        finished=p.done >= p.total or p.cancelled or p.aborted_reason is not None,
        output_dir=str(_OUTPUT_ROOT / run_id),
        rate_limited=p.rate_limited,
        aborted_reason=p.aborted_reason,
    )


@router.post("/cancel/{run_id}", response_model=StatusResponse)
def bench_cancel(run_id: str) -> StatusResponse:
    """Interrupt a run — it stops after the in-flight document and writes what it has."""
    _require_dev()
    p = _RUNS.get(run_id)
    if p is None:
        raise HTTPException(status_code=404, detail="unknown run")
    p.cancelled = True
    return bench_status(run_id)
