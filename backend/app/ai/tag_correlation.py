"""The AI boundary for Stage-B correlation tag production (LP-314) — the sourcing JUDGE.

Stage B produces cross-entity correlation tags via **candidate-then-judge** (§3D): deterministic
code searches the whole file for candidate sources (``services/tag_correlation.py``); the AI here
JUDGES only ONE deposit against its SMALL candidate set — it never searches, never sees the whole
file. This is what makes correlation scale to any file size. This module is the AI boundary only
(the "judge"), cloned from ``ai/cross_source.py`` / ``ai/tag_production.py``.

The honesty contract (§3D) — the critical distinction this pass turns on:

* ``"no"`` means "we looked and found no source" (the unexplained-deposit signal AS-1 fires on).
  A deposit handed to the judge with NO candidates is a real ``"no"``, NOT ``"unknown"``.
* ``"unknown"`` means "genuinely cannot determine" — reserved for when the input itself is
  unknown; the orchestrator, not this judge, produces that case (DAG propagation).

``complete()`` has no timeout, so the call is wrapped in one — a hung request fails closed
(raises ``AIClientError`` → the orchestrator writes an unknown-with-reason tag), never a
fabricated ``"yes"``. PII flows through the call but is NEVER logged (counts only).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from app.ai.client import AIClientError, complete
from app.ai.parsing import coerce_optional_confidence, extract_json_object, opt_int, opt_str
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_MAX_TOKENS = 2048  # one deposit + a few candidates → a small judgment; no need for the 8k body

# Allowed values for the sourcing tag (fact-tag vocabulary: txn.has_identified_source).
HAS_IDENTIFIED_SOURCE_VALUES = ("yes", "no", "unknown")

STAGE_B_SOURCING_SYSTEM_PROMPT = """\
You are a senior mortgage loan processor judging whether ONE bank deposit is SOURCED — that is,
whether it has a visible, traceable origin. You do NOT decide if the deposit is a problem or
whether it needs a letter; you ONLY judge whether a genuine source is present. Deterministic
code has already searched the whole file and handed you this deposit plus the small set of
candidate sources it found — judge ONLY from what is in front of you.

A deposit IS sourced ("yes") when:
- it is clearly PAYROLL / regular income (its own description/category shows an employer or a
  recurring direct deposit), OR
- a candidate is a GENUINE match — e.g. a transfer FROM the borrower's own account of the same
  amount within a few days (money left one account and arrived here). A genuine source must post
  ON OR BEFORE the deposit (allowing a day or two of bank posting lag): money cannot leave an
  account AFTER it has already arrived, so a candidate dated clearly later than the deposit is
  NOT its source, however closely the amount matches.

A deposit is NOT sourced ("no") when you looked and found NO genuine source — no matching
own-account transfer, no payroll/income signal, no documented origin. IMPORTANT: if you were
given NO candidates and the deposit shows no payroll/income signal of its own, the answer is
"no" — a real "no" meaning "unsourced", NOT "unknown". An unsourced deposit is exactly the
signal downstream rules must catch, so do not soften it to "unknown".

BE HONEST ABOUT *HOW* YOU KNOW — the strength of the evidence matters downstream:
- MATCHED PAPER TRAIL: you found a genuine candidate debit (an own-account transfer of the same
  amount posting on or before the deposit). CITE it (source_index). This is the strongest proof.
- INTRINSIC INCOME: payroll / interest / dividend — sourced by its own nature; no matching debit
  is needed or expected. Say so.
- DESCRIPTION-ONLY CLAIM: the deposit's description CLAIMS an own-account or gift source (e.g.
  "transfer from my brokerage") but NO matching debit was found among the candidates. This is the
  borrower's CLAIM, not a proven paper trail — a fraudster can label a deposit anything. Answer
  "yes" (a source is claimed) with source_index null, but your reasoning MUST state plainly that
  NO matching debit was found and the source rests on the description alone. Do NOT describe a
  description-only claim as though a debit had been matched.

