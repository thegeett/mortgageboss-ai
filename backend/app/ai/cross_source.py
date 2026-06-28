"""The AI cross-source capability (LP-78) — one general read-and-compare pass.

This is the **"AI surfaces"** half of the locked two-layer principle (LP-74 built
the deterministic *judge*; this is the *perceiver*). It reads what the borrower
*stated* (the MISMO application) against what the *documents prove* (the verified
extractions) and surfaces **CONFLICTS** — where both sides are present and
disagree — as structured findings.

What it is NOT: it does not flag missing documentation (that is the needs list's
job), it does not compute or judge ratios (DTI/LTV/reserves — the deterministic
calculators' job), and it does not re-label or re-split the same discrepancy run
to run. Canonical types keep labels stable; an open ``other`` type with a required
description **preserves novel discoveries** (the capability stays general — guided,
not limited).

The output is **structured findings only** (typed: type, the two conflicting
values, source document + page + snippet, confidence, reasoning) — never prose the
deterministic layer interprets. This module is the AI boundary — it assembles
nothing and persists nothing. PII flows through the call but is **never logged**
(counts/tokens only).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.ai.client import AIClientError, complete
from app.ai.parsing import coerce_confidence, extract_json_object
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_MAX_TOKENS = 8192

CROSS_SOURCE_SYSTEM_PROMPT = """\
You are reviewing a mortgage loan file for CONFLICTS between what the borrower
STATED (the application / MISMO data) and what the DOCUMENTS prove (verified
extractions from pay stubs, W-2s, bank statements, gift letters, and other
documents).

WHAT TO REPORT — CONFLICTS, NOT ABSENCES:
- Report a discrepancy ONLY when BOTH sides are present and they DISAGREE — a
  stated value and a documented value that conflict.
- Do NOT report "stated X but no document to verify it". Missing documentation is a
  SEPARATE system's job (the needs list), not yours. If the documents needed to
  verify a stated value are absent, report NOTHING about it — there is nothing to
  cross-check.
- Only flag a missing document when its ABSENCE ITSELF conflicts with something that
  IS documented (e.g. a bank statement shows a large deposit with no gift letter,
  while the application claims that money as a gift).

ONE SCOPE PER DISCREPANCY:
- Report each discrepancy ONCE, at the most specific accurate scope.
- Do NOT report the same gap at both an aggregate/file level AND an item level. No
  "the entire file lacks documentation" umbrella alongside per-item findings — keep
  the specific item-level findings and drop the umbrella.
- Do NOT split one issue into several findings; do NOT merge two distinct issues.

NO CALCULATED CONCLUSIONS:
- Do NOT compute or judge ratios or derived metrics — DTI, LTV, reserves, qualifying
  income, or any calculated figure. Those are the deterministic calculators' job.
- Surface DATA discrepancies only, never ratio or metric conclusions. If data that
  feeds a ratio is wrong, report the DATA discrepancy, not the ratio.

TYPES — classify with a canonical type when one fits (use the EXACT string) so the
same kind of discrepancy is labelled the same way every run:
- "income_variance"              — stated income conflicts with the pay stubs / W-2s
- "employer_mismatch"            — stated employer conflicts with the documents
- "gift_discrepancy"             — a stated gift conflicts with the gift letter / deposit
- "co_borrower_discrepancy"      — a co-borrower's stated data conflicts with documents
- "property_address_discrepancy" — the subject-property address conflicts across sources
- "liability_discrepancy"        — a documented debt conflicts with the stated liabilities
- "asset_discrepancy"            — a stated asset conflicts with the documented asset
- "identity_discrepancy"         — identity data (name / SSN / DOB / address) conflicts
- "other"                        — a REAL discrepancy that fits NONE of the above. Give a
                                   specific "description". Use "other" to PRESERVE novel
                                   discoveries (e.g. an ID listing the subject property as
                                   the borrower's own address). NEVER suppress a real
                                   discrepancy for lacking a canonical type — and do NOT
                                   invent a new label for an issue that fits a canonical
                                   type.

You are SURFACING candidates for a human to review — you do not decide. Be honest
about uncertainty in the confidence.

STRICT OUTPUT — return ONLY a JSON ARRAY (no markdown fences, no prose before or
after):
[
  {
    "type": "<a canonical type above, or \\"other\\">",
    "description": "<one-line summary of the conflict>",
    "stated_value": "<what the application stated, or null>",
    "document_value": "<what the documents show, or null>",
    "source_document": "<the document type that evidences this, or null>",
    "page": <page number, or null>,
    "snippet": "<verbatim supporting text from the document, or null>",
    "confidence": <0.0 - 1.0>,
    "reasoning": "<why these two sides conflict>"
  }
]
Every field must be PRESENT (use null where not applicable). An empty array [] is a
VALID, CORRECT answer when the stated data and the documents agree, or when there is
nothing to compare.
"""


@dataclass(frozen=True)
class CrossSourceRawFinding:
    """One structured conflict the AI surfaced (pre-persistence)."""

    type: str
    description: str
    stated_value: str | None
    document_value: str | None
    source_document: str | None
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

    The prompt asks for a bare JSON array; this also tolerates markdown fences,
    surrounding prose, and a ``{"findings": [...]}`` wrapper (resilience). Logs
    (counts only, never content) when the response can't be parsed or individual
    entries are dropped — so silent losses are observable.
    """
    raw_list = _load_findings_list(text)
    if raw_list is None:
        logger.warning("cross_source_parse_no_json_array")  # no parseable array — maybe truncated
        return []
    parsed = [f for item in raw_list if (f := _coerce_finding(item)) is not None]
    if len(parsed) != len(raw_list):
        logger.warning(
            "cross_source_findings_dropped",  # malformed entries the model returned
            raw=len(raw_list),
            parsed=len(parsed),
        )
    return parsed


def _load_findings_list(text: str) -> list[Any] | None:
    """Pull the findings list out of the response (array, fenced, or wrapped)."""
    for candidate in _json_candidates(text):
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            findings = data.get("findings")
            if isinstance(findings, list):
                return findings
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
    obj = extract_json_object(text)  # the {"findings": [...]} fallback shape
    if obj is not None:
        candidates.append(obj)
    return candidates


def _extract_balanced(text: str, opener: str, closer: str) -> str | None:
    """The first balanced ``opener…closer`` span (depth-aware), or ``None``."""
    start = text.find(opener)
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _coerce_finding(item: Any) -> CrossSourceRawFinding | None:
    if not isinstance(item, dict):
        return None
    type_ = item.get("type")
    description = item.get("description")
    if not isinstance(type_, str) or not type_ or not isinstance(description, str):
        return None
    # Accept the canonical field name, falling back to the older key for resilience.
    source_document = item.get("source_document")
    if source_document is None:
        source_document = item.get("source_document_type")
    return CrossSourceRawFinding(
        type=type_,
        description=description,
        stated_value=_opt_str(item.get("stated_value")),
        document_value=_opt_str(item.get("document_value")),
        source_document=_opt_str(source_document),
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
