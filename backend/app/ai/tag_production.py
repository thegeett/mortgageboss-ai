"""The AI boundary for Stage-A tag production (LP-313) — transactions.

Stage A turns a SINGLE transaction's raw facts into clean atomic fact-tags (§3D): the
AI structures MEANING it perceives (is this money IN or OUT? what does the description
say it IS?), it does NOT evaluate rules or reach conclusions. This module is the AI
boundary only — the "perceiver" half of the two-layer principle, cloned from
``ai/cross_source.py``: it assembles nothing and persists nothing; the orchestration
(batching, caching, writing the tags layer) is ``services/tag_production.py``.

The honesty contract (§3D): the domain of every judged tag ALWAYS includes ``"unknown"``;
a value the model cannot determine is ``"unknown"``, never a guess. Confidence is the
model's own number (the orchestrator nulls it when it falls back). ``complete()`` has no
timeout, so the call is wrapped in one here — a hung request fails closed (raises
``AIClientError``, which the orchestrator turns into unknown-with-reason tags), never a
fabricated value. PII flows through the call but is NEVER logged (counts only).
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

from app.ai.client import AIClientError, complete
from app.ai.parsing import coerce_optional_confidence, extract_json_object, opt_int, opt_str
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_MAX_TOKENS = 8192

# The Stage-A transaction tags this pass judges, and their allowed values (from the
# fact-tag vocabulary, docs/snapshot-fact-tags.xlsx / fact_tags.csv). ``"unknown"`` is
# always a legal value. An AI value outside its set is coerced to ``"unknown"`` by the
# orchestrator (never accepted verbatim — that would smuggle an off-vocabulary tag in).
IS_MONEY_IN_VALUES = ("in", "out", "unknown")
APPARENT_CATEGORY_VALUES = (
    "payroll",
    "transfer_own",
    "transfer_third_party_in",  # LP-379-E (Priya-pending)
    "transfer_third_party_out",  # LP-379-E (Priya-pending)
    "debt_payment",  # LP-379-E (Priya-pending)
    "gift",
    "loan_proceeds",
    "refund",
    "interest",
    "fee",
    "vendor",
    "unknown",
)

STAGE_A_TRANSACTION_SYSTEM_PROMPT = """\
You are a senior mortgage loan processor STRUCTURING raw bank-statement transactions into
clean, factual tags. Your ONLY job is to describe what each transaction IS — you do NOT
evaluate rules, decide if a deposit needs sourcing, or reach any conclusion. Downstream
deterministic code does all judgement; it can only be correct if your facts are accurate.

NORTH STAR — ACCURACY AND HONESTY:
- A WRONG tag silently corrupts every rule that reads it. When you cannot determine a
  value from the transaction in front of you, return "unknown". NEVER guess to look
  complete. "unknown" is a correct, expected answer.
- Judge ONLY from the transaction's own fields (date, amount, a raw direction hint if
  present, and the description). Do not invent a source, a counterparty, or a category
  the text does not support.

FOR EACH TRANSACTION, produce two tags:

1. is_money_in — the DIRECTION of funds, resolved from MEANING, tolerating ANY label the
   bank used (credit / debit / deposit / withdrawal / transfer / ACH / wire / Zelle / a
   raw sign / or nothing at all). Values: "in" (money entered the account), "out" (money
   left it), or "unknown" (genuinely cannot tell). Do NOT assume a positive amount means
   "in" — decide from the description and any direction hint.

