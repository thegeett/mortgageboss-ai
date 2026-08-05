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

from app.core.config import settings
from app.dev.bench.engine import RunProgress, preview, run_one, walk_documents
from app.dev.bench.findings import write_output
from app.dev.bench.redact import redact_string

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/dev/extraction-bench", tags=["dev-extraction-bench"])

# In-memory only (dev tool, nothing persisted). run_id -> state; capped so a long-lived dev server
# doesn't accumulate run state unboundedly (the heavy `records` list is also dropped post-write).
_RUNS: dict[str, RunProgress] = {}
_MAX_RUNS = 50
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


class StartResponse(BaseModel):
    run_id: str
    output_dir: str
    to_run: int


@router.post("/start", response_model=StartResponse)
async def bench_start(req: RootRequest) -> StartResponse:
    """START — launches the run as a background task. Returns immediately with a run_id to poll. Nothing
    runs until this is called (the UI shows the preview first and requires an explicit press)."""
    _require_dev()
    root = Path(req.root).expanduser()
    if not root.is_dir():
        raise HTTPException(status_code=400, detail=f"not a directory: {root}")
    readable = [f for f in walk_documents(root) if f.media_type is not None]
    run_id = uuid4().hex[:12]
    out_dir = _OUTPUT_ROOT / run_id
    progress = RunProgress(total=len(readable))
    while (
        len(_RUNS) >= _MAX_RUNS
    ):  # evict the oldest (insertion order) — its output is already on disk
        _RUNS.pop(next(iter(_RUNS)))
    _RUNS[run_id] = progress
    task = asyncio.create_task(_run(run_id, root, readable, out_dir, progress))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return StartResponse(run_id=run_id, output_dir=str(out_dir), to_run=len(readable))


async def _run(
    run_id: str, root: Path, readable: list[Any], out_dir: Path, progress: RunProgress
) -> None:
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
        progress.cost_so_far += (record.get("extraction") or {}).get("cost_estimate") or 0
        progress.done += 1
    progress.current = None
    if progress.records:
        write_output(root, progress.records, out_dir)
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
        finished=p.done >= p.total or p.cancelled,
        output_dir=str(_OUTPUT_ROOT / run_id),
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
