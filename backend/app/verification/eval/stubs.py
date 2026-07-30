"""Fixture-driven stub reasoners - the KEYLESS seam (LP-317).

The pipeline injects a ``reasoner`` for both Stage A and Stage B (the same seam LP-313/314 tests
use). These stubs REPLAY the AI judgment a good model should return for each labeled fixture
transaction, so scoring is deterministic and needs no API key. Everything downstream of the AI -
the candidate search, the strength derivation, the gate, the rule arithmetic - runs for real; only
the model's judgment is replayed.

The stubs key on the transaction DESCRIPTION (unique + redaction-safe per case), so they are robust
to the orchestrator's batching / candidate reordering (which shuffle indices but never the content).
"""

from __future__ import annotations

import json

from app.ai.tag_correlation import SourcingJudgment, SourcingResult
from app.ai.tag_production import (
    StageAResult,
    TagJudgment,
    TransactionJudgment,
)
from app.verification.eval.cases import FixtureTxn
from app.verification.tag_materialization.ai import (
    AiGroupResult,
    AiSubjectJudgment,
    AiTagJudgment,
)
from app.verification.tag_materialization.ai import (
    Reasoner as AiGroupReasoner,
)
from app.verification.tag_materialization.declarations import load_ai_groups, load_declarations

# A stub judgment is high-confidence so the fail-closed gate passes on a well-formed fixture (the
# gate's job is tested by the real pipeline; a fixture that WANTS couldnt_check uses is_money_in
# unknown, not low confidence).
_STUB_CONFIDENCE = 0.9
_STUB_MODEL = "stub"
# The candidate kind that constitutes a matched paper-trail debit (SourceCandidate.kind in
# services.tag_correlation) — cited to yield strength=verified.
_TRANSFER_KIND = "own_account_transfer"


class StubStageAReasoner:
    """Replays each fixture transaction's Stage-A judgment, keyed by description."""

    def __init__(self, txns: tuple[FixtureTxn, ...]) -> None:
        self._by_key = {t.key: t for t in txns}

    async def __call__(self, context_json: str) -> StageAResult:
        context = json.loads(context_json)
        judgments: list[TransactionJudgment] = []
        for entry in context["transactions"]:
            fx = self._lookup(entry["description"])
            judgments.append(
                TransactionJudgment(
                    index=entry["index"],
                    is_money_in=TagJudgment(
                        fx.is_money_in, _STUB_CONFIDENCE, "stub: labeled fixture"
                    ),
                    apparent_category=TagJudgment(
                        fx.apparent_category, _STUB_CONFIDENCE, "stub: labeled fixture"
                    ),
                )
            )
        return StageAResult(
            judgments=judgments,
            input_tokens=0,
            output_tokens=0,
            model=_STUB_MODEL,
            truncated=False,
        )

    def _lookup(self, description: str | None) -> FixtureTxn:
        fx = self._by_key.get(description or "")
        if fx is None:  # a fixture whose description was rewritten (redaction) or is not labeled
            raise KeyError(f"stage-A stub has no label for description {description!r}")
        return fx


class StubStageBReasoner:
    """Replays each money-in deposit's sourcing judgment, keyed by the deposit description.

    A ``yes`` that should rest on a matched paper trail cites candidate index 1 (the deterministic
    search having found the debit); a ``yes`` that is a description-only claim cites nothing, so the
    real strength derivation yields ``self_asserted``.
    """

    def __init__(self, txns: tuple[FixtureTxn, ...]) -> None:
        self._by_key = {t.key: t for t in txns}

    async def __call__(self, context_json: str) -> SourcingResult:
        context = json.loads(context_json)
        deposit = context["deposit"]
        candidates = context["candidates"]
        fx = self._lookup(deposit["description"])
        if fx.has_source is None:
            raise ValueError(
                f"stage-B stub was asked to judge {fx.key!r} but the fixture set has_source=None "
                f"(only money-in subjects are judged - check the fixture label)"
            )
        # Cite the matched own-account-transfer candidate by KIND (not a hardcoded index 1):
        # find_source_candidates lists a payroll self-candidate FIRST when present, so index 1 is
        # not always the debit. A real model cites the genuine paper-trail debit; replay that.
        source_index = None
        if fx.cite_candidate:
            source_index = next(
                (c["index"] for c in candidates if c.get("kind") == _TRANSFER_KIND), None
            )
        reasoning = _judge_reasoning(fx, cited=source_index is not None)
        return SourcingResult(
            judgment=SourcingJudgment(
                value=fx.has_source,
                source_index=source_index,
                confidence=_STUB_CONFIDENCE,
                reasoning=reasoning,
            ),
            input_tokens=0,
            output_tokens=0,
            model=_STUB_MODEL,
            truncated=False,
        )

    def _lookup(self, description: str | None) -> FixtureTxn:
        fx = self._by_key.get(description or "")
        if fx is None:
            raise KeyError(f"stage-B stub has no label for deposit {description!r}")
        return fx


