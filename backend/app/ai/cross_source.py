"""The AI cross-source capability (LP-78) — one general read-and-compare pass.

This is the **"AI surfaces"** half of the locked two-layer principle (LP-74 built
the deterministic *judge*; this is the *perceiver*). It is **ONE GENERAL
capability, not a rule per check**: the AI reads what the borrower *stated* (the
MISMO application) against what the *documents prove* (the verified extractions)
and surfaces whatever **doesn't line up** — as a single open-ended perception
task. Because it reads and compares (rather than executing pre-written checks), it
catches **known and novel** discrepancies alike — the undisclosed obligation in a
divorce decree that no rule was written for.

The output is **structured findings only** (typed: type, amounts, source document
+ page + snippet, confidence, reasoning) — never prose the deterministic layer
interprets. A starter set of high-value comparisons (income variance, employer,
gift) is **prompt guidance**; the capability stays general (the full ~15-20 is
LP-86).

This module is the AI boundary — it assembles nothing and persists nothing; it
takes a prepared context string and returns parsed structured findings. The
service layer (:mod:`app.services.cross_source`) assembles the two sides and emits
the findings into LP-75's model. PII flows through the call but is **never
logged** (counts/tokens only).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.ai.client import AIClientError, complete
from app.ai.parsing import coerce_confidence, extract_json_object
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_MAX_TOKENS = 4096

CROSS_SOURCE_SYSTEM_PROMPT = """\
You are reviewing a mortgage loan file for DISCREPANCIES between what the borrower
STATED (the application / MISMO data) and what the DOCUMENTS prove (verified
extractions from pay stubs, W-2s, bank statements, gift letters, and other
documents).

Your job is to COMPARE the two sides and surface anything that DOES NOT LINE UP —
including issues that no specific rule covers (for example, an obligation that
appears in a document but is absent from the stated debts, or a property that a
document references but the stated assets omit). Read and compare; do not run a
fixed checklist.

High-value things worth checking (but do NOT limit yourself to these — surface ANY
discrepancy you find):
- Stated monthly income vs. income computed from the pay stubs / W-2s — flag a
  variance greater than 10%.
- Stated employer vs. the employer named on the W-2 / pay stub.
- Stated gift funds vs. the gift letter and the matching bank deposit.

You are SURFACING candidates for a human processor to review — you are not making a
decision. It is acceptable to be uncertain; reflect that in the confidence. Do not
invent discrepancies; if the stated data and the documents agree, return none.

Return ONLY a JSON object of this exact shape (no prose outside the JSON):
{
  "findings": [
    {
      "type": "income_variance" | "employer_mismatch" | "gift_mismatch" |
              "undisclosed_obligation" | "<short_snake_case_for_anything_else>",
      "category": "income" | "assets" | "credit" | "property" | "cross_source",
      "severity": "red" | "yellow",
      "description": "<one-line human summary>",
      "stated_value": "<what the application stated, or null>",
      "document_value": "<what the documents show, or null>",
      "amount": "<the dollar amount at issue, or null>",
      "source_document_type": "<the document type that evidences this, or null>",
      "page": <page number in that document, or null>,
      "snippet": "<verbatim supporting text from the document, or null>",
      "confidence": <0.0 - 1.0>,
      "reasoning": "<why this is a discrepancy>"
    }
  ]
}
"""


@dataclass(frozen=True)
class CrossSourceRawFinding:
    """One structured discrepancy the AI surfaced (pre-persistence)."""

    type: str
    category: str | None
    severity: str | None
    description: str
    stated_value: str | None
    document_value: str | None
    amount: str | None
    source_document_type: str | None
    page: int | None
    snippet: str | None
    confidence: float
    reasoning: str | None


@dataclass(frozen=True)
class CrossSourceResult:
    """The result of one cross-source pass — the findings + the AI cost metadata."""

    findings: list[CrossSourceRawFinding]
    input_tokens: int
    output_tokens: int
    model: str


async def reason_cross_source(context_json: str) -> CrossSourceResult:
    """Run one general AI pass over the assembled stated-vs-verified context.

    Calls Sonnet with the cross-source system prompt and the context as the user
    message, then parses the structured findings defensively (never raises on bad
    JSON — a malformed response yields no findings). Raises
    :class:`~app.ai.client.AIClientError` on a transport failure (the caller marks
    the run FAILED). **Never logs the context or the response** — only counts.
    """
    result = await complete(
        model=settings.anthropic_model_extraction,  # Sonnet — real reasoning over context
        system=CROSS_SOURCE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context_json}],
        max_tokens=_MAX_TOKENS,
    )
    findings = _parse_findings(result.text)
    logger.info(
        "cross_source_reasoning_done",
        findings=len(findings),  # count only — never the findings' content (PII)
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )
    return CrossSourceResult(
        findings=findings,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        model=result.model,
    )


def _parse_findings(text: str) -> list[CrossSourceRawFinding]:
    """Defensively parse the AI response into structured findings (never raises)."""
    snippet = extract_json_object(text)
    if snippet is None:
        return []
    try:
        payload = json.loads(snippet)
    except (json.JSONDecodeError, ValueError):
        return []
    raw_list = payload.get("findings") if isinstance(payload, dict) else None
    if not isinstance(raw_list, list):
        return []
    return [f for item in raw_list if (f := _coerce_finding(item)) is not None]


def _coerce_finding(item: Any) -> CrossSourceRawFinding | None:
    if not isinstance(item, dict):
        return None
    type_ = item.get("type")
    description = item.get("description")
    if not isinstance(type_, str) or not type_ or not isinstance(description, str):
        return None
    return CrossSourceRawFinding(
        type=type_,
        category=_opt_str(item.get("category")),
        severity=_opt_str(item.get("severity")),
        description=description,
        stated_value=_opt_str(item.get("stated_value")),
        document_value=_opt_str(item.get("document_value")),
        amount=_opt_str(item.get("amount")),
        source_document_type=_opt_str(item.get("source_document_type")),
        page=_opt_int(item.get("page")),
        snippet=_opt_str(item.get("snippet")),
        confidence=coerce_confidence(item.get("confidence")),
        reasoning=_opt_str(item.get("reasoning")),
    )


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _opt_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


__all__ = [
    "CROSS_SOURCE_SYSTEM_PROMPT",
    "AIClientError",
    "CrossSourceRawFinding",
    "CrossSourceResult",
    "reason_cross_source",
]
