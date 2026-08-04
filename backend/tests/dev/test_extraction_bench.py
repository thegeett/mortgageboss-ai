"""The extraction bench (dev-only) — the SEPARATION and SAFETY guarantees.

The bench must change NOTHING about the system under test: production prompts byte-unchanged (the PII
variant is a separate file applied at runtime), no production module depends on the bench, PII is redacted
in two layers, and the rule engine is untouched (ACTIVE_RULE_IDS == 37). It measures COVERAGE, not accuracy.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from app.dev.bench.prompt import bench_pii_instruction, bench_pii_prompt
from app.dev.bench.redact import redact_string, redact_tree

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
