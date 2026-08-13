"""The extraction bench (dev-only) — the SEPARATION and SAFETY guarantees.

The bench must change NOTHING about the system under test: production prompts byte-unchanged, no
production module depends on the bench, and the rule engine is untouched (ACTIVE_RULE_IDS == 40).
Redaction was REMOVED (Geet's decision) — the bench now captures real values, so its output contains real
PII; that safety is handled by gitignore + warnings, not by scrubbing. It measures COVERAGE, not accuracy.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from app.ai.client import AIClientError
from app.dev.bench.findings import finalize_output, load_records, write_record
from app.dev.bench.prompt import bench_run_context
from fastapi import HTTPException

_BACKEND = Path(__file__).resolve().parents[2]
_APP = _BACKEND / "app"
_PROD_PROMPTS = _APP / "ai" / "prompts" / "extraction"
_BENCH = _APP / "dev" / "bench"


# --------------------------------------------------------------------------- #
# Separation: production is provably untouched (the whole point of the bench living under app/dev/)
# --------------------------------------------------------------------------- #
def test_no_production_prompt_mentions_the_bench_or_pii_placeholder() -> None:
    # No production extraction prompt carries a bench flag or PII-placeholder instruction. (The bench no
    # longer HAS a placeholder — redaction was removed — but production must still be clean of any such
    # runtime injection, so this guard stays.)
    for p in _PROD_PROMPTS.glob("*.txt"):
        text = p.read_text(encoding="utf-8")
        assert (
            "PII PLACEHOLDER" not in text
            and "[SSN]" not in text
            and "extraction bench" not in text.lower()
        )


def test_no_production_module_imports_the_bench() -> None:
    # Nothing under app/ imports app.dev.bench EXCEPT the dev-only API router + the dev-gated main mount.
    allowed = {"api/dev_bench.py", "main.py"}
    offenders = []
    for p in _APP.rglob("*.py"):
        rel = p.relative_to(_APP).as_posix()
        if rel.startswith("dev/") or rel in allowed:
            continue
        if "app.dev.bench" in p.read_text(encoding="utf-8"):
            offenders.append(rel)
    assert not offenders, f"production module(s) import the bench: {offenders}"


def test_redaction_is_fully_removed() -> None:
    # Both layers are gone: the model-side placeholder instruction file, and the belt-and-braces regex.
    assert not (_BENCH / "bench_pii_instruction.txt").exists()
    assert not (_BENCH / "redact.py").exists()


async def test_bench_run_context_does_not_modify_the_prompt() -> None:
    # The runtime wrapper OBSERVES failures only — it must NOT change the system prompt (redaction removed).
    # Proven by capturing what reaches the (mocked) complete: byte-identical inside and outside the context.
    import app.ai.extraction.model_call as model_call

    mock = AsyncMock(return_value=None)
    model_call.complete = mock  # type: ignore[assignment]
    try:
        with bench_run_context():
            await model_call.complete(system="PROD", messages=[], max_tokens=10, model="m")
        assert mock.await_args.kwargs["system"] == "PROD"  # unchanged — nothing appended
    finally:
        _reload_extract_complete()


# --------------------------------------------------------------------------- #
# The bench does not touch the rule engine
# --------------------------------------------------------------------------- #
def test_active_rule_ids_unchanged() -> None:
    from app.verification.rule_engine.registry import ACTIVE_RULE_IDS

    assert (
        len(ACTIVE_RULE_IDS) == 52
    )  # LP-488 +MI-1  # LP-487 +IH-2/IH-7  # LP-486 +CR-12  # LP-485 +CL-1/CR-13/PR-6


# --------------------------------------------------------------------------- #
# Rate limiting: refuse an unpaced Bedrock batch (a mistake worth making impossible)
# --------------------------------------------------------------------------- #
def test_require_paced_refuses_unpaced_bedrock(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import dev_bench
    from app.core.config import settings

    monkeypatch.setattr(settings, "ai_provider", "bedrock")
    monkeypatch.setattr(settings, "ai_requests_per_minute_bedrock", None)
    with pytest.raises(HTTPException) as exc:
        dev_bench._require_paced()
    assert exc.value.status_code == 409
    assert "AI_REQUESTS_PER_MINUTE_BEDROCK" in str(exc.value.detail)


def test_require_paced_allows_paced_bedrock(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import dev_bench
    from app.core.config import settings

    monkeypatch.setattr(settings, "ai_provider", "bedrock")
    monkeypatch.setattr(settings, "ai_requests_per_minute_bedrock", 8)
    dev_bench._require_paced()  # no raise


def test_require_paced_ignores_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    # The anthropic direct API is generous; an unset limit there is fine, so no refusal.
    from app.api import dev_bench
    from app.core.config import settings

    monkeypatch.setattr(settings, "ai_provider", "anthropic")
    monkeypatch.setattr(settings, "ai_requests_per_minute_bedrock", None)
    dev_bench._require_paced()  # no raise


# --------------------------------------------------------------------------- #
# Throttle tagging: a 429/throttle is recorded distinctly, BEFORE the sentinel swallows the type
# --------------------------------------------------------------------------- #
def _reload_extract_complete() -> None:
    import app.ai.extraction.model_call as model_call
    from app.ai.client import complete as real

    model_call.complete = real  # type: ignore[attr-defined]


async def test_throttle_tagged_when_cause_is_transient() -> None:
    # A transient cause (here TimeoutError) means the AIClientError was an INFRASTRUCTURE failure — the
    # bench must tag the document rate_limited so it is never read as a coverage gap.
    import app.ai.extraction.model_call as model_call

    err = AIClientError("AI call failed")
    err.__cause__ = TimeoutError("throttled")
    model_call.complete = AsyncMock(side_effect=err)  # type: ignore[assignment]
    try:
        with bench_run_context() as tally:
            with pytest.raises(AIClientError):
                await model_call.complete(system="s", messages=[], max_tokens=1, model="m")
            assert tally.current_doc_throttled is True
            assert tally.current_doc_failed is True  # a throttle is also a failure
            assert tally.throttled_calls == 1
    finally:
        _reload_extract_complete()


async def test_non_transient_failure_tagged_as_failure_not_throttle() -> None:
    # A non-transient cause (e.g. an auth/credentials error) is an infrastructure failure but NOT a
    # throttle — it must set current_doc_failed (so the run can abort/exclude it) while leaving
    # current_doc_throttled False, and capture the cause type for the report.
    import app.ai.extraction.model_call as model_call

    err = AIClientError("AI call failed")
    err.__cause__ = ValueError("no credentials")
    model_call.complete = AsyncMock(side_effect=err)  # type: ignore[assignment]
    try:
        with bench_run_context() as tally:
            with pytest.raises(AIClientError):
                await model_call.complete(system="s", messages=[], max_tokens=1, model="m")
            assert tally.current_doc_failed is True  # a failure...
            assert tally.current_doc_throttled is False  # ...but NOT a throttle
            assert tally.throttled_calls == 0
            assert tally.last_error_type == "ValueError"  # cause captured for the report
    finally:
        _reload_extract_complete()


# --------------------------------------------------------------------------- #
# Incremental write + resume + rate-limited partitioning
# --------------------------------------------------------------------------- #
def test_write_record_and_load_records_roundtrip(tmp_path: Path) -> None:
    rec = {"source_filename": "a.pdf", "classified_type": "w2", "rate_limited": False}
    write_record(tmp_path, rec, 0)
    assert (tmp_path / "w2" / "0-a.json").is_file()  # per-doc JSON on disk immediately
    assert load_records(tmp_path) == [rec]  # resume log round-trips


def test_write_record_strips_source_extension(tmp_path: Path) -> None:
    # foo.pdf -> <n>-foo.json (NOT foo.pdf.json), so a file browser doesn't try to open the JSON as a PDF.
    rec = {"source_filename": "Mortgage statement 304.pdf", "classified_type": "mortgage_statement"}
    write_record(tmp_path, rec, 12)
    written = list((tmp_path / "mortgage_statement").glob("*.json"))
    assert [p.name for p in written] == ["12-Mortgage_statement_304.json"]
    assert not any(".pdf.json" in p.name for p in written)


def test_load_records_skips_a_corrupt_line(tmp_path: Path) -> None:
    # LP review: a partial/corrupt line (a hard crash mid-write, or a manual edit) must NOT make the
    # whole run unresumable — load_records skips it and returns the intact records.
    from app.dev.bench.findings import RECORDS_LOG

    good = {"source_filename": "a.pdf", "classified_type": "w2"}
    (tmp_path / RECORDS_LOG).write_text(
        json.dumps(good) + "\n" + '{"partial": ' + "\n", encoding="utf-8"
    )
    assert load_records(tmp_path) == [good]  # the good line survives; the truncated one is dropped


async def test_run_records_source_relpath_for_stable_resume_dedup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # LP review: resume must dedup by PATH, not bare filename — two same-named files in different
    # subfolders are DISTINCT documents. _run stamps each record with source_relpath (path under root).
    from app.dev.bench import engine

    (tmp_path / "alice").mkdir()
    (tmp_path / "bob").mkdir()
    files = [
        SimpleNamespace(path=tmp_path / "alice" / "paystub.pdf"),
        SimpleNamespace(path=tmp_path / "bob" / "paystub.pdf"),  # SAME name, different folder
    ]

    async def fake_run_one(f: object) -> dict[str, object]:
        return {
            "source_filename": f.path.name,  # type: ignore[attr-defined]
            "classified_type": "pay_stub",
            "classification_confidence": 0.9,
            "rate_limited": False,
            "extraction": {
                "status": "success",
                "typed_core": {},
                "lists": {},
                "catch_all": [],
                "cost_estimate": 0.0,
            },
        }

    monkeypatch.setattr(engine, "run_one", fake_run_one)
    progress = engine.RunProgress(total=len(files))
    out = tmp_path / "out"
    await engine.run_corpus("rid", tmp_path, files, out, progress, 0)

    # read back from the resume log (progress.records is freed after finalize) — both distinct relpaths,
    # so a resume dedup keyed on them keeps the two same-named files separate.
    relpaths = {r["source_relpath"] for r in load_records(out)}
    assert relpaths == {
        "alice/paystub.pdf",
        "bob/paystub.pdf",
    }  # distinct keys despite the same filename


def test_finalize_excludes_rate_limited_from_findings(tmp_path: Path) -> None:
    records = [
        {
            "source_filename": "ok.pdf",
            "classified_type": "pay_stub",
            "classification_confidence": 0.9,
            "rate_limited": False,
            "extraction": {
                "status": "success",
                "typed_core": {"employer": "AMBIO INC"},
                "lists": {},
                "catch_all": [],
                "cost_estimate": 0.01,
            },
        },
        {
            "source_filename": "throttled.pdf",
            "classified_type": "credit_report",
            "classification_confidence": 0.4,
            "rate_limited": True,
            "ai_failed": True,  # a real throttled record is also an AI failure
            "extraction": {
                "status": "failed",
                "typed_core": {},
                "lists": {},
                "catch_all": [],
                "cost_estimate": None,
            },
        },
    ]
    out = finalize_output(tmp_path, records, tmp_path / "o")
    assert out["failed"]["rate_limited"] == 1
    assert out["failed"]["usable"] == 1
    # the throttled doc's type must NOT appear as a (false) coverage finding
    assert "credit_report" not in out["types"]
    assert "pay_stub" in out["types"]
    summary = (tmp_path / "o" / "_SUMMARY.md").read_text(encoding="utf-8")
    assert "captures REAL PII" in summary  # the real-PII warning is always present
    assert "1 rate-limited (throttled)" in summary  # count is stated, prominently
    assert "RUN FAILED" not in summary  # something succeeded → not a failed run


def test_finalize_marks_run_failed_when_nothing_succeeds(tmp_path: Path) -> None:
    # The 246 x "AI call failed" case: every doc failed → the summary must be marked FAILED at the top and
    # must NOT read like a coverage result.
    records = [
        {
            "source_filename": f"d{i}.pdf",
            "classified_type": "unknown",
            "classification_confidence": 0.0,
            "classification_reasoning": "AI call failed",
            "rate_limited": False,
            "ai_failed": True,
            "failure_error_type": "NoCredentialsError",
            "extraction": {"status": "no_extractor"},
        }
        for i in range(6)
    ]
    out = finalize_output(tmp_path, records, tmp_path / "o")
    assert out["failed"]["usable"] == 0
    assert out["failed"]["auth_or_other"] == 6
    summary = (tmp_path / "o" / "_SUMMARY.md").read_text(encoding="utf-8")
    assert "captures REAL PII" in summary  # PII warning first, then the FAILED banner
    assert "# ⚠️ RUN FAILED" in summary  # FAILED banner present (after the one-line PII warning)
    assert "NoCredentialsError" in summary  # the real cause is named


async def test_run_aborts_after_consecutive_throttles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Several throttles in a row is almost certainly the rate limit — the run must abort, not march on.
    from app.dev.bench import engine
    from app.dev.bench.engine import RunProgress

    files = [SimpleNamespace(path=tmp_path / f"d{i}.pdf") for i in range(10)]

    async def fake_run_one(f: object) -> dict[str, object]:
        return {
            "source_filename": f.path.name,  # type: ignore[attr-defined]
            "classified_type": "pay_stub",
            "rate_limited": True,
            "ai_failed": True,  # a throttle is a failure
            "extraction": {"cost_estimate": 0.0},
        }

    monkeypatch.setattr(engine, "run_one", fake_run_one)
    progress = RunProgress(total=len(files))
    await engine.run_corpus("rid", tmp_path, files, tmp_path / "out", progress, 0)

    assert progress.aborted_reason == "rate_limited"
    assert progress.done == engine.FAILURE_ABORT_STREAK  # stopped early (5), not all 10
    assert progress.rate_limited == engine.FAILURE_ABORT_STREAK
    assert progress.failed == engine.FAILURE_ABORT_STREAK


async def test_run_aborts_after_consecutive_auth_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # This is the 246 x "AI call failed" case: auth failures (non-throttle) must ALSO abort after N, with
    # the cause reported — it should have stopped at 5, not 246.
    from app.dev.bench import engine
    from app.dev.bench.engine import RunProgress

    files = [SimpleNamespace(path=tmp_path / f"d{i}.pdf") for i in range(10)]

    async def fake_run_one(f: object) -> dict[str, object]:
        return {
            "source_filename": f.path.name,  # type: ignore[attr-defined]
            "classified_type": "unknown",
            "rate_limited": False,  # NOT a throttle
            "ai_failed": True,  # an auth/other AI failure
            "failure_error_type": "NoCredentialsError",
            "extraction": {"status": "no_extractor"},
        }

    monkeypatch.setattr(engine, "run_one", fake_run_one)
    progress = RunProgress(total=len(files))
    await engine.run_corpus("rid", tmp_path, files, tmp_path / "out", progress, 0)

    assert progress.aborted_reason == "ai_error"  # distinguished from throttling
    assert progress.abort_error_type == "NoCredentialsError"  # the real cause
    assert progress.done == engine.FAILURE_ABORT_STREAK
    assert progress.rate_limited == 0  # not throttling


# --------------------------------------------------------------------------- #
# Preflight: refuse to start when the model backend is unreachable/unauthenticated
# --------------------------------------------------------------------------- #
async def test_preflight_raises_when_backend_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.ai.client as client
    from app.core.config import settings
    from app.dev.bench.engine import preflight

    monkeypatch.setattr(settings, "ai_provider", "anthropic")  # skip the bedrock env/cache branch
    err = AIClientError("AI call failed")
    err.__cause__ = RuntimeError("NoCredentials")
    monkeypatch.setattr(client, "complete", AsyncMock(side_effect=err))
    with pytest.raises(AIClientError):
        await preflight()


async def test_preflight_passes_when_backend_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.ai.client as client
    from app.core.config import settings
    from app.dev.bench.engine import preflight

    monkeypatch.setattr(settings, "ai_provider", "anthropic")
    monkeypatch.setattr(client, "complete", AsyncMock(return_value=None))
    await preflight()  # no raise


# --------------------------------------------------------------------------- #
# Run planning (shared by both front doors: the dev API and the CLI)
# --------------------------------------------------------------------------- #
def _corpus(root: Path, *names: str) -> Path:
    """A minimal readable corpus — real PDF headers, so walk_documents counts them as readable."""
    for name in names:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"%PDF-1.4\n%stub\n")
    return root


def test_prepare_run_fresh_plans_every_readable_document(tmp_path: Path) -> None:
    from app.dev.bench.engine import prepare_run

    root = _corpus(tmp_path / "corpus", "alice/paystub.pdf", "bob/paystub.pdf", "notes.txt")
    plan = prepare_run(root)
    assert plan.resumed is False
    assert plan.start_index == 0
    assert len(plan.to_run) == 2  # the .txt is unreadable and never sent
    assert plan.out_dir.name == plan.run_id  # output dir is named by run id


def test_prepare_run_resume_skips_done_and_reruns_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Resume must skip the SUCCESSFUL documents and RE-RUN the throttled one (an infrastructure failure
    # is the very reason to resume), while the index continues past every prior record.
    from app.dev.bench import engine

    root = _corpus(tmp_path / "corpus", "a.pdf", "b.pdf", "c.pdf")
    monkeypatch.setattr(engine, "OUTPUT_ROOT", tmp_path / "out")
    out_dir = tmp_path / "out" / "run123"
    write_record(
        out_dir,
        {
            "source_filename": "a.pdf",
            "classified_type": "w2",
            "source_relpath": "a.pdf",
            "rate_limited": False,
        },
        0,
    )
    write_record(
        out_dir,
        {
            "source_filename": "b.pdf",
            "classified_type": "pay_stub",
            "source_relpath": "b.pdf",
            "rate_limited": True,
        },
        1,
    )

    plan = engine.prepare_run(root, "run123")
    assert plan.resumed is True
    assert {f.path.name for f in plan.to_run} == {
        "b.pdf",
        "c.pdf",
    }  # throttled b re-runs; a is done
    assert plan.progress.done == 1  # the one kept record counts toward the corpus total
    assert plan.progress.total == 3
    assert plan.start_index == 2  # past BOTH prior records, so no per-doc JSON is overwritten


def test_prepare_run_unknown_resume_id_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.dev.bench import engine

    monkeypatch.setattr(engine, "OUTPUT_ROOT", tmp_path / "out")
    with pytest.raises(engine.ResumeNotFoundError):
        engine.prepare_run(_corpus(tmp_path / "corpus", "a.pdf"), "nope")


def test_unpaced_reason_matches_the_api_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    # The engine-level condition both front doors refuse on — the API turns it into a 409, the CLI into
    # a non-zero exit. One source of truth, so they cannot drift.
    from app.core.config import settings
    from app.dev.bench.engine import unpaced_reason

    monkeypatch.setattr(settings, "ai_provider", "bedrock")
    monkeypatch.setattr(settings, "ai_requests_per_minute_bedrock", None)
    assert "AI_REQUESTS_PER_MINUTE_BEDROCK" in (unpaced_reason() or "")
    monkeypatch.setattr(settings, "ai_requests_per_minute_bedrock", 8)
    assert unpaced_reason() is None


# --------------------------------------------------------------------------- #
# The CLI front door (scripts/extraction-bench.py) — same engine, no browser required
# --------------------------------------------------------------------------- #
def _cli() -> Any:
    """Load the CLI as a module (its filename has a dash, so it is not importable by name)."""
    import importlib.util

    path = _BACKEND / "scripts" / "extraction-bench.py"
    spec = importlib.util.spec_from_file_location("extraction_bench_cli", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_preview_only_runs_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # --preview-only must print the preview and exit 0 without a preflight or a single model call.
    root = _corpus(tmp_path / "corpus", "a.pdf")
    assert _cli().main([str(root), "--preview-only"]) == 0
    out = capsys.readouterr().out
    assert "estimated cost" in out and "COVERAGE, not accuracy" in out


def test_cli_refuses_unpaced_bedrock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The CLI must refuse the same unpaced batch the API 409s on — before preflight, before any spend.
    from app.core.config import settings

    monkeypatch.setattr(settings, "ai_provider", "bedrock")
    monkeypatch.setattr(settings, "ai_requests_per_minute_bedrock", None)
    root = _corpus(tmp_path / "corpus", "a.pdf")
    assert _cli().main([str(root), "--yes"]) == 1
    assert "AI_REQUESTS_PER_MINUTE_BEDROCK" in capsys.readouterr().err


def test_cli_rejects_a_bad_root(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _cli().main([str(tmp_path / "nope"), "--yes"]) == 1
    assert "not a directory" in capsys.readouterr().err


def test_cli_end_to_end_writes_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The whole CLI path with the model stubbed out: preflight → run → per-document lines → report on
    # disk → exit 0. This is the run the UI does, with no browser involved.
    from app.core.config import settings
    from app.dev.bench import engine

    monkeypatch.setattr(settings, "ai_provider", "anthropic")  # no unpaced-bedrock refusal
    monkeypatch.setattr(engine, "OUTPUT_ROOT", tmp_path / "out")
    monkeypatch.setattr(engine, "preflight", AsyncMock(return_value=None))

    async def fake_run_one(f: object) -> dict[str, object]:
        return {
            "source_filename": f.path.name,  # type: ignore[attr-defined]
            "classified_type": "pay_stub",
            "classification_confidence": 0.95,
            "rate_limited": False,
            "extraction": {
                "status": "success",
                "typed_core": {"employer": "AMBIO INC"},
                "lists": {},
                "catch_all": [],
                "cost_estimate": 0.02,
            },
        }

    monkeypatch.setattr(engine, "run_one", fake_run_one)
    root = _corpus(tmp_path / "corpus", "alice/a.pdf", "bob/b.pdf")

    assert _cli().main([str(root), "--yes"]) == 0
    out = capsys.readouterr().out
    assert "[1/2]" in out and "[2/2]" in out  # a progress line per document, for `tail -f`
    assert "run id" in out  # printed BEFORE the run, so an interrupted run is resumable

    run_dir = next((tmp_path / "out").iterdir())
    assert (run_dir / "_SUMMARY.md").is_file() and (run_dir / "_FINDINGS.csv").is_file()
    assert len(load_records(run_dir)) == 2


# --------------------------------------------------------------------------- #
# Live progress display — the CLI's equivalent of the UI's run panel
# --------------------------------------------------------------------------- #
def _progress(**kw: Any) -> Any:
    from app.dev.bench.engine import RunProgress

    p = RunProgress(total=kw.pop("total", 10))
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def test_display_status_line_mirrors_the_ui_panel() -> None:
    # Same facts the UI's run panel shows: bar, done/total, cost so far, the infrastructure-failure
    # counts (never coverage gaps), and the document in flight.
    p = _progress(total=10, done=3, cost_so_far=1.234, failed=2, rate_limited=1, current="w2.pdf")
    line = _cli()._Display(p, tty=True)._status_line()
    assert " 30%" in line and "3/10" in line and "$1.23" in line
    assert "2 failed (1 throttled)" in line
    assert "w2.pdf" in line
    assert "█" in line and "░" in line  # a filled/empty bar, not just numbers


def test_display_shows_no_eta_before_the_first_document_or_after_the_last() -> None:
    # No ETA can be honest with zero completions, and "~0s left" on a finished run is noise.
    cli = _cli()
    assert cli._Display(_progress(total=10, done=0), tty=True)._eta_seconds() is None
    assert cli._Display(_progress(total=10, done=10), tty=True)._eta_seconds() is None


def test_display_eta_ignores_documents_carried_over_by_a_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # On a resume, progress.done starts at the count already on disk. Those were not run in THIS
    # session, so counting them would report a wildly optimistic rate — the ETA must use only the
    # documents this process actually ran.
    cli = _cli()
    clock = {"t": 1000.0}
    monkeypatch.setattr(cli.time, "monotonic", lambda: clock["t"])
    p = _progress(total=100, done=90)  # resumed: 90 already done, 10 to go
    display = cli._Display(p, tty=True)
    clock["t"] += 10.0  # 10s elapsed...
    p.done = 95  # ...in which 5 documents ran → 2s each → ~10s for the last 5
    eta = display._eta_seconds()
    assert eta is not None and 9.0 < eta < 11.0


def test_display_prints_no_control_codes_when_not_a_tty(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # nohup/pipe/CI: carriage returns and clear-line codes would turn the log file into mush, so the
    # pinned line is suppressed entirely and each document gets one self-contained line instead.
    p = _progress(total=2, done=1, cost_so_far=0.02)
    display = _cli()._Display(p, tty=False)
    display.tick()
    assert capsys.readouterr().out == ""  # nothing pinned, nothing redrawn
    display.on_document(
        {"source_relpath": "a/b.pdf", "classified_type": "w2", "extraction": {"status": "success"}},
        p,
    )
    out = capsys.readouterr().out
    assert "[1/2] $0.02" in out and "a/b.pdf → w2 · success" in out
    assert "\r" not in out and "\033" not in out


def test_cli_sigterm_still_writes_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `kill <pid>` is the ONLY way to stop a detached (nohup'd) run — there is no terminal to Ctrl-C.
    # Unhandled, SIGTERM kills instantly and _SUMMARY.md/_FINDINGS.csv are never written, which is the
    # whole point of the run. It must stop after the in-flight document and finalize, like Cancel does.
    import os
    import signal

    from app.core.config import settings
    from app.dev.bench import engine

    monkeypatch.setattr(settings, "ai_provider", "anthropic")
    monkeypatch.setattr(engine, "OUTPUT_ROOT", tmp_path / "out")
    monkeypatch.setattr(engine, "preflight", AsyncMock(return_value=None))

    sent = False

    async def fake_run_one(f: object) -> dict[str, object]:
        nonlocal sent
        if not sent:  # once — after the handler is removed, a second SIGTERM would hard-kill pytest
            sent = True
            os.kill(os.getpid(), signal.SIGTERM)  # arrives while this document is "in flight"
        # A real await, not sleep(0): the signal reaches the loop through its self-pipe, so it is only
        # delivered once the selector actually polls.
        await asyncio.sleep(0.05)
        return {
            "source_filename": f.path.name,  # type: ignore[attr-defined]
            "classified_type": "pay_stub",
            "classification_confidence": 0.9,
            "rate_limited": False,
            "extraction": {
                "status": "success",
                "typed_core": {},
                "lists": {},
                "catch_all": [],
                "cost_estimate": 0.01,
            },
        }

    monkeypatch.setattr(engine, "run_one", fake_run_one)
    root = _corpus(tmp_path / "corpus", "a.pdf", "b.pdf", "c.pdf")

    assert _cli().main([str(root), "--yes"]) == 130  # cancelled, not a clean finish
    run_dir = next((tmp_path / "out").iterdir())
    assert (run_dir / "_SUMMARY.md").is_file()  # the report exists despite the kill
    assert (run_dir / "_FINDINGS.csv").is_file()
    assert len(load_records(run_dir)) == 1  # stopped after the in-flight document, not all three


# --------------------------------------------------------------------------- #
# run_one's LONG-TAIL path: a doc with no TYPED extractor now runs the production tier path (Tier 3 free
# extraction for unknown/uncataloged, Tier 2 summary otherwise) — so the bench shows what the long tail
# actually captures instead of a bare "no_extractor" (previously Tier 3 looked like it did nothing).
# --------------------------------------------------------------------------- #
def _pdf_file(tmp_path: Path) -> Any:
    from app.dev.bench.engine import DiscoveredFile

    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF-1.4\n%mock\n")
    return DiscoveredFile(path=p, size=p.stat().st_size, media_type="application/pdf")


@pytest.mark.asyncio
async def test_run_one_unknown_runs_tier3_free_extraction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.ai.generic_analyzer import AnalyzedFinding, GenericAnalysis
    from app.dev.bench import engine

    monkeypatch.setattr(
        engine,
        "classify_document",
        AsyncMock(
            return_value=SimpleNamespace(document_type="unknown", confidence=0.9, reasoning="?")
        ),
    )
    analysis = GenericAnalysis(
        document_type_guess="mystery affidavit",
        summary="a mortgage-relevant affidavit",
        key_findings=[AnalyzedFinding(finding_type="obligation", description="owes $500/mo")],
        full_text="THE FULL TEXT THAT MUST BE EXCLUDED",
    )
    analyze = AsyncMock(return_value=analysis)
    monkeypatch.setattr(engine, "analyze_document", analyze)

    record = await engine.run_one(_pdf_file(tmp_path))

    assert record["classified_type"] == "unknown"
    ex = record["extraction"]
    assert ex["status"] == "no_extractor"  # still no TYPED extractor — coverage tally unchanged
    analyze.assert_awaited_once()
    t3 = ex["tier3_free_extraction"]
    assert t3 is not None and t3["summary"] == "a mortgage-relevant affidavit"
    assert t3["key_findings"][0]["description"] == "owes $500/mo"
    assert "full_text" not in t3  # excluded from the record (lives in its own column in prod)
    assert record["findings"]["typed_present"] == 0  # no typed extraction happened


@pytest.mark.asyncio
async def test_run_one_tier2_type_runs_free_extraction_not_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # LP-471: a Tier-2 catalog type with no registered extractor (warranty_deed) no longer gets the LP-65
    # summary — production routes EVERY no-typed-extractor document through the SAME Tier-3 scoped free
    # extraction, so the bench must mirror that (it used to run summarize_document here — the desync LP-471
    # review fixed). (passport was the old example; LP-472 gave it a typed extractor, so it is Tier-1 now.)
    from app.ai.generic_analyzer import GenericAnalysis
    from app.dev.bench import engine

    monkeypatch.setattr(
        engine,
        "classify_document",
        AsyncMock(
            return_value=SimpleNamespace(
                document_type="warranty_deed", confidence=0.95, reasoning="?"
            )
        ),
    )
    analysis = GenericAnalysis(
        document_type_guess="warranty_deed",
        summary="a warranty deed",
        key_findings=[],
        full_text="EXCLUDED",
    )
    analyze = AsyncMock(return_value=analysis)
    monkeypatch.setattr(engine, "analyze_document", analyze)

    record = await engine.run_one(_pdf_file(tmp_path))

    ex = record["extraction"]
    assert ex["status"] == "no_extractor"
    analyze.assert_awaited_once()  # Tier-2 now runs free extraction, not a summary
    assert ex["tier3_free_extraction"] is not None
    assert "tier2_summary" not in ex
