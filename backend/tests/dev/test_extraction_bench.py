"""The extraction bench (dev-only) — the SEPARATION and SAFETY guarantees.

The bench must change NOTHING about the system under test: production prompts byte-unchanged (the PII
variant is a separate file applied at runtime), no production module depends on the bench, PII is redacted
in two layers, and the rule engine is untouched (ACTIVE_RULE_IDS == 37). It measures COVERAGE, not accuracy.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.ai.client import AIClientError
from app.dev.bench.findings import finalize_output, load_records, write_record
from app.dev.bench.prompt import bench_pii_instruction, bench_pii_prompt, bench_run_context
from app.dev.bench.redact import redact_string, redact_tree
from fastapi import HTTPException

_BACKEND = Path(__file__).resolve().parents[2]
_APP = _BACKEND / "app"
_PROD_PROMPTS = _APP / "ai" / "prompts" / "extraction"
_BENCH = _APP / "dev" / "bench"


# --------------------------------------------------------------------------- #
# Separation: the bench prompt is a SEPARATE file; production is provably untouched
# --------------------------------------------------------------------------- #
def test_bench_pii_instruction_is_a_separate_file_not_under_production_prompts() -> None:
    instruction = _BENCH / "bench_pii_instruction.txt"
    assert instruction.is_file()
    # it lives under dev/bench, NEVER under the production prompt tree
    assert _PROD_PROMPTS not in instruction.parents
    assert "[SSN]" in bench_pii_instruction() and "PII PLACEHOLDER" in bench_pii_instruction()


def test_no_production_prompt_mentions_the_bench_or_pii_placeholder() -> None:
    # No production extraction prompt carries a bench flag / PII-placeholder instruction — the variant is
    # applied at runtime, so production prompts have zero knowledge of it.
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


async def test_bench_prompt_appends_only_within_the_context() -> None:
    # Layer 1: within bench_pii_prompt(), the extraction system prompt gets the PII instruction appended;
    # outside it, the call is byte-unchanged. Proven by capturing what reaches the (mocked) complete.
    import app.ai.extraction.model_call as model_call

    mock = AsyncMock(return_value=None)
    model_call.complete = mock  # type: ignore[assignment]
    try:
        await model_call.complete(system="PROD", messages=[], max_tokens=10, model="m")
        assert mock.await_args.kwargs["system"] == "PROD"  # outside: unchanged
        with bench_pii_prompt():
            await model_call.complete(system="PROD", messages=[], max_tokens=10, model="m")
        inside = mock.await_args.kwargs["system"]
        assert inside.startswith("PROD") and "[SSN]" in inside  # inside: appended
        await model_call.complete(system="PROD", messages=[], max_tokens=10, model="m")
        assert mock.await_args.kwargs["system"] == "PROD"  # restored on exit
    finally:
        importlib_reload_complete(model_call)


def importlib_reload_complete(model_call: object) -> None:
    from app.ai.client import complete as real

    model_call.complete = real  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# Layer 2: the belt-and-braces redaction — identity shapes go, org/amount/code survive
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw",
    ["SSN 123-45-6789", "account 4471000012345", "call (555) 123-4567", "email a.b@x.com"],
)
def test_redact_removes_identity_shapes(raw: str) -> None:
    scrubbed, hits = redact_string(raw)
    assert hits >= 1 and "[redacted]" in scrubbed


@pytest.mark.parametrize(
    "keep",
    [
        "Wells Fargo Bank, N.A.",
        "AMBIO INC",
        "$1,432.00",
        "AS AGREED",
        "HO 00 03",
        "****1234",
        "replacement cost",
    ],
)
def test_redact_keeps_orgs_amounts_codes_and_masked_last4(keep: str) -> None:
    # These are what the bench MEASURES — organisation names, amounts, statuses, form codes, masked last-4.
    scrubbed, hits = redact_string(keep)
    assert hits == 0 and scrubbed == keep


def test_redact_tree_sweeps_lists_and_nested_dicts() -> None:
    body = {
        "typed_core": {"ssn": "123-45-6789"},
        "lists": {"rows": [{"acct": "4471000012345"}]},
        "catch_all": ["x@y.com"],
    }
    scrubbed, hits = redact_tree(body)
    assert hits == 3
    assert scrubbed["typed_core"]["ssn"] == "[redacted]"
    assert scrubbed["lists"]["rows"][0]["acct"] == "[redacted]"


# --------------------------------------------------------------------------- #
# The bench does not touch the rule engine
# --------------------------------------------------------------------------- #
def test_active_rule_ids_unchanged() -> None:
    from app.verification.rule_engine.registry import ACTIVE_RULE_IDS

    assert len(ACTIVE_RULE_IDS) == 37


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
    from app.api import dev_bench

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

    monkeypatch.setattr(dev_bench, "run_one", fake_run_one)
    progress = dev_bench.RunProgress(total=len(files))
    out = tmp_path / "out"
    await dev_bench._run("rid", tmp_path, files, out, progress, 0)

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
    assert summary.startswith("# ⚠️ RUN FAILED")  # FAILED banner at the very top
    assert "NoCredentialsError" in summary  # the real cause is named


async def test_run_aborts_after_consecutive_throttles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Several throttles in a row is almost certainly the rate limit — the run must abort, not march on.
    from app.api import dev_bench
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

    monkeypatch.setattr(dev_bench, "run_one", fake_run_one)
    progress = RunProgress(total=len(files))
    await dev_bench._run("rid", tmp_path, files, tmp_path / "out", progress, 0)

    assert progress.aborted_reason == "rate_limited"
    assert progress.done == dev_bench._FAILURE_ABORT_STREAK  # stopped early (5), not all 10
    assert progress.rate_limited == dev_bench._FAILURE_ABORT_STREAK
    assert progress.failed == dev_bench._FAILURE_ABORT_STREAK


async def test_run_aborts_after_consecutive_auth_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # This is the 246 x "AI call failed" case: auth failures (non-throttle) must ALSO abort after N, with
    # the cause reported — it should have stopped at 5, not 246.
    from app.api import dev_bench
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

    monkeypatch.setattr(dev_bench, "run_one", fake_run_one)
    progress = RunProgress(total=len(files))
    await dev_bench._run("rid", tmp_path, files, tmp_path / "out", progress, 0)

    assert progress.aborted_reason == "ai_error"  # distinguished from throttling
    assert progress.abort_error_type == "NoCredentialsError"  # the real cause
    assert progress.done == dev_bench._FAILURE_ABORT_STREAK
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