class _StubAiGroupReasoner:
    """Replays an AI-group structuring pass (LP-326) — an HONEST abstention (WITH confidence, so it is
    a genuine judgment, NOT a fail-closed degradation) for every subject the group is asked about.

    The abstention value is `unknown` where the tag's vocabulary allows it (or is free-text). For a
    presence/eligibility enum that has no `unknown` but DOES have `no` (income.voe_present = yes|no — LP-428;
    stmt.is_reserve_eligible = yes|no|partial — LP-429), `unknown` is off-vocabulary and would be COERCED to a
    null-confidence fail-closed tag, spuriously flipping `run.degraded`; there the stub emits the in-vocab
    honest `no` (a bank statement is not a VOE; an abstaining reserve check is "not eligible" — a real model
    would return `no` too). A MULTI-category enum with no `no` and no `unknown` (income.type = base|bonus|…)
    keeps abstaining to `unknown` (still coerced to fail-closed — its callers rely on that honest-unknown,
    e.g. IN-12's self-employment gate).

    A fixture built for the txn/AS-1/OC-2 pipeline has no identity documents, so the id.* groups
    correctly perceive nothing — a clean run, not a degraded one. A test that WANTS a real id.* value
    supplies its own reasoner for that group.
    """

    def __init__(self, shorts: tuple[str, ...], values: dict[str, str] | None = None) -> None:
        self.shorts = shorts
        self.values = (
            values or {}
        )  # short -> the in-vocabulary abstention value (defaults to "unknown")
        self.calls = 0

    async def __call__(self, context_json: str) -> AiGroupResult:
        self.calls += 1
        subjects = json.loads(context_json).get("subjects", [])
        judgments = [
            AiSubjectJudgment(
                index=int(s["index"]),
                tags={
                    short: AiTagJudgment(
                        self.values.get(short, "unknown"),
                        _STUB_CONFIDENCE,
                        "not stated in this document",
                    )
                    for short in self.shorts
                },
            )
            for s in subjects
        ]
        return AiGroupResult(
            judgments, input_tokens=1, output_tokens=1, model=_STUB_MODEL, truncated=False
        )


def stub_materialization_reasoners(subject: str | None = None) -> dict[str, AiGroupReasoner]:
    """A keyless materialization seam (LP-326) — one honest-unknown stub per declared AI group, so the
    orchestrator's materialization stage never hits the network in a test.

    ``subject=None`` (the default) stubs EVERY declared group regardless of subject family — the
    orchestrator materializes all of them (``document`` AND ``loan``-subject groups like ``occupancy``),
    so a document-only seam would leave the loan-subject groups to fall through to the real model. Pass a
    specific subject to scope the seam to one family."""
    decls = (
        load_declarations()
    )  # per-tag allowed_values, to keep the stub's abstention IN-vocabulary
    reasoners: dict[str, AiGroupReasoner] = {}
    for key, group in load_ai_groups().items():
        if subject is not None and group.subject != subject:
            continue
        shorts = tuple(tag_id.rsplit(".", 1)[-1] for tag_id in group.tag_ids)
        values: dict[str, str] = {}
        for tag_id in group.tag_ids:
            short = tag_id.rsplit(".", 1)[-1]
            allowed = decls[tag_id].allowed_values if tag_id in decls else None
            if allowed is None or "unknown" in allowed:
                values[short] = (
                    "unknown"  # free-text or an enum that permits it — a genuine abstention
                )
            elif "no" in allowed:
                values[short] = (
                    "no"  # a presence/eligibility check — the in-vocab honest "not this"
                )
            else:
                values[short] = (
                    "unknown"  # a multi-category enum, no honest default → abstain (coerced)
                )
        reasoners[key] = _StubAiGroupReasoner(shorts, values)
    return reasoners


def _judge_reasoning(fx: FixtureTxn, *, cited: bool) -> str:
    """A human-legible reason (provenance must never be empty - §3D Move 1)."""
    if fx.has_source == "no":
        return "stub: no matching own-account debit and no payroll/income signal - unsourced"
    if fx.apparent_category == "payroll":
        return "stub: recurring payroll / direct deposit - sourced by its own nature"
    if cited:
        return "stub: a matching own-account transfer debit was found and cited - a paper trail"
    return "stub: the description claims a source but NO matching debit was found - a claim only"
