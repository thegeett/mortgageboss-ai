"""The extraction-bench engine — walk, preview+cost, the per-document run, and the corpus loop.

⚠️ MEASURES COVERAGE, NOT ACCURACY. Every fill-rate/value it reports is "was this field POPULATED",
never "is the value CORRECT". Nothing is persisted (JSON output only). It changes nothing about the
system under test — it drives the LIVE classifier and the LIVE registered extractors, read-only.

Everything here is TRANSPORT-FREE: no FastAPI, no HTTP, no database. Both front doors — the dev API
(``app/api/dev_bench.py``) and the CLI (``scripts/extraction-bench.py``) — are thin shells over
:func:`prepare_run` + :func:`run_corpus`, so a CLI run and a UI run are the same run in every respect
(same output root, same abort rules) and either can RESUME the other's run id.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import structlog

from app.ai.classification import classify_document
from app.ai.cost import estimate_cost
from app.ai.extraction import EXTRACTORS
from app.ai.extraction.parsing import failure_detail
from app.ai.generic_analyzer import analyze_document
from app.core.config import resolve_model, resolve_requests_per_minute, settings
from app.dev.bench.findings import finalize_output, load_records, write_record
from app.dev.bench.prompt import CallTally, bench_run_context

logger = structlog.get_logger(__name__)

_SECONDS_PER_MINUTE = 60

#: Abort the run after this many CONSECUTIVE failed documents (throttle / auth / error) — that is almost
#: certainly an infrastructure problem, not the corpus, and continuing would only write records that read
#: as false schema findings. The 246x "AI call failed" run should have stopped at 5, not marched to 246.
FAILURE_ABORT_STREAK = 5

#: Where output is written. Default: INSIDE the storage dir (not a sibling) so it inherits storage's
#: gitignore — bench output derived from borrower documents can never be accidentally committed (LP review).
#: Overridable via BENCH_OUTPUT_DIR for a dev-chosen location (gitignore it if inside the repo). Not
#: web-served: the download endpoint serves by DB storage_path, and these files have no DB row.
OUTPUT_ROOT = (
    Path(settings.bench_output_dir).expanduser().resolve()
    if settings.bench_output_dir
    else Path(settings.storage_local_path).resolve() / "bench_output"
)


class ResumeNotFoundError(Exception):
    """Raised by :func:`prepare_run` when ``resume_run_id`` names no run under :data:`OUTPUT_ROOT`."""


def unpaced_reason() -> str | None:
    """The reason to REFUSE (not warn about) an UNPACED batch, or ``None`` when pacing is fine.

    The account's Bedrock quota is ~10 requests/min; the bench makes 2 calls per document, so an unpaced
    200-document run would be throttled within seconds and its findings corrupted by rate-limit failures.
    An accidental unpaced run is exactly the mistake worth making impossible — so both front doors refuse
    it (the API with a 409, the CLI with a non-zero exit)."""
    if settings.ai_provider == "bedrock" and resolve_requests_per_minute() is None:
        return (
            "AI_PROVIDER=bedrock but no client-side rate limit is set "
            "(AI_REQUESTS_PER_MINUTE_BEDROCK is unset = unlimited). A batch run would exceed the "
            "account's Bedrock quota and be throttled. Set AI_REQUESTS_PER_MINUTE_BEDROCK (e.g. 8 "
            "requests/min = 4 docs/min) and retry."
        )
    return None


async def preflight() -> None:
    """Prove the model backend is REACHABLE and AUTHENTICATED before a batch — one minimal live call
    (mirrors verify-bedrock.py step 1). Raises ``AIClientError`` (the real cause attached) on failure, so
    ``/start`` can refuse rather than march an entire corpus into ``"AI call failed"`` records.

    Under Bedrock it also (a) exports ``settings.aws_profile`` into ``os.environ`` when the launching
    shell provided none — so the backend does not depend on that shell — and (b) rebuilds the cached
    client, so a freshly refreshed SSO session (``aws sso login``) is picked up WITHOUT a server restart."""
    from app.ai.client import complete, get_anthropic_client

    if settings.ai_provider == "bedrock":
        if settings.aws_profile and os.environ.get("AWS_PROFILE") != settings.aws_profile:
            os.environ["AWS_PROFILE"] = settings.aws_profile
        # Drop the cached client so this call reconstructs it and re-reads the current AWS credentials.
        get_anthropic_client.cache_clear()

    await complete(
        model=settings.anthropic_model_classification,
        messages=[{"role": "user", "content": "ping"}],
        max_tokens=1,
    )


# The document formats the pipeline can read natively (LP-37 content block). Anything else is
# "unreadable" for the bench and reported, not sent.
_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

# A ROUGH per-document cost estimate for the PREVIEW only (count x this). Midpoint of the two real
# Haiku-4.5 measurements in the ticket: a credit report ~$0.074, a pay stub ~$0.021. The ACTUAL cost is
# reported per document after the run, from real token counts — this is only to avoid a surprise-spend.
PER_DOC_COST_ESTIMATE = 0.05


@dataclass
class DiscoveredFile:
    path: Path
    size: int
    media_type: str | None  # None = unreadable/unsupported
    unreadable_reason: str | None = None


def walk_documents(root: Path) -> list[DiscoveredFile]:
    """Recursively find every file under ``root`` (nested directories expected), classifying each as a
    readable document or an unreadable one (zero bytes, unsupported extension, or a PDF that isn't one)."""
    found: list[DiscoveredFile] = []
    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            if name.startswith("."):
                continue  # skip .DS_Store etc.
            p = Path(dirpath) / name
            try:
                size = p.stat().st_size
            except OSError:
                continue
            media = _MEDIA_TYPES.get(p.suffix.lower())
            reason: str | None = None
            if size == 0:
                media, reason = None, "zero bytes"
            elif media is None:
                reason = f"unsupported extension {p.suffix or '(none)'!r}"
            elif media == "application/pdf" and not _looks_like_pdf(p):
                media, reason = None, "not a valid PDF (bad header)"
            found.append(DiscoveredFile(p, size, media, reason))
    return found


def _looks_like_pdf(p: Path) -> bool:
    try:
        with p.open("rb") as fh:
            return fh.read(5).startswith(b"%PDF-")
    except OSError:
        return False


#: Model calls per document (classification + extraction). Used for the pacing estimate. It is a FLOOR —
#: a truncation retry adds an extraction call, and each transient retry re-paces — so a throttled run
#: makes more.
CALLS_PER_DOC = 2


@dataclass
class Preview:
    root: str
    total: int
    readable: int
    by_extension: dict[str, int]
    unreadable: list[dict[str, str]]
    per_doc_estimate: float
    estimated_cost: float
    provider: str
    extraction_model: str
    requests_per_minute: int | None
    estimated_minutes: float | None
    note: str = (
        "Estimated cost is count x a rough per-document figure; actual cost is measured per document "
        "after the run. This bench measures COVERAGE (was a field populated), NOT accuracy."
    )


def preview(root: Path) -> Preview:
    """The PREVIEW shown BEFORE anything runs: counts, breakdown, unreadable files, an estimated cost,
    and the pacing (requests/min + estimated duration). Nothing is sent to a model here."""
    files = walk_documents(root)
    readable = [f for f in files if f.media_type is not None]
    by_ext: dict[str, int] = {}
    for f in files:
        by_ext[f.path.suffix.lower() or "(none)"] = (
            by_ext.get(f.path.suffix.lower() or "(none)", 0) + 1
        )
    unreadable = [
        {"file": str(f.path.relative_to(root)), "reason": f.unreadable_reason or "unreadable"}
        for f in files
        if f.media_type is None
    ]
    rpm = resolve_requests_per_minute()
    # Floor duration: CALLS_PER_DOC requests/doc paced at rpm (first request is free). None ⇒ unpaced.
    n_requests = len(readable) * CALLS_PER_DOC
    estimated_minutes = (
        round(max(0, n_requests - 1) * (_SECONDS_PER_MINUTE / rpm) / _SECONDS_PER_MINUTE, 1)
        if rpm and rpm > 0
        else None
    )
    return Preview(
        root=str(root),
        total=len(files),
        readable=len(readable),
        by_extension=dict(sorted(by_ext.items())),
        unreadable=unreadable,
        per_doc_estimate=PER_DOC_COST_ESTIMATE,
        estimated_cost=round(len(readable) * PER_DOC_COST_ESTIMATE, 2),
        provider=settings.ai_provider,
        extraction_model=resolve_model(settings.anthropic_model_extraction),
        requests_per_minute=rpm,
        estimated_minutes=estimated_minutes,
    )


def _result_to_record(data: Any) -> dict[str, Any]:
    """Generic view of any ``*Extraction`` model: typed-core field values, list row-dicts, and the
    catch-all — independent of the concrete result class."""
    typed_core: dict[str, Any] = {}
    lists: dict[str, list[dict[str, Any]]] = {}
    for name in type(data).model_fields:
        if name == "additional_sections":
            continue
        val = getattr(data, name)
        if hasattr(val, "value"):  # a TypedField
            typed_core[name] = val.value
        elif isinstance(val, list):  # a nested list (generic rows or a bespoke record model)
            rows: list[dict[str, Any]] = []
            for row in val:
                if hasattr(row, "model_dump"):
                    rows.append(row.model_dump(mode="json"))
                elif isinstance(row, dict):
                    rows.append(row)
            lists[name] = rows
    catch_all = [
        {"section": s.section, "fields": [{"label": f.label, "value": f.value} for f in s.fields]}
        for s in getattr(data, "additional_sections", []) or []
    ]
    return {"typed_core": typed_core, "lists": lists, "catch_all": catch_all}


async def run_one(f: DiscoveredFile) -> dict[str, Any]:
    """Classify one document, then extract it with the LIVE registered extractor. Returns the
    per-document record (no persistence). ``f.media_type`` must be non-None (a readable file).

    ⚠️ **No redaction.** The bench captures REAL values (identity fields included) — the redaction was
    blanking data the comparison needs (employer EINs, business addresses, reference numbers). So the
    record contains real borrower PII; the output folder must never be committed/shared/moved.

    Both model calls run inside :func:`bench_run_context`, which does NOT change the prompt — it only
    observes failures, so each record is tagged ``rate_limited`` / ``ai_failed`` and an infrastructure
    failure is never read as a coverage gap."""
    assert f.media_type is not None
    content = f.path.read_bytes()

    with bench_run_context() as tally:
        classification = await classify_document(content, f.media_type)
        dtype = classification.document_type
        record: dict[str, Any] = {
            "source_filename": f.path.name,
            "classified_type": dtype,
            "classification_confidence": round(classification.confidence, 4),
            "classification_reasoning": classification.reasoning,
            "size_bytes": f.size,
        }

        extractor = EXTRACTORS.get(dtype)
        if extractor is None:
            # No TYPED (Tier-1) extractor. In production a document does NOT stop here — LP-471 routes EVERY
            # no-typed-extractor document (a Tier-2 type, a Tier-1 type promoted before its extractor is wired,
            # or a Tier-3 uncataloged/``unknown`` type) through the SAME Tier-3 scoped FREE extraction
            # (``analyze_document``, LP-463); the old Tier-2 ``summarize_document`` path is gone. Mirror that
            # here so the bench shows what the long tail ACTUALLY captures — otherwise every no-extractor
            # document is a bare ``no_extractor`` and the long tail looks like it does nothing. ``status`` stays
            # "no_extractor" (there IS no typed extractor — the coverage tally is unchanged; ``coverage`` skips
            # a record with no ``typed_core``); the long-tail output is additive.
            long_tail: dict[str, Any] = {
                "status": "no_extractor",
                "note": f"no typed extractor for {dtype!r}; ran the production long-tail path",
                "extraction_model": resolve_model(settings.anthropic_model_extraction),
            }
            analysis = await analyze_document(content, f.media_type)
            long_tail["tier3_free_extraction"] = (
                analysis.model_dump(mode="json", exclude={"full_text"})
                if analysis is not None
                else None
            )
            record["extraction"] = long_tail
            record["findings"] = _per_document_findings(dtype, None)
            return _tag_outcome(record, tally)

        result = await extractor(content, f.media_type)

    extraction: dict[str, Any] = {
        "status": result.status.value,
        # LP-473: the result attribute is ``reasoning`` (not ``failure_reason`` — that getattr always
        # returned None, so a FAILED extraction showed a blank reason). ``failure_detail`` also names the
        # honest all-null case, so an empty typed core no longer reads as "empty failure, no error type".
        "failure_reason": failure_detail(result.status, getattr(result, "reasoning", None)),
        "input_tokens": getattr(result, "input_tokens", None),
        "output_tokens": getattr(result, "output_tokens", None),
    }
    body = _result_to_record(result.data)  # REAL values — no redaction (identity fields included)
    extraction.update(body)
    extraction["extraction_model"] = resolve_model(settings.anthropic_model_extraction)
    it, ot = extraction["input_tokens"], extraction["output_tokens"]
    # Price on the RAW Anthropic model string, NOT the resolved id: cost.py's table is keyed by the
    # Anthropic names, so a Bedrock inference-profile id (us.anthropic.claude-…) resolves to nothing and
    # would silently estimate 0 (LP review). The resolved id is still the label above.
    extraction["cost_estimate"] = (
        round(
            estimate_cost(
                model=settings.anthropic_model_extraction, input_tokens=it, output_tokens=ot
            ),
            5,
        )
        if it is not None and ot is not None
        else None
    )
    record["extraction"] = extraction
    record["findings"] = _per_document_findings(dtype, body)
    return _tag_outcome(record, tally)


def _tag_outcome(record: dict[str, Any], tally: CallTally) -> dict[str, Any]:
    """Stamp the per-document infrastructure-outcome flags from the call tally.

    ``ai_failed`` = any model call failed (auth/throttle/bad-request); ``failure_error_type`` names
    the exception class; ``infra_kind`` names the CAUSE. These let the report separate
    infrastructure failures from genuine coverage — a throttle or an auth failure must never read
    as a schema gap.

    ``rate_limited`` IS A HISTORICAL KEY NAME AND MEANS "RE-RUNNABLE" (LP-636 defect 2). It is true
    for the whole transient family — throttles, connection failures, 5xx — because that is what
    resume and abort need: all three are worth retrying. Reading it as "was throttled" is what made
    the bench agree with production's mislabel, so ``infra_kind`` now carries the honest answer
    alongside it. The key is not renamed because bench records already on disk use it, and rewriting
    their meaning is worse than documenting it.
    """
    record["rate_limited"] = tally.current_doc_throttled
    record["infra_kind"] = tally.current_doc_infra_kind
    record["ai_failed"] = tally.current_doc_failed
    record["failure_error_type"] = tally.last_error_type
    return record


def _per_document_findings(dtype: str, body: dict[str, Any] | None) -> dict[str, Any]:
    """The per-document slice of the five findings (aggregated across documents in findings.py)."""
    if body is None:
        return {"typed_present": 0, "typed_null": 0, "list_row_counts": {}, "catch_all_count": 0}
    typed = body["typed_core"]
    present = [
        k for k, v in typed.items() if v is not None and (not isinstance(v, str) or v.strip())
    ]
    return {
        "typed_present": len(present),
        "typed_null": len(typed) - len(present),
        "list_row_counts": {name: len(rows) for name, rows in body["lists"].items()},
        "catch_all_count": sum(len(s["fields"]) for s in body["catch_all"]),
    }


@dataclass
class RunProgress:
    total: int
    done: int = 0
    current: str | None = None
    records: list[dict[str, Any]] = field(default_factory=list)
    cost_so_far: float = 0.0
    cancelled: bool = False
    #: documents tagged rate_limited (INFRASTRUCTURE failures — throttling — not coverage gaps)
    rate_limited: int = 0
    #: documents where any model call failed (auth / throttle / bad-request) — never coverage gaps
    failed: int = 0
    #: set when the run stopped itself: "rate_limited" (throttling) or "ai_error" (auth/other failures)
    aborted_reason: str | None = None
    #: the underlying cause type at abort (e.g. "NoCredentialsError"), surfaced in status + summary
    abort_error_type: str | None = None


@dataclass
class RunPlan:
    """Everything decided BEFORE the first model call: which run id, which output dir, which documents
    still need running, and (for a resume) the prior records already folded into ``progress``."""

    run_id: str
    out_dir: Path
    to_run: list[DiscoveredFile]
    progress: RunProgress
    start_index: int
    resumed: bool


def prepare_run(root: Path, resume_run_id: str | None = None) -> RunPlan:
    """Plan a run over ``root`` — a fresh one, or the CONTINUATION of an interrupted one.

    Pass ``resume_run_id`` to continue: its output dir is reused, documents already on disk are skipped,
    and the final findings still aggregate the whole corpus. A 50-90 min Bedrock run must never be
    all-or-nothing. Raises :class:`ResumeNotFoundError` if that run id has no output dir."""
    all_readable = [f for f in walk_documents(root) if f.media_type is not None]

    if not resume_run_id:
        run_id = uuid4().hex[:12]
        return RunPlan(
            run_id=run_id,
            out_dir=OUTPUT_ROOT / run_id,
            to_run=all_readable,
            progress=RunProgress(total=len(all_readable)),
            start_index=0,
            resumed=False,
        )

    out_dir = OUTPUT_ROOT / resume_run_id
    if not out_dir.is_dir():
        raise ResumeNotFoundError(resume_run_id)
    prior = load_records(out_dir)
    # Skip only the SUCCESSFULLY-processed docs; RE-RUN throttled/errored ones (an infrastructure
    # failure is the very reason to resume). Drop their stale records so the re-run replaces them in
    # the aggregate (their old per-document JSON stays on disk, harmless). Dedup by source_relpath —
    # a bare filename is not unique across the nested directories the bench walks (every borrower
    # folder has "paystub.pdf"), so name-dedup would skip un-processed same-named files.
    keep = [r for r in prior if not r.get("rate_limited") and r.get("classified_type") != "error"]
    done_paths = {r.get("source_relpath") for r in keep}
    progress = RunProgress(total=len(all_readable))
    progress.records = keep
    progress.done = len(keep)
    progress.rate_limited = 0  # keep has no rate_limited by construction; re-runs recount live
    progress.cost_so_far = sum((r.get("extraction") or {}).get("cost_estimate") or 0 for r in keep)
    return RunPlan(
        run_id=resume_run_id,
        out_dir=out_dir,
        to_run=[f for f in all_readable if str(f.path.relative_to(root)) not in done_paths],
        progress=progress,
        # Index continues past EVERY prior record (incl. dropped ones) so a re-run never overwrites an
        # existing per-document JSON file.
        start_index=len(prior),
        resumed=True,
    )


async def run_corpus(
    run_id: str,
    root: Path,
    readable: list[DiscoveredFile],
    out_dir: Path,
    progress: RunProgress,
    start_index: int,
    on_document: Callable[[dict[str, Any], RunProgress], None] | None = None,
) -> None:
    """Run every document in ``readable``, writing each record as it completes, then finalize the report.

    Shared by the dev API (which polls ``progress``) and the CLI (which passes ``on_document`` to print a
    line per document). Set ``progress.cancelled`` from anywhere — another task, or a signal handler — to
    stop after the in-flight document and still write the summary."""
    index = start_index
    consecutive_failed = 0
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
                "error": str(exc)[:200],  # raw — the bench captures real values, redaction removed
            }
            logger.warning("bench_document_failed", file=f.path.name, error_type=type(exc).__name__)
        # The STABLE per-document key for resume dedup — a bare filename is not unique across the nested
        # directories the bench walks; the path relative to root is. Set on both the success and error record.
        record["source_relpath"] = str(f.path.relative_to(root))
        progress.records.append(record)
        write_record(out_dir, record, index)  # incremental: a crash loses at most this one document
        index += 1
        progress.cost_so_far += (record.get("extraction") or {}).get("cost_estimate") or 0
        progress.done += 1
        if record.get("rate_limited"):
            progress.rate_limited += 1
        # A run of consecutive FAILURES (throttle / auth / error) is almost certainly infrastructure, not
        # the corpus — abort rather than keep writing records that would read as coverage gaps.
        failed = bool(record.get("ai_failed")) or record.get("classified_type") == "error"
        if failed:
            progress.failed += 1
            consecutive_failed += 1
        else:
            consecutive_failed = 0
        if on_document is not None:
            on_document(record, progress)
        if consecutive_failed >= FAILURE_ABORT_STREAK:
            progress.aborted_reason = "rate_limited" if record.get("rate_limited") else "ai_error"
            progress.abort_error_type = record.get("failure_error_type")
            logger.warning(
                "bench_aborted",
                run_id=run_id,
                done=progress.done,
                reason=progress.aborted_reason,
                error_type=progress.abort_error_type,
            )
            break
    progress.current = None
    if progress.records:
        finalize_output(
            root,
            progress.records,
            out_dir,
            aborted_reason=progress.aborted_reason,
            abort_error_type=progress.abort_error_type,
        )
        progress.records = []  # output is on disk; free the heavy per-document records (status needs only counts)
