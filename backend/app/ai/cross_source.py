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

_MAX_TOKENS = 8192

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
discrepancy you find, using the "other" type below):
- Stated monthly income vs. income computed from the pay stubs / W-2s — flag a
  variance greater than 10%.
- Stated employer vs. the employer named on the W-2 / pay stub.
- Stated gift funds vs. the gift letter and the matching bank deposit.

You are SURFACING candidates for a human processor to review — you are not making a
decision. It is acceptable to be uncertain; reflect that in the confidence. Do not
invent discrepancies; if the stated data and the documents agree, return none.

CHOOSE THE TYPE from this fixed list when one fits (use the EXACT string), so the
same kind of discrepancy is labelled the same way every time:
- "income_variance"            — stated income vs. income shown by pay stubs / W-2s
- "employer_mismatch"          — stated employer vs. the employer on the documents
- "gift_documentation_missing" — a stated gift lacks a gift letter / matching deposit
- "co_borrower_income_missing" — a co-borrower is on the file but has no income/asset/
                                 liability data or supporting documents
- "property_address_mismatch"  — the subject-property address differs across sources
- "loan_amount_variance"       — the loan amount is inconsistent with price / down payment
- "asset_undocumented"         — a stated asset (e.g. stocks, account) lacks documentation
- "undisclosed_obligation"     — an obligation in a document is absent from stated debts
- "other"                      — ANY OTHER discrepancy, including novel ones no type above
                                 covers (e.g. an ID address that matches the subject
                                 property). For "other" the "description" is REQUIRED and
                                 must clearly state the discrepancy. Never discard a real
                                 discrepancy just because no named type fits — use "other".

GRANULARITY (so the count is stable run to run):
- Report each DISTINCT discrepancy exactly ONCE.
- Do NOT split a single issue into multiple findings (e.g. one income variance is ONE
  finding, not separate pay-stub / W-2 / YTD findings for the same income).
- Do NOT merge two genuinely different issues into one finding.
- Prefer a canonical type above; fall back to "other" (with a description) otherwise.

Return ONLY a JSON object of this exact shape (no prose outside the JSON):
{
  "findings": [
    {
      "type": "<one of the fixed types above, or \\"other\\">",
      "category": "income" | "assets" | "credit" | "property" | "cross_source",
      "severity": "red" | "yellow",
      "description": "<one-line human summary; REQUIRED for the \\"other\\" type>",
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
        # Discrepancy detection is a judgement task, not creative writing — run it
        # deterministically so the SAME file yields the SAME findings run to run.
        temperature=0.0,
    )
    # Truncation guard: a response cut at max_tokens leaves the JSON unbalanced, so
    # the parser would drop ALL findings — surface that loudly, never silently.
    if result.stop_reason == "max_tokens":
        logger.warning(
            "cross_source_response_truncated",  # the body was cut off (raise _MAX_TOKENS)
            output_tokens=result.output_tokens,
            max_tokens=_MAX_TOKENS,
        )
    findings = _parse_findings(result.text)
    logger.info(
        "cross_source_reasoning_done",
        findings=len(findings),  # count only — never the findings' content (PII)
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        stop_reason=result.stop_reason,
    )
    return CrossSourceResult(
        findings=findings,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        model=result.model,
    )


def _parse_findings(text: str) -> list[CrossSourceRawFinding]:
    """Defensively parse the AI response into structured findings (never raises).

    Logs (counts only, never content) whenever the response can't be parsed or
    individual entries are dropped — so silent losses are observable rather than
    hidden behind an empty/short list.
    """
    snippet = extract_json_object(text)
    if snippet is None:
        logger.warning("cross_source_parse_no_json_object")  # no balanced {...} — likely truncated
        return []
    try:
        payload = json.loads(snippet)
    except (json.JSONDecodeError, ValueError):
        logger.warning("cross_source_parse_invalid_json")
        return []
    raw_list = payload.get("findings") if isinstance(payload, dict) else None
    if not isinstance(raw_list, list):
        logger.warning("cross_source_parse_no_findings_list")
        return []
    parsed = [f for item in raw_list if (f := _coerce_finding(item)) is not None]
    if len(parsed) != len(raw_list):
        logger.warning(
            "cross_source_findings_dropped",  # malformed entries the model returned
            raw=len(raw_list),
            parsed=len(parsed),
        )
    return parsed


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