2. apparent_category — WHAT the transaction is, from the description. Report ONLY what the
   description shows; a downstream RULE decides the consequence (gift-vs-loan, whether a debt
   recurs). Values:
   "payroll", "transfer_own" (a transfer between the borrower's own accounts),
   "transfer_third_party_in" (money IN from another person or entity the description names —
   e.g. a Zelle / wire / check from a named individual; the honest observable for an inbound a
   rule will later judge a gift or an undisclosed loan),
   "transfer_third_party_out" (money OUT to a named person or entity that is not a merchant or
   a creditor),
   "debt_payment" (a payment to an apparent CREDITOR — a credit-card issuer, a mortgage
   servicer, or a loan (auto / student / personal) — identified from a lender-like payee in the
   description, NOT from the amount; whether it RECURS monthly is a cross-statement rule's
   judgment, not yours),
   "gift" (ONLY if the description itself states the funds are a gift), "loan_proceeds" (ONLY if
   the description itself states a loan disbursement), "refund", "interest", "fee",
   "vendor" (an ordinary purchase / merchant), or "unknown". Pick the single best fit;
   "unknown" if none clearly applies.

For each tag give a confidence (0.0-1.0) reflecting genuine certainty, and a short
reasoning citing the evidence in the description. Be honest in the confidence.

STRICT OUTPUT — return ONLY a JSON ARRAY (no markdown fences, no prose before or after),
one object per transaction, echoing the "index" you were given:
[
  {
    "index": <the transaction's index>,
    "is_money_in": { "value": "in|out|unknown", "confidence": <0.0-1.0>, "reasoning": "<why>" },
    "apparent_category": { "value": "<one of the categories>", "confidence": <0.0-1.0>, "reasoning": "<why>" }
  }
]
Return one object for EVERY transaction index you were given, in any order. Every field
must be present.
"""


@dataclass(frozen=True)
class TagJudgment:
    """The AI's judgment for one tag of one transaction."""

    value: str
    confidence: float | None
    reasoning: str | None


@dataclass(frozen=True)
class TransactionJudgment:
    """The AI's judgments for one transaction, addressed by the batch ``index`` it was given.

    A tag the model omitted or returned malformed is ``None`` here — the orchestrator turns
    that into an unknown-with-reason tag, never a defaulted value.
    """

    index: int
    is_money_in: TagJudgment | None
    apparent_category: TagJudgment | None


@dataclass(frozen=True)
class StageAResult:
    """The result of one Stage-A batch pass — the per-transaction judgments + cost + honesty flags."""

    judgments: list[TransactionJudgment]
    input_tokens: int
    output_tokens: int
    model: str
    truncated: bool


async def reason_stage_a_transactions(context_json: str) -> StageAResult:
    """Run one Stage-A structuring pass over a bounded batch of transactions.

    ``context_json`` is ``{"transactions": [{"index", "date", "amount", "direction",
    "description"}, ...]}`` assembled deterministically by the orchestrator. Calls the
    extraction/reasoning tier (Sonnet by default, env-overridable) at
    temperature 0 (same file → same tags), guards truncation, and parses defensively (a
    malformed response yields no judgments — the orchestrator falls back to unknown). Raises
    :class:`~app.ai.client.AIClientError` on a transport failure OR a timeout (``complete()``
    has none). NEVER logs the context or the response — only counts.
    """
    try:
        result = await asyncio.wait_for(
            complete(
                model=settings.anthropic_model_extraction,  # Sonnet by default — real reasoning over the facts
                system=STAGE_A_TRANSACTION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": context_json}],
                max_tokens=_MAX_TOKENS,
                temperature=0.0,
            ),
            timeout=settings.ai_request_timeout_seconds,
        )
    except TimeoutError as exc:
        # complete() has no timeout; wrap it so a hung call fails closed like any AI error.
        logger.warning("stage_a_reason_timeout", timeout_s=settings.ai_request_timeout_seconds)
        raise AIClientError("Stage-A structuring timed out") from exc

    truncated = result.stop_reason == "max_tokens"
    if truncated:
        # A response cut at max_tokens drops the trailing transactions; surface it loudly so
        # the orchestrator marks the missing ones unknown-with-reason, never silently empty.
        logger.warning(
            "stage_a_response_truncated", output_tokens=result.output_tokens, max_tokens=_MAX_TOKENS
        )
    judgments = _parse_judgments(result.text)
    logger.info(
        "stage_a_reasoning_done",
        judgments=len(judgments),  # count only — never the content (PII)
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        stop_reason=result.stop_reason,
    )
    return StageAResult(
        judgments=judgments,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        model=result.model,
        truncated=truncated,
    )


def _parse_judgments(text: str) -> list[TransactionJudgment]:
    """Defensively parse the AI response into per-transaction judgments (never raises)."""
    raw_list = _load_judgment_list(text)
    if raw_list is None:
        logger.warning("stage_a_parse_no_json_array")  # unparseable — maybe truncated
        return []
    parsed = [j for item in raw_list if (j := _coerce_transaction_judgment(item)) is not None]
    if len(parsed) != len(raw_list):
        logger.warning("stage_a_judgments_dropped", raw=len(raw_list), parsed=len(parsed))
    return parsed


def _load_judgment_list(text: str) -> list[Any] | None:
    """Pull the judgments list out of the response (array, fenced, or wrapped)."""
    for candidate in _json_candidates(text):
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("transactions", "judgments", "results"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
    return None


def _json_candidates(text: str) -> list[str]:
    """Ordered candidate JSON substrings, most-likely first (never raises)."""
    candidates = [text.strip()]
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced is not None:
        candidates.append(fenced.group(1).strip())
    array = _extract_balanced(text, "[", "]")
    if array is not None:
        candidates.append(array)
    obj = extract_json_object(text)
    if obj is not None:
        candidates.append(obj)
    return candidates


def _extract_balanced(text: str, opener: str, closer: str) -> str | None:
    """The first balanced ``opener…closer`` span (depth-aware, string-literal-safe), or ``None``.

    Brackets that appear INSIDE a JSON string — a description or reasoning containing ``[`` /
    ``]`` — are ignored, so an unbalanced bracket in free text can't skew the depth count and
    mis-slice the span. Standard JSON string rules (double quotes, backslash escapes) apply.
    """
    start = text.find(opener)
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _coerce_transaction_judgment(item: Any) -> TransactionJudgment | None:
    """One response object → a TransactionJudgment, or None if it has no usable index."""
    if not isinstance(item, dict):
        return None
    index = opt_int(item.get("index"))
    if index is None:
        return None
    return TransactionJudgment(
        index=index,
        is_money_in=_coerce_tag_judgment(item.get("is_money_in")),
        apparent_category=_coerce_tag_judgment(item.get("apparent_category")),
    )


def _coerce_tag_judgment(item: Any) -> TagJudgment | None:
    """One tag object → a TagJudgment, or None when absent/malformed (→ unknown downstream)."""
    if not isinstance(item, dict):
        return None
    value = item.get("value")
    if not isinstance(value, str) or not value.strip():
        return None
    return TagJudgment(
        value=value.strip(),
        confidence=coerce_optional_confidence(item.get("confidence")),
        reasoning=opt_str(item.get("reasoning")),
    )


__all__ = [
    "APPARENT_CATEGORY_VALUES",
    "IS_MONEY_IN_VALUES",
    "STAGE_A_TRANSACTION_SYSTEM_PROMPT",
    "AIClientError",
    "StageAResult",
    "TagJudgment",
    "TransactionJudgment",
    "reason_stage_a_transactions",
]
