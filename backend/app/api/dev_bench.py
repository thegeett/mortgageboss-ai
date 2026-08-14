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

⚠️ THIS MODULE IS A SHELL. All of the bench's behaviour — planning, the per-document loop, the abort
rules, the report — lives in ``app/dev/bench/engine.py``, shared with the CLI front door
(``scripts/extraction-bench.py``). Anything added here that the CLI would also need belongs in the
engine instead, or the two front doors drift.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.ai.client import AIClientError
from app.core.config import settings
from app.dev.bench.engine import (
    OUTPUT_ROOT,
    ResumeNotFoundError,
    RunProgress,
    preflight,
    prepare_run,
    preview,
    run_corpus,
    unpaced_reason,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/dev/extraction-bench", tags=["dev-extraction-bench"])

# In-memory only (dev tool, nothing persisted). run_id -> state; capped so a long-lived dev server
# doesn't accumulate run state unboundedly (the heavy `records` list is also dropped post-write).
_RUNS: dict[str, RunProgress] = {}
_MAX_RUNS = 50
_TASKS: set[asyncio.Task[None]] = (
    set()
)  # keep strong refs so a background run isn't GC'd mid-flight


def _require_dev() -> None:
    if not settings.is_development:
        raise HTTPException(status_code=404, detail="not found")


def _require_paced() -> None:
    """REFUSE (not warn) to start an UNPACED batch under Bedrock — see :func:`unpaced_reason`. The CLI
    refuses on the same condition; only the shape of the refusal differs (409 here, exit code there)."""
    reason = unpaced_reason()
    if reason is not None:
        raise HTTPException(status_code=409, detail=f"Refusing to start: {reason}")


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
    # PREFLIGHT — one minimal live call proving the model backend is reachable + authenticated BEFORE we
    # process anything. Refuse with the REAL cause rather than march the whole corpus into "AI call
    # failed" records (as the 246-doc run did when the AWS session was not logged in).
    try:
        await preflight()
    except AIClientError as err:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Preflight failed — the model backend is unreachable or unauthenticated: "
                f"{err.__cause__ or err}. Under Bedrock this is almost always AWS credentials: set "
                f"AWS_PROFILE (now in .env) and run `aws sso login --profile <name>`, then retry."
            ),
        ) from err
    try:
        plan = prepare_run(root, req.resume_run_id)
    except ResumeNotFoundError as err:
        raise HTTPException(
            status_code=404, detail=f"no run to resume: {req.resume_run_id}"
        ) from err

    while (
        len(_RUNS) >= _MAX_RUNS
    ):  # evict the oldest (insertion order) — its output is already on disk
        _RUNS.pop(next(iter(_RUNS)))
    _RUNS[plan.run_id] = plan.progress
    task = asyncio.create_task(
        run_corpus(plan.run_id, root, plan.to_run, plan.out_dir, plan.progress, plan.start_index)
    )
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return StartResponse(
        run_id=plan.run_id,
        output_dir=str(plan.out_dir),
        to_run=len(plan.to_run),
        resumed=plan.resumed,
    )


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
    #: documents where any model call failed (auth / throttle / error) — never coverage gaps
    failed: int
    #: set when the run stopped itself: "rate_limited" or "ai_error"; resume to finish the corpus
    aborted_reason: str | None
    #: the underlying cause type at abort (e.g. "NoCredentialsError"), so the UI can name it
    abort_error_type: str | None


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
        output_dir=str(OUTPUT_ROOT / run_id),
        rate_limited=p.rate_limited,
        failed=p.failed,
        aborted_reason=p.aborted_reason,
        abort_error_type=p.abort_error_type,
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
