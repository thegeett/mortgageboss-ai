"""The extraction bench (dev-only) — the SEPARATION and SAFETY guarantees.

The bench must change NOTHING about the system under test: production prompts byte-unchanged (the PII
variant is a separate file applied at runtime), no production module depends on the bench, PII is redacted
in two layers, and the rule engine is untouched (ACTIVE_RULE_IDS == 37). It measures COVERAGE, not accuracy.
"""

from __future__ import annotations

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
            assert tally.throttled_calls == 1
    finally:
        _reload_extract_complete()


async def test_non_transient_failure_is_not_tagged_as_throttle() -> None:
    # A non-transient cause (a genuinely bad document/payload) is a real signal, NOT a throttle.
    import app.ai.extraction.model_call as model_call

    err = AIClientError("AI call failed")
    err.__cause__ = ValueError("bad payload")
    model_call.complete = AsyncMock(side_effect=err)  # type: ignore[assignment]
    try:
        with bench_run_context() as tally:
            with pytest.raises(AIClientError):
                await model_call.complete(system="s", messages=[], max_tokens=1, model="m")
            assert tally.current_doc_throttled is False
            assert tally.throttled_calls == 0
    finally:
        _reload_extract_complete()


# --------------------------------------------------------------------------- #
# Incremental write + resume + rate-limited partitioning
# --------------------------------------------------------------------------- #
def test_write_record_and_load_records_roundtrip(tmp_path: Path) -> None:
    rec = {"source_filename": "a.pdf", "classified_type": "w2", "rate_limited": False}
    write_record(tmp_path, rec, 0)
    assert (tmp_path / "w2" / "0-a.pdf.json").is_file()  # per-doc JSON on disk immediately
    assert load_records(tmp_path) == [rec]  # resume log round-trips


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
    assert out["rate_limited"] == 1
    # the throttled doc's type must NOT appear as a (false) coverage finding
    assert "credit_report" not in out["types"]
    assert "pay_stub" in out["types"]
    summary = (tmp_path / "o" / "_SUMMARY.md").read_text(encoding="utf-8")
    assert "Rate-limited documents: 1" in summary  # count is stated, prominently


async def test_run_aborts_after_consecutive_throttles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Several "AI call failed" in a row is almost certainly the rate limit — the run must abort rather than
    # keep writing records that read as schema gaps.
    from app.api import dev_bench
    from app.dev.bench.engine import RunProgress

    files = [SimpleNamespace(path=SimpleNamespace(name=f"d{i}.pdf")) for i in range(10)]

    async def fake_run_one(f: object) -> dict[str, object]:
        return {
            "source_filename": f.path.name,  # type: ignore[attr-defined]
            "classified_type": "pay_stub",
            "rate_limited": True,
            "extraction": {"cost_estimate": 0.0},
        }

    monkeypatch.setattr(dev_bench, "run_one", fake_run_one)
    progress = RunProgress(total=len(files))
    await dev_bench._run("rid", tmp_path, files, tmp_path / "out", progress, 0)

    assert progress.aborted_reason == "rate_limited"
    assert progress.done == dev_bench._THROTTLE_ABORT_STREAK  # stopped early, not all 10
    assert progress.rate_limited == dev_bench._THROTTLE_ABORT_STREAK
