"""Tier 3 generic analyzer (LP-66) — "understand anything" for unrecognized docs.

Tier 3 is the long-tail: a document no predefined schema anticipates (a court
order, a trust, an unusual asset statement, a personal-loan agreement, a
handwritten letter). One **flexible** analysis makes any such document *legible*
without a per-type schema — the typed-core + catch-all philosophy at its most
flexible. The output is structured-but-flexible **generic slots** that work for
ANY document:

  * ``document_type_guess`` — the model's best guess at what it is
  * ``key_parties`` — names + roles
  * ``key_dates`` — date + description
  * ``key_amounts`` — value + context
  * ``key_findings`` — things that may affect the loan (obligations, property
    interests, income items, discrepancies) — recorded as :class:`DocumentFinding`\\ s
  * ``summary`` — a short narrative
  * ``full_text`` — the document's text, stored + indexed for search

One mechanism for all Tier 3 docs (no per-type logic). **Sonnet** (it is
*understanding*, not a cheap one-liner — but it is *surfacing for a human*, not
calculation-grade extraction, so accuracy is **moderate-stakes**). Like the other
AI helpers it **never raises**: any failure returns ``None`` and the pipeline still
finalizes the document. Document bytes/base64 and the raw response are never logged.
"""

import json
from decimal import Decimal
from typing import Any

import structlog
from pydantic import BaseModel, Field

from app.ai.client import AIClientError, build_document_message, complete
from app.ai.extraction.parsing import coerce_decimal, coerce_str
from app.ai.parsing import extract_json_object
from app.ai.prompt_loader import load_prompt
from app.core.config import settings

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "analysis/generic_analyzer.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# A generic analysis (incl. the full text for indexing) can be long — budget room.
_MAX_TOKENS = 8192


class AnalyzedParty(BaseModel):
    """A party named in the document (a person/entity + their role)."""

    name: str | None = None
    role: str | None = None


class AnalyzedDate(BaseModel):
    """A date the document references (kept as a free string + what it is)."""

    date: str | None = None
    description: str | None = None


class AnalyzedAmount(BaseModel):
    """A dollar amount the document references + its context."""

    value: Decimal | None = None
    context: str | None = None


class AnalyzedFinding(BaseModel):
    """One thing in the document that may affect the loan → becomes a DocumentFinding."""

    finding_type: str | None = None  # obligation / property_interest / income_related / ...
    description: str | None = None
    amount: Decimal | None = None
    frequency: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class GenericAnalysis(BaseModel):
    """The structured-but-flexible output of the Tier 3 analyzer (generic slots)."""

    document_type_guess: str | None = None
    key_parties: list[AnalyzedParty] = Field(default_factory=list)
    key_dates: list[AnalyzedDate] = Field(default_factory=list)
    key_amounts: list[AnalyzedAmount] = Field(default_factory=list)
    key_findings: list[AnalyzedFinding] = Field(default_factory=list)
    summary: str | None = None
    full_text: str | None = None  # stored + indexed for search


def _parse_party(entry: Any) -> AnalyzedParty | None:
    if not isinstance(entry, dict):
        return None
    party = AnalyzedParty(name=coerce_str(entry.get("name")), role=coerce_str(entry.get("role")))
    return party if (party.name or party.role) else None


def _parse_date(entry: Any) -> AnalyzedDate | None:
    if not isinstance(entry, dict):
        return None
    d = AnalyzedDate(
        date=coerce_str(entry.get("date")), description=coerce_str(entry.get("description"))
    )
    return d if (d.date or d.description) else None


def _parse_amount(entry: Any) -> AnalyzedAmount | None:
    if not isinstance(entry, dict):
        return None
    a = AnalyzedAmount(
        value=coerce_decimal(entry.get("value")), context=coerce_str(entry.get("context"))
    )
    return a if (a.value is not None or a.context) else None


def _parse_finding(entry: Any) -> AnalyzedFinding | None:
    if not isinstance(entry, dict):
        return None
    description = coerce_str(entry.get("description"))
    finding_type = coerce_str(entry.get("finding_type"))
    if not description and not finding_type:
        return None  # an empty finding is noise — drop it
    raw_details = entry.get("details")
    details = raw_details if isinstance(raw_details, dict) else {}
    return AnalyzedFinding(
        finding_type=finding_type,
        description=description,
        amount=coerce_decimal(entry.get("amount")),
        frequency=coerce_str(entry.get("frequency")),
        details=details,
    )


def _parse_list(raw: Any, parse_one: Any) -> list[Any]:
    if not isinstance(raw, list):
        return []
    return [parsed for entry in raw if (parsed := parse_one(entry)) is not None]


def _parse_analysis_json(text: str) -> GenericAnalysis | None:
    """Defensively parse the analyzer response into a :class:`GenericAnalysis`. Never raises.

    Each list is parsed leniently (bad/empty entries dropped); amounts are coerced
    to ``Decimal``; everything is honest-null. Returns ``None`` only when no JSON
    object can be parsed at all.
    """
    snippet = extract_json_object(text)
    if snippet is None:
        return None
    try:
        payload: Any = json.loads(snippet)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    return GenericAnalysis(
        document_type_guess=coerce_str(payload.get("document_type_guess")),
        key_parties=_parse_list(payload.get("key_parties"), _parse_party),
        key_dates=_parse_list(payload.get("key_dates"), _parse_date),
        key_amounts=_parse_list(payload.get("key_amounts"), _parse_amount),
        key_findings=_parse_list(payload.get("key_findings"), _parse_finding),
        summary=coerce_str(payload.get("summary")),
        full_text=coerce_str(payload.get("full_text")),
    )


async def analyze_document(content: bytes, media_type: str) -> GenericAnalysis | None:
    """Generically analyze any document into the structured-but-flexible output. Never raises.

    Empty/unsupported → ``None`` without an API call. Otherwise loads the analyzer
    prompt, sends the full document to the Sonnet-class model (generous budget), and
    parses defensively. Any AI error / unparseable output → ``None`` (the pipeline
    finalizes the document without an analysis). The bytes/base64, raw response, and
    extracted values are never logged — only metadata (counts).
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return None

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return None

    try:
        result = await complete(
            model=settings.anthropic_model_extraction,  # Sonnet — understanding, not a one-liner
            system=system_prompt,
            messages=[message],
            max_tokens=_MAX_TOKENS,
        )
    except AIClientError:
        logger.warning("generic_analysis_ai_failed")  # metadata only — no bytes/content
        return None

    analysis = _parse_analysis_json(result.text)
    if analysis is None:
        logger.warning("generic_analysis_parse_failed")  # truncated/malformed; no raw response
        return None

    # Metadata only: counts — never any extracted value or the full text.
    logger.info(
        "generic_analysis_done",
        parties=len(analysis.key_parties),
        dates=len(analysis.key_dates),
        amounts=len(analysis.key_amounts),
        findings=len(analysis.key_findings),
        has_full_text=analysis.full_text is not None,
    )
    return analysis
