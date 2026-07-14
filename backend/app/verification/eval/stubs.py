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


def _judge_reasoning(fx: FixtureTxn, *, cited: bool) -> str:
    """A human-legible reason (provenance must never be empty - §3D Move 1)."""
    if fx.has_source == "no":
        return "stub: no matching own-account debit and no payroll/income signal - unsourced"
    if fx.apparent_category == "payroll":
        return "stub: recurring payroll / direct deposit - sourced by its own nature"
    if cited:
        return "stub: a matching own-account transfer debit was found and cited - a paper trail"
    return "stub: the description claims a source but NO matching debit was found - a claim only"