Use "unknown" ONLY if you genuinely cannot tell even what the deposit is.

Judge honestly; a candidate of a coincidentally-similar amount is NOT automatically a source —
say so in the reasoning. Give a confidence reflecting genuine certainty.

STRICT OUTPUT — return ONLY a JSON OBJECT (no markdown fences, no prose before or after):
{
  "value": "yes|no|unknown",
  "source_index": <the index of the candidate you judged to be the genuine source, or null if
                   none applies — including when the deposit is sourced by its OWN payroll/income>,
  "confidence": <0.0-1.0>,
  "reasoning": "<why — cite the payroll signal or the matching candidate, or state that no
                 genuine source was found>"
}
"""


@dataclass(frozen=True)
class SourcingJudgment:
    """The judge's verdict for one deposit."""

    value: str  # yes | no | unknown
    source_index: int | None  # which candidate is the source (1-based), or None
    confidence: float | None
    reasoning: str | None


@dataclass(frozen=True)
class SourcingResult:
    """The result of one sourcing judgment — the verdict (or None if unparseable) + cost/flags."""

    judgment: SourcingJudgment | None
    input_tokens: int
    output_tokens: int
    model: str
    truncated: bool


async def reason_stage_b_sourcing(context_json: str) -> SourcingResult:
    """Judge whether ONE deposit is sourced, given its candidate set (never the whole file).

    ``context_json`` is ``{"deposit": {...}, "candidates": [{"index", ...}, ...]}`` assembled
    deterministically by the orchestrator. Calls Opus at temperature 0, guards truncation, and
    parses defensively (a malformed response → ``judgment=None`` → the orchestrator falls back
    to unknown-with-reason). Raises :class:`~app.ai.client.AIClientError` on a transport failure
    OR a timeout. NEVER logs the context or the response — only counts.
    """
    try:
        result = await asyncio.wait_for(
            complete(
                model=settings.anthropic_model_extraction,  # Opus — real judgment over the facts
                system=STAGE_B_SOURCING_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": context_json}],
                max_tokens=_MAX_TOKENS,
                temperature=0.0,
            ),
            timeout=settings.ai_request_timeout_seconds,
        )
    except TimeoutError as exc:
        logger.warning("stage_b_reason_timeout", timeout_s=settings.ai_request_timeout_seconds)
        raise AIClientError("Stage-B sourcing judgment timed out") from exc

    truncated = result.stop_reason == "max_tokens"
    if truncated:
        logger.warning(
            "stage_b_response_truncated", output_tokens=result.output_tokens, max_tokens=_MAX_TOKENS
        )
    judgment = _parse_judgment(result.text)
    logger.info(
        "stage_b_reasoning_done",
        sourced=judgment.value if judgment is not None else None,  # a single enum, not PII
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        stop_reason=result.stop_reason,
    )
    return SourcingResult(
        judgment=judgment,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        model=result.model,
        truncated=truncated,
    )


def _parse_judgment(text: str) -> SourcingJudgment | None:
    """Defensively parse the response into a SourcingJudgment (never raises)."""
    candidate = extract_json_object(text)
    if candidate is None:
        logger.warning("stage_b_parse_no_json_object")
        return None
    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        logger.warning("stage_b_parse_bad_json")
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("value")
    if not isinstance(value, str) or not value.strip():
        return None
    return SourcingJudgment(
        value=value.strip(),
        source_index=opt_int(data.get("source_index")),
        confidence=coerce_optional_confidence(data.get("confidence")),
        reasoning=opt_str(data.get("reasoning")),
    )


__all__ = [
    "HAS_IDENTIFIED_SOURCE_VALUES",
    "STAGE_B_SOURCING_SYSTEM_PROMPT",
    "AIClientError",
    "SourcingJudgment",
    "SourcingResult",
    "reason_stage_b_sourcing",
]
