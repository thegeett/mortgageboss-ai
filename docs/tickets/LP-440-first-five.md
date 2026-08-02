# LP-440 — the first 5 generated specs, in full

The batch-gate sample (chosen to exercise: flat/no-PII/no-list · a nested list · a count cross-check · PII-heavy · the Custom redactor). Module + prompt + test for each. All ruff/format/mypy-clean; their 40 tests pass. See docs/schema-specs/_REGISTRATION_SNIPPETS.md for their registration snippets.

#### `app/ai/extraction/business_license.py`
```python
"""Business License extraction — GENERATED from a schema spec by the LP-434 generator.

The LP-39a shape: a typed core (each field a ``TypedField`` with source) + a grouped
catch-all (``additional_sections``). Honest nulls, graceful ``.failed()``, and
metadata-only logging — a verbatim mirror of the hand-written flat extractors
(``property_tax_bill`` is the reference).

**GENERATED STARTER — accuracy is UNVALIDATED.** The field set comes from the spec and
the prompt is a scaffold; both need a human pass and Priya's review of real extractions
before they are trusted (guide §11). Structurally correct and mechanically tested is not
the same as tuned.
"""

import json
from datetime import date
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError

from app.ai.client import build_document_message
from app.ai.extraction.model_call import run_extraction_completion
from app.ai.extraction.parsing import (
    CoreSpec,
    coerce_date,
    coerce_str,
    derive_status,
    parse_catch_all,
    parse_typed_core,
)
from app.ai.extraction.shape import CatchAllSection, TypedField
from app.ai.parsing import coerce_confidence, extract_json_object
from app.ai.prompt_loader import load_prompt
from app.models.extraction import ExtractionStatus

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "extraction/business_license.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Bounded fixed-form output → the 4096 scaffold budget (guide §7).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 4096


class BusinessLicenseExtraction(BaseModel):
    """A business license in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    issuing_agency_or_jurisdiction: TypedField[str] = Field(default_factory=TypedField)
    issuer_name: TypedField[str] = Field(default_factory=TypedField)
    license_number: TypedField[str] = Field(default_factory=TypedField)
    license_type_or_class: TypedField[str] = Field(default_factory=TypedField)
    business_legal_name: TypedField[str] = Field(default_factory=TypedField)
    dba_name: TypedField[str] = Field(default_factory=TypedField)
    owner_or_qualifying_individual: TypedField[str] = Field(default_factory=TypedField)
    business_address: TypedField[str] = Field(default_factory=TypedField)
    business_activity_or_trade: TypedField[str] = Field(default_factory=TypedField)
    industry_or_naics_code: TypedField[str] = Field(default_factory=TypedField)
    issue_date: TypedField[date] = Field(default_factory=TypedField)
    expiration_or_renewal_date: TypedField[date] = Field(default_factory=TypedField)
    license_status: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class BusinessLicenseExtractionResult(BaseModel):
    """A business license extraction plus its outcome (mirrors the other extractor results)."""

    data: BusinessLicenseExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "BusinessLicenseExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=BusinessLicenseExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("issuing_agency_or_jurisdiction", coerce_str),
    ("issuer_name", coerce_str),
    ("license_number", coerce_str),
    ("license_type_or_class", coerce_str),
    ("business_legal_name", coerce_str),
    ("dba_name", coerce_str),
    ("owner_or_qualifying_individual", coerce_str),
    ("business_address", coerce_str),
    ("business_activity_or_trade", coerce_str),
    ("industry_or_naics_code", coerce_str),
    ("issue_date", coerce_date),
    ("expiration_or_renewal_date", coerce_date),
    ("license_status", coerce_str),
)


def _parse_business_license_json(text: str) -> BusinessLicenseExtractionResult | None:
    """Defensively parse a model response into a business license result. Never raises."""
    snippet = extract_json_object(text)
    if snippet is None:
        return None
    try:
        payload: Any = json.loads(snippet)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    core_payload, non_null, coercion_lost = parse_typed_core(payload, _CORE_SPEC)
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = BusinessLicenseExtraction.model_validate(
            {**core_payload, "additional_sections": sections}
        )
    except ValidationError:
        return None

    status = derive_status(non_null, coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return BusinessLicenseExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_business_license(
    content: bytes, media_type: str
) -> BusinessLicenseExtractionResult:
    """Extract business license values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return BusinessLicenseExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return BusinessLicenseExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="business_license",
    )
    if call.text is None:
        return BusinessLicenseExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_business_license_json(call.text)
    if result is None:
        logger.warning("business_license_extraction_parse_failed")  # no raw response logged
        return BusinessLicenseExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "business_license_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
```

#### `app/ai/prompts/extraction/business_license.txt`
```
GENERATED STARTER PROMPT (LP-434) — REPLACE WITH / MERGE INTO THE TUNED BUSINESS LICENSE
PROMPT. A scaffold so the module works end-to-end; keep the JSON contract below. The
typed-core field set comes from the schema spec — refine the wording with Priya.
----------------------------------------------------------------------

You are a data extraction assistant for a US residential mortgage loan processor.
You are given a single BUSINESS LICENSE. Read it faithfully and return structured data.

CAPTURE EVERYTHING ON THE DOCUMENT — lose nothing. There are two buckets:

1. TYPED CORE — put these into their named slots:
     issuing_agency_or_jurisdiction  (string)
     issuer_name                     (string)
     license_number                  (string)
     license_type_or_class           (string)
     business_legal_name             (string)
     dba_name                        (string)
     owner_or_qualifying_individual  (string)
     business_address                (string)
     business_activity_or_trade      (string)
     industry_or_naics_code          (string) NAICS/SIC codes may appear; capture them as the activity disambiguator
     issue_date                      (date (YYYY-MM-DD))
     expiration_or_renewal_date      (date (YYYY-MM-DD))
     license_status                  (string)

2. ADDITIONAL SECTIONS — EVERYTHING ELSE, grouped by section (e.g. "Other"). Do not
   force these into the typed core — capture them here so nothing is lost.

FOR EVERY FIELD include WHERE you read it:
  - "page"    (integer)  the 1-based page the value appears on
  - "snippet" (string)   the verbatim text you read the value from

CRITICAL RULES:
  - If a value is NOT present or NOT legible, use null — NEVER guess or invent.
  - Money may include "$"/commas (they will be parsed); dates in any common format.

PER-FIELD CONFIDENCE — in addition to the per-document "confidence" below, return a
"field_confidence" object mapping EACH typed-core field name to your certainty
(a number 0.0-1.0) that THAT field's value is correct. Use null for any field you
cannot assess (absent, illegible, or uncertain). Rate each field independently and
never inflate. Example: "field_confidence": {"<field_a>": 0.95, "<field_b>": 0.7}.

Respond with ONLY a single JSON object, no markdown fences and no prose, exactly:
{
  "typed_core": {
    "issuing_agency_or_jurisdiction": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "issuer_name": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "license_number": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "license_type_or_class": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "business_legal_name": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "dba_name": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "owner_or_qualifying_individual": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "business_address": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "business_activity_or_trade": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "industry_or_naics_code": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "issue_date": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "expiration_or_renewal_date": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "license_status": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>}
  },
  "additional_sections": [
    {"section": "<section name>", "fields": [
      {"label": "<field label>", "value": <string|null>, "page": <int|null>, "snippet": <string|null>}
    ]}
  ],
  "field_confidence": {"<typed_core field name>": <0.0-1.0|null>, "...": <0.0-1.0|null>},
  "confidence": <number 0.0-1.0>,
  "reasoning": "<one short sentence describing the document>"
}
```

#### `tests/ai/test_business_license_extraction.py`
```python
"""Tests for business license extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

Shape/mechanism, not accuracy (guide §10): the typed core is coerced with source, an
all-null core is FAILED, unparseable JSON returns None, and the ``.failed()`` factory
holds. No real samples exist — accuracy is validated as real documents flow through.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.ai.client import AIClientError
from app.ai.extraction import model_call
from app.ai.extraction.business_license import (
    BusinessLicenseExtraction,
    BusinessLicenseExtractionResult,
    _parse_business_license_json,
    extract_business_license,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy business_license"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "issuing_agency_or_jurisdiction": _core("SAMPLE"),
        "issuer_name": _core("SAMPLE"),
        "license_number": _core("SAMPLE"),
        "license_type_or_class": _core("SAMPLE"),
        "business_legal_name": _core("SAMPLE"),
        "dba_name": _core("SAMPLE"),
        "owner_or_qualifying_individual": _core("SAMPLE"),
        "business_address": _core("SAMPLE"),
        "business_activity_or_trade": _core("SAMPLE"),
        "industry_or_naics_code": _core("SAMPLE"),
        "issue_date": _core("2024-01-15"),
        "expiration_or_renewal_date": _core("2024-01-15"),
        "license_status": _core("SAMPLE"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "confidence": 0.9,
    "reasoning": "generated test fixture.",
}
FULL_JSON = json.dumps(FULL_PAYLOAD)


def _mock_complete(
    monkeypatch: pytest.MonkeyPatch, *, text: str | None = None, exc: Exception | None = None
) -> AsyncMock:
    if exc is not None:
        mock = AsyncMock(side_effect=exc)
    else:
        mock = AsyncMock(
            return_value=SimpleNamespace(
                text=text, input_tokens=150, output_tokens=60, model="m", stop_reason="end_turn"
            )
        )
    monkeypatch.setattr(model_call, "complete", mock)
    return mock


def test_typed_core_coerced_with_source() -> None:
    d = _parse_business_license_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.issuing_agency_or_jurisdiction.value == "SAMPLE"
    assert d.issuing_agency_or_jurisdiction.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"issuing_agency_or_jurisdiction": _core(None)}}
    parsed = _parse_business_license_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_business_license_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_business_license(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_business_license(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = BusinessLicenseExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == BusinessLicenseExtraction()
```

#### `app/ai/extraction/statement_of_account.py`
```python
"""Statement Of Account extraction — GENERATED from a schema spec by the LP-434 generator.

The LP-39a shape: a typed core (each field a ``TypedField`` with source) + a grouped
catch-all (``additional_sections``). Honest nulls, graceful ``.failed()``, and
metadata-only logging — a verbatim mirror of the hand-written flat extractors
(``property_tax_bill`` is the reference).

**GENERATED STARTER — accuracy is UNVALIDATED.** The field set comes from the spec and
the prompt is a scaffold; both need a human pass and Priya's review of real extractions
before they are trusted (guide §11). Structurally correct and mechanically tested is not
the same as tuned.
"""

import json
from datetime import date
from decimal import Decimal
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError

from app.ai.client import build_document_message
from app.ai.extraction.model_call import run_extraction_completion
from app.ai.extraction.parsing import (
    CoreSpec,
    coerce_date,
    coerce_decimal,
    coerce_int,
    coerce_str,
    derive_status,
    parse_catch_all,
    parse_typed_core,
)
from app.ai.extraction.shape import CatchAllSection, TypedField
from app.ai.parsing import coerce_confidence, extract_json_object
from app.ai.prompt_loader import load_prompt
from app.models.extraction import ExtractionStatus

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "extraction/statement_of_account.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class StatementOfAccountExtraction(BaseModel):
    """A statement of account in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    issuer_name: TypedField[str] = Field(default_factory=TypedField)
    creditor_or_servicer_name: TypedField[str] = Field(default_factory=TypedField)
    customer_or_debtor_name: TypedField[str] = Field(default_factory=TypedField)
    customer_or_debtor_name_2: TypedField[str] = Field(default_factory=TypedField)
    customer_or_debtor_count: TypedField[int] = Field(default_factory=TypedField)
    account_number_masked: TypedField[str] = Field(default_factory=TypedField)
    account_type: TypedField[str] = Field(default_factory=TypedField)
    statement_date: TypedField[date] = Field(default_factory=TypedField)
    statement_period_start: TypedField[date] = Field(default_factory=TypedField)
    statement_period_end: TypedField[date] = Field(default_factory=TypedField)
    previous_balance: TypedField[Decimal] = Field(default_factory=TypedField)
    current_balance: TypedField[Decimal] = Field(default_factory=TypedField)
    minimum_or_scheduled_payment: TypedField[Decimal] = Field(default_factory=TypedField)
    payment_due_date: TypedField[date] = Field(default_factory=TypedField)
    past_due_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    days_past_due: TypedField[int] = Field(default_factory=TypedField)
    delinquency_or_collection_stage: TypedField[str] = Field(default_factory=TypedField)
    current_account_status: TypedField[str] = Field(default_factory=TypedField)
    credit_limit_or_original_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    payoff_or_settlement_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    payoff_good_through_date: TypedField[date] = Field(default_factory=TypedField)
    property_address: TypedField[str] = Field(default_factory=TypedField)
    loan_number: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class StatementOfAccountExtractionResult(BaseModel):
    """A statement of account extraction plus its outcome (mirrors the other extractor results)."""

    data: StatementOfAccountExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "StatementOfAccountExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=StatementOfAccountExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("issuer_name", coerce_str),
    ("creditor_or_servicer_name", coerce_str),
    ("customer_or_debtor_name", coerce_str),
    ("customer_or_debtor_name_2", coerce_str),
    ("customer_or_debtor_count", coerce_int),
    ("account_number_masked", coerce_str),
    ("account_type", coerce_str),
    ("statement_date", coerce_date),
    ("statement_period_start", coerce_date),
    ("statement_period_end", coerce_date),
    ("previous_balance", coerce_decimal),
    ("current_balance", coerce_decimal),
    ("minimum_or_scheduled_payment", coerce_decimal),
    ("payment_due_date", coerce_date),
    ("past_due_amount", coerce_decimal),
    ("days_past_due", coerce_int),
    ("delinquency_or_collection_stage", coerce_str),
    ("current_account_status", coerce_str),
    ("credit_limit_or_original_amount", coerce_decimal),
    ("payoff_or_settlement_amount", coerce_decimal),
    ("payoff_good_through_date", coerce_date),
    ("property_address", coerce_str),
    ("loan_number", coerce_str),
)


def _parse_statement_of_account_json(text: str) -> StatementOfAccountExtractionResult | None:
    """Defensively parse a model response into a statement of account result. Never raises."""
    snippet = extract_json_object(text)
    if snippet is None:
        return None
    try:
        payload: Any = json.loads(snippet)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    core_payload, non_null, coercion_lost = parse_typed_core(payload, _CORE_SPEC)
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = StatementOfAccountExtraction.model_validate(
            {**core_payload, "additional_sections": sections}
        )
    except ValidationError:
        return None

    status = derive_status(non_null, coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return StatementOfAccountExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_statement_of_account(
    content: bytes, media_type: str
) -> StatementOfAccountExtractionResult:
    """Extract statement of account values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return StatementOfAccountExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return StatementOfAccountExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="statement_of_account",
    )
    if call.text is None:
        return StatementOfAccountExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_statement_of_account_json(call.text)
    if result is None:
        logger.warning("statement_of_account_extraction_parse_failed")  # no raw response logged
        return StatementOfAccountExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "statement_of_account_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
```

#### `app/ai/prompts/extraction/statement_of_account.txt`
```
GENERATED STARTER PROMPT (LP-434) — REPLACE WITH / MERGE INTO THE TUNED STATEMENT OF ACCOUNT
PROMPT. A scaffold so the module works end-to-end; keep the JSON contract below. The
typed-core field set comes from the schema spec — refine the wording with Priya.
----------------------------------------------------------------------

You are a data extraction assistant for a US residential mortgage loan processor.
You are given a single STATEMENT OF ACCOUNT. Read it faithfully and return structured data.

CAPTURE EVERYTHING ON THE DOCUMENT — lose nothing. There are two buckets:

1. TYPED CORE — put these into their named slots:
     issuer_name                      (string)
     creditor_or_servicer_name        (string)
     customer_or_debtor_name          (string)
     customer_or_debtor_name_2        (string)
     customer_or_debtor_count         (integer)
     account_number_masked            (string)
     account_type                     (string) This is a generic account statement — it may be a mortgage, auto, student, credit-card, or utility account; capture account_type verbatim to disambiguate
     statement_date                   (date (YYYY-MM-DD))
     statement_period_start           (date (YYYY-MM-DD))
     statement_period_end             (date (YYYY-MM-DD))
     previous_balance                 (number)
     current_balance                  (number)
     minimum_or_scheduled_payment     (number) The contractual monthly obligation, not the amount the borrower chose to pay
     payment_due_date                 (date (YYYY-MM-DD))
     past_due_amount                  (number)
     days_past_due                    (integer)
     delinquency_or_collection_stage  (string)
     current_account_status           (string)
     credit_limit_or_original_amount  (number)
     payoff_or_settlement_amount      (number) Distinguish the statement balance from a payoff/settlement amount (payoff includes accrued interest/fees and has a good-through date)
     payoff_good_through_date         (date (YYYY-MM-DD))
     property_address                 (string)
     loan_number                      (string)

2. ADDITIONAL SECTIONS — EVERYTHING ELSE, grouped by section (e.g. "Other"). Do not
   force these into the typed core — capture them here so nothing is lost.

3. NESTED LISTS — one FLAT ROW per repeating item (bare values + a page/snippet):
     transactions_or_activity — each row: date, description, amount, type, running_balance

FOR EVERY FIELD include WHERE you read it:
  - "page"    (integer)  the 1-based page the value appears on
  - "snippet" (string)   the verbatim text you read the value from

CRITICAL RULES:
  - If a value is NOT present or NOT legible, use null — NEVER guess or invent.
  - Money may include "$"/commas (they will be parsed); dates in any common format.
  - NEVER place an SSN or account number in additional_sections — catch-all values are stored unmasked; keep every identifier in its named typed-core slot.
  - For any masked field, output the LAST 4 CHARACTERS ONLY — never the full value.

PER-FIELD CONFIDENCE — in addition to the per-document "confidence" below, return a
"field_confidence" object mapping EACH typed-core field name to your certainty
(a number 0.0-1.0) that THAT field's value is correct. Use null for any field you
cannot assess (absent, illegible, or uncertain). Rate each field independently and
never inflate. Example: "field_confidence": {"<field_a>": 0.95, "<field_b>": 0.7}.

Respond with ONLY a single JSON object, no markdown fences and no prose, exactly:
{
  "typed_core": {
    "issuer_name": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "creditor_or_servicer_name": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "customer_or_debtor_name": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "customer_or_debtor_name_2": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "customer_or_debtor_count": {"value": <int|null>, "page": <int|null>, "snippet": <string|null>},
    "account_number_masked": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "account_type": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "statement_date": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "statement_period_start": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "statement_period_end": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "previous_balance": {"value": <number|null>, "page": <int|null>, "snippet": <string|null>},
    "current_balance": {"value": <number|null>, "page": <int|null>, "snippet": <string|null>},
    "minimum_or_scheduled_payment": {"value": <number|null>, "page": <int|null>, "snippet": <string|null>},
    "payment_due_date": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "past_due_amount": {"value": <number|null>, "page": <int|null>, "snippet": <string|null>},
    "days_past_due": {"value": <int|null>, "page": <int|null>, "snippet": <string|null>},
    "delinquency_or_collection_stage": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "current_account_status": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "credit_limit_or_original_amount": {"value": <number|null>, "page": <int|null>, "snippet": <string|null>},
    "payoff_or_settlement_amount": {"value": <number|null>, "page": <int|null>, "snippet": <string|null>},
    "payoff_good_through_date": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "property_address": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "loan_number": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>}
  },
  "additional_sections": [
    {"section": "<section name>", "fields": [
      {"label": "<field label>", "value": <string|null>, "page": <int|null>, "snippet": <string|null>}
    ]}
  ],
  "transactions_or_activity": [{"date": <string|null>, "description": <string|null>, "amount": <number|null>, "type": <string|null>, "running_balance": <number|null>, "page": <int|null>, "snippet": <string|null>}],
  "field_confidence": {"<typed_core field name>": <0.0-1.0|null>, "...": <0.0-1.0|null>},
  "confidence": <number 0.0-1.0>,
  "reasoning": "<one short sentence describing the document>"
}
```

#### `tests/ai/test_statement_of_account_extraction.py`
```python
"""Tests for statement of account extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

Shape/mechanism, not accuracy (guide §10): the typed core is coerced with source, an
all-null core is FAILED, unparseable JSON returns None, and the ``.failed()`` factory
holds. No real samples exist — accuracy is validated as real documents flow through.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.ai.client import AIClientError
from app.ai.extraction import model_call
from app.ai.extraction.statement_of_account import (
    StatementOfAccountExtraction,
    StatementOfAccountExtractionResult,
    _parse_statement_of_account_json,
    extract_statement_of_account,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy statement_of_account"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "issuer_name": _core("SAMPLE"),
        "creditor_or_servicer_name": _core("SAMPLE"),
        "customer_or_debtor_name": _core("SAMPLE"),
        "customer_or_debtor_name_2": _core("SAMPLE"),
        "customer_or_debtor_count": _core(2024),
        "account_number_masked": _core("SAMPLE"),
        "account_type": _core("SAMPLE"),
        "statement_date": _core("2024-01-15"),
        "statement_period_start": _core("2024-01-15"),
        "statement_period_end": _core("2024-01-15"),
        "previous_balance": _core("1234.56"),
        "current_balance": _core("1234.56"),
        "minimum_or_scheduled_payment": _core("1234.56"),
        "payment_due_date": _core("2024-01-15"),
        "past_due_amount": _core("1234.56"),
        "days_past_due": _core(2024),
        "delinquency_or_collection_stage": _core("SAMPLE"),
        "current_account_status": _core("SAMPLE"),
        "credit_limit_or_original_amount": _core("1234.56"),
        "payoff_or_settlement_amount": _core("1234.56"),
        "payoff_good_through_date": _core("2024-01-15"),
        "property_address": _core("SAMPLE"),
        "loan_number": _core("SAMPLE"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "confidence": 0.9,
    "reasoning": "generated test fixture.",
}
FULL_JSON = json.dumps(FULL_PAYLOAD)


def _mock_complete(
    monkeypatch: pytest.MonkeyPatch, *, text: str | None = None, exc: Exception | None = None
) -> AsyncMock:
    if exc is not None:
        mock = AsyncMock(side_effect=exc)
    else:
        mock = AsyncMock(
            return_value=SimpleNamespace(
                text=text, input_tokens=150, output_tokens=60, model="m", stop_reason="end_turn"
            )
        )
    monkeypatch.setattr(model_call, "complete", mock)
    return mock


def test_typed_core_coerced_with_source() -> None:
    d = _parse_statement_of_account_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.issuer_name.value == "SAMPLE"
    assert d.issuer_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"issuer_name": _core(None)}}
    parsed = _parse_statement_of_account_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_statement_of_account_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_statement_of_account(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_statement_of_account(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = StatementOfAccountExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == StatementOfAccountExtraction()
```

#### `app/ai/extraction/appraisal.py`
```python
"""Appraisal extraction — GENERATED from a schema spec by the LP-434 generator.

The LP-39a shape: a typed core (each field a ``TypedField`` with source) + a grouped
catch-all (``additional_sections``). Honest nulls, graceful ``.failed()``, and
metadata-only logging — a verbatim mirror of the hand-written flat extractors
(``property_tax_bill`` is the reference).

**GENERATED STARTER — accuracy is UNVALIDATED.** The field set comes from the spec and
the prompt is a scaffold; both need a human pass and Priya's review of real extractions
before they are trusted (guide §11). Structurally correct and mechanically tested is not
the same as tuned.
"""

import json
from datetime import date
from decimal import Decimal
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError

from app.ai.client import build_document_message
from app.ai.extraction.model_call import run_extraction_completion
from app.ai.extraction.parsing import (
    CoreSpec,
    coerce_date,
    coerce_decimal,
    coerce_int,
    coerce_str,
    derive_status,
    parse_catch_all,
    parse_typed_core,
)
from app.ai.extraction.shape import CatchAllSection, TypedField
from app.ai.parsing import coerce_confidence, extract_json_object
from app.ai.prompt_loader import load_prompt
from app.models.extraction import ExtractionStatus

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "extraction/appraisal.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class AppraisalExtraction(BaseModel):
    """A appraisal in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    uad_version: TypedField[str] = Field(default_factory=TypedField)
    form_type: TypedField[str] = Field(default_factory=TypedField)
    appraisal_effective_date: TypedField[date] = Field(default_factory=TypedField)
    report_date: TypedField[date] = Field(default_factory=TypedField)
    appraiser_name: TypedField[str] = Field(default_factory=TypedField)
    appraiser_license: TypedField[str] = Field(default_factory=TypedField)
    lender_client_name: TypedField[str] = Field(default_factory=TypedField)
    subject_property_address: TypedField[str] = Field(default_factory=TypedField)
    county: TypedField[str] = Field(default_factory=TypedField)
    legal_description: TypedField[str] = Field(default_factory=TypedField)
    parcel_identification_number: TypedField[str] = Field(default_factory=TypedField)
    property_type: TypedField[str] = Field(default_factory=TypedField)
    number_of_units: TypedField[int] = Field(default_factory=TypedField)
    occupant_status: TypedField[str] = Field(default_factory=TypedField)
    year_built: TypedField[int] = Field(default_factory=TypedField)
    gross_living_area: TypedField[int] = Field(default_factory=TypedField)
    project_name: TypedField[str] = Field(default_factory=TypedField)
    hoa_dues_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    hoa_dues_frequency: TypedField[str] = Field(default_factory=TypedField)
    appraised_value: TypedField[Decimal] = Field(default_factory=TypedField)
    contract_price_stated: TypedField[Decimal] = Field(default_factory=TypedField)
    value_approach_used: TypedField[str] = Field(default_factory=TypedField)
    property_owner_of_record: TypedField[str] = Field(default_factory=TypedField)
    prior_sale_date: TypedField[date] = Field(default_factory=TypedField)
    prior_sale_price: TypedField[Decimal] = Field(default_factory=TypedField)
    condition_rating: TypedField[str] = Field(default_factory=TypedField)
    quality_rating: TypedField[str] = Field(default_factory=TypedField)
    appraisal_completion_condition: TypedField[str] = Field(default_factory=TypedField)
    repairs_required_indicator: TypedField[str] = Field(default_factory=TypedField)
    fha_condition_deficiencies: TypedField[str] = Field(default_factory=TypedField)
    estimated_monthly_market_rent: TypedField[Decimal] = Field(default_factory=TypedField)
    rent_schedule_attached: TypedField[str] = Field(default_factory=TypedField)
    comparable_count: TypedField[int] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class AppraisalExtractionResult(BaseModel):
    """A appraisal extraction plus its outcome (mirrors the other extractor results)."""

    data: AppraisalExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "AppraisalExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=AppraisalExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("uad_version", coerce_str),
    ("form_type", coerce_str),
    ("appraisal_effective_date", coerce_date),
    ("report_date", coerce_date),
    ("appraiser_name", coerce_str),
    ("appraiser_license", coerce_str),
    ("lender_client_name", coerce_str),
    ("subject_property_address", coerce_str),
    ("county", coerce_str),
    ("legal_description", coerce_str),
    ("parcel_identification_number", coerce_str),
    ("property_type", coerce_str),
    ("number_of_units", coerce_int),
    ("occupant_status", coerce_str),
    ("year_built", coerce_int),
    ("gross_living_area", coerce_int),
    ("project_name", coerce_str),
    ("hoa_dues_amount", coerce_decimal),
    ("hoa_dues_frequency", coerce_str),
    ("appraised_value", coerce_decimal),
    ("contract_price_stated", coerce_decimal),
    ("value_approach_used", coerce_str),
    ("property_owner_of_record", coerce_str),
    ("prior_sale_date", coerce_date),
    ("prior_sale_price", coerce_decimal),
    ("condition_rating", coerce_str),
    ("quality_rating", coerce_str),
    ("appraisal_completion_condition", coerce_str),
    ("repairs_required_indicator", coerce_str),
    ("fha_condition_deficiencies", coerce_str),
    ("estimated_monthly_market_rent", coerce_decimal),
    ("rent_schedule_attached", coerce_str),
    ("comparable_count", coerce_int),
)


def _parse_appraisal_json(text: str) -> AppraisalExtractionResult | None:
    """Defensively parse a model response into a appraisal result. Never raises."""
    snippet = extract_json_object(text)
    if snippet is None:
        return None
    try:
        payload: Any = json.loads(snippet)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    core_payload, non_null, coercion_lost = parse_typed_core(payload, _CORE_SPEC)
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = AppraisalExtraction.model_validate({**core_payload, "additional_sections": sections})
    except ValidationError:
        return None

    status = derive_status(non_null, coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return AppraisalExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_appraisal(content: bytes, media_type: str) -> AppraisalExtractionResult:
    """Extract appraisal values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return AppraisalExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return AppraisalExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="appraisal",
    )
    if call.text is None:
        return AppraisalExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_appraisal_json(call.text)
    if result is None:
        logger.warning("appraisal_extraction_parse_failed")  # no raw response logged
        return AppraisalExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "appraisal_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
```

#### `app/ai/prompts/extraction/appraisal.txt`
```
GENERATED STARTER PROMPT (LP-434) — REPLACE WITH / MERGE INTO THE TUNED APPRAISAL
PROMPT. A scaffold so the module works end-to-end; keep the JSON contract below. The
typed-core field set comes from the schema spec — refine the wording with Priya.
----------------------------------------------------------------------

You are a data extraction assistant for a US residential mortgage loan processor.
You are given a single APPRAISAL. Read it faithfully and return structured data.

CAPTURE EVERYTHING ON THE DOCUMENT — lose nothing. There are two buckets:

1. TYPED CORE — put these into their named slots:
     uad_version                     (string) Determine this FIRST — it dictates where every other field lives and which rating vocabulary applies
     form_type                       (string) Determine this second — it changes the layout
     appraisal_effective_date        (date (YYYY-MM-DD)) The EFFECTIVE date (the inspection), not the signature date — PR-6 measures from this
     report_date                     (date (YYYY-MM-DD))
     appraiser_name                  (string)
     appraiser_license               (string)
     lender_client_name              (string)
     subject_property_address        (string)
     county                          (string)
     legal_description               (string)
     parcel_identification_number    (string)
     property_type                   (string)
     number_of_units                 (integer)
     occupant_status                 (string)
     year_built                      (integer)
     gross_living_area               (integer)
     project_name                    (string)
     hoa_dues_amount                 (number)
     hoa_dues_frequency              (string) ALWAYS state monthly vs annual — never assume
     appraised_value                 (number)
     contract_price_stated           (number)
     value_approach_used             (string)
     property_owner_of_record        (string)
     prior_sale_date                 (date (YYYY-MM-DD)) From the subject's transfer-history section, NOT from the comparables
     prior_sale_price                (number)
     condition_rating                (string) The C1-C6 code. If only prose is given ('average'), record the prose and leave the code null — do NOT translate
     quality_rating                  (string)
     appraisal_completion_condition  (string)
     repairs_required_indicator      (string)
     fha_condition_deficiencies      (string)
     estimated_monthly_market_rent   (number)
     rent_schedule_attached          (string)
     comparable_count                (integer) Read the count from the grid header before listing the comps

2. ADDITIONAL SECTIONS — EVERYTHING ELSE, grouped by section (e.g. "Other"). Do not
   force these into the typed core — capture them here so nothing is lost.

3. NESTED LISTS — one FLAT ROW per repeating item (bare values + a page/snippet):
     comparable_sales — each row: comp_number, address, sale_price, sale_date, gross_living_area, distance_from_subject, net_adjustment, adjusted_value
   Read the TOTAL COUNT from the document's summary FIRST, then list every item (a count that disagrees with the rows marks the extraction PARTIAL).

FOR EVERY FIELD include WHERE you read it:
  - "page"    (integer)  the 1-based page the value appears on
  - "snippet" (string)   the verbatim text you read the value from

CRITICAL RULES:
  - If a value is NOT present or NOT legible, use null — NEVER guess or invent.
  - Money may include "$"/commas (they will be parsed); dates in any common format.

PER-FIELD CONFIDENCE — in addition to the per-document "confidence" below, return a
"field_confidence" object mapping EACH typed-core field name to your certainty
(a number 0.0-1.0) that THAT field's value is correct. Use null for any field you
cannot assess (absent, illegible, or uncertain). Rate each field independently and
never inflate. Example: "field_confidence": {"<field_a>": 0.95, "<field_b>": 0.7}.

Respond with ONLY a single JSON object, no markdown fences and no prose, exactly:
{
  "typed_core": {
    "uad_version": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "form_type": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "appraisal_effective_date": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "report_date": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "appraiser_name": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "appraiser_license": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "lender_client_name": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "subject_property_address": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "county": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "legal_description": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "parcel_identification_number": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "property_type": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "number_of_units": {"value": <int|null>, "page": <int|null>, "snippet": <string|null>},
    "occupant_status": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "year_built": {"value": <int|null>, "page": <int|null>, "snippet": <string|null>},
    "gross_living_area": {"value": <int|null>, "page": <int|null>, "snippet": <string|null>},
    "project_name": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "hoa_dues_amount": {"value": <number|null>, "page": <int|null>, "snippet": <string|null>},
    "hoa_dues_frequency": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "appraised_value": {"value": <number|null>, "page": <int|null>, "snippet": <string|null>},
    "contract_price_stated": {"value": <number|null>, "page": <int|null>, "snippet": <string|null>},
    "value_approach_used": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "property_owner_of_record": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "prior_sale_date": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "prior_sale_price": {"value": <number|null>, "page": <int|null>, "snippet": <string|null>},
    "condition_rating": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "quality_rating": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "appraisal_completion_condition": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "repairs_required_indicator": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "fha_condition_deficiencies": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "estimated_monthly_market_rent": {"value": <number|null>, "page": <int|null>, "snippet": <string|null>},
    "rent_schedule_attached": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "comparable_count": {"value": <int|null>, "page": <int|null>, "snippet": <string|null>}
  },
  "additional_sections": [
    {"section": "<section name>", "fields": [
      {"label": "<field label>", "value": <string|null>, "page": <int|null>, "snippet": <string|null>}
    ]}
  ],
  "comparable_sales": [{"comp_number": <int|null>, "address": <string|null>, "sale_price": <number|null>, "sale_date": <string|null>, "gross_living_area": <int|null>, "distance_from_subject": <string|null>, "net_adjustment": <number|null>, "adjusted_value": <number|null>, "page": <int|null>, "snippet": <string|null>}],
  "field_confidence": {"<typed_core field name>": <0.0-1.0|null>, "...": <0.0-1.0|null>},
  "confidence": <number 0.0-1.0>,
  "reasoning": "<one short sentence describing the document>"
}
```

#### `tests/ai/test_appraisal_extraction.py`
```python
"""Tests for appraisal extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

Shape/mechanism, not accuracy (guide §10): the typed core is coerced with source, an
all-null core is FAILED, unparseable JSON returns None, and the ``.failed()`` factory
holds. No real samples exist — accuracy is validated as real documents flow through.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.ai.client import AIClientError
from app.ai.extraction import model_call
from app.ai.extraction.appraisal import (
    AppraisalExtraction,
    AppraisalExtractionResult,
    _parse_appraisal_json,
    extract_appraisal,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy appraisal"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "uad_version": _core("SAMPLE"),
        "form_type": _core("SAMPLE"),
        "appraisal_effective_date": _core("2024-01-15"),
        "report_date": _core("2024-01-15"),
        "appraiser_name": _core("SAMPLE"),
        "appraiser_license": _core("SAMPLE"),
        "lender_client_name": _core("SAMPLE"),
        "subject_property_address": _core("SAMPLE"),
        "county": _core("SAMPLE"),
        "legal_description": _core("SAMPLE"),
        "parcel_identification_number": _core("SAMPLE"),
        "property_type": _core("SAMPLE"),
        "number_of_units": _core(2024),
        "occupant_status": _core("SAMPLE"),
        "year_built": _core(2024),
        "gross_living_area": _core(2024),
        "project_name": _core("SAMPLE"),
        "hoa_dues_amount": _core("1234.56"),
        "hoa_dues_frequency": _core("SAMPLE"),
        "appraised_value": _core("1234.56"),
        "contract_price_stated": _core("1234.56"),
        "value_approach_used": _core("SAMPLE"),
        "property_owner_of_record": _core("SAMPLE"),
        "prior_sale_date": _core("2024-01-15"),
        "prior_sale_price": _core("1234.56"),
        "condition_rating": _core("SAMPLE"),
        "quality_rating": _core("SAMPLE"),
        "appraisal_completion_condition": _core("SAMPLE"),
        "repairs_required_indicator": _core("SAMPLE"),
        "fha_condition_deficiencies": _core("SAMPLE"),
        "estimated_monthly_market_rent": _core("1234.56"),
        "rent_schedule_attached": _core("SAMPLE"),
        "comparable_count": _core(2024),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "confidence": 0.9,
    "reasoning": "generated test fixture.",
}
FULL_JSON = json.dumps(FULL_PAYLOAD)


def _mock_complete(
    monkeypatch: pytest.MonkeyPatch, *, text: str | None = None, exc: Exception | None = None
) -> AsyncMock:
    if exc is not None:
        mock = AsyncMock(side_effect=exc)
    else:
        mock = AsyncMock(
            return_value=SimpleNamespace(
                text=text, input_tokens=150, output_tokens=60, model="m", stop_reason="end_turn"
            )
        )
    monkeypatch.setattr(model_call, "complete", mock)
    return mock


def test_typed_core_coerced_with_source() -> None:
    d = _parse_appraisal_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.uad_version.value == "SAMPLE"
    assert d.uad_version.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"uad_version": _core(None)}}
    parsed = _parse_appraisal_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_appraisal_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_appraisal(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_appraisal(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = AppraisalExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == AppraisalExtraction()
```

#### `app/ai/extraction/work_visa_ead_card.py`
```python
"""Work Visa Ead Card extraction — GENERATED from a schema spec by the LP-434 generator.

The LP-39a shape: a typed core (each field a ``TypedField`` with source) + a grouped
catch-all (``additional_sections``). Honest nulls, graceful ``.failed()``, and
metadata-only logging — a verbatim mirror of the hand-written flat extractors
(``property_tax_bill`` is the reference).

**GENERATED STARTER — accuracy is UNVALIDATED.** The field set comes from the spec and
the prompt is a scaffold; both need a human pass and Priya's review of real extractions
before they are trusted (guide §11). Structurally correct and mechanically tested is not
the same as tuned.
"""

import json
from datetime import date
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError

from app.ai.client import build_document_message
from app.ai.extraction.model_call import run_extraction_completion
from app.ai.extraction.parsing import (
    CoreSpec,
    coerce_date,
    coerce_str,
    derive_status,
    parse_catch_all,
    parse_typed_core,
)
from app.ai.extraction.shape import CatchAllSection, TypedField
from app.ai.parsing import coerce_confidence, extract_json_object
from app.ai.prompt_loader import load_prompt
from app.models.extraction import ExtractionStatus

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "extraction/work_visa_ead_card.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Bounded fixed-form output → the 4096 scaffold budget (guide §7).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 4096


class WorkVisaEadCardExtraction(BaseModel):
    """A work visa ead card in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    document_title: TypedField[str] = Field(default_factory=TypedField)
    immigration_document_type: TypedField[str] = Field(default_factory=TypedField)
    full_name: TypedField[str] = Field(default_factory=TypedField)
    document_or_card_number: TypedField[str] = Field(default_factory=TypedField)
    uscis_or_a_number: TypedField[str] = Field(default_factory=TypedField)
    receipt_number: TypedField[str] = Field(default_factory=TypedField)
    date_of_birth: TypedField[date] = Field(default_factory=TypedField)
    country_of_birth_or_citizenship: TypedField[str] = Field(default_factory=TypedField)
    visa_or_ead_category: TypedField[str] = Field(default_factory=TypedField)
    status_or_class_of_admission: TypedField[str] = Field(default_factory=TypedField)
    valid_from_date: TypedField[date] = Field(default_factory=TypedField)
    expiration_or_admit_until_date: TypedField[date] = Field(default_factory=TypedField)
    employer_or_petitioner_name: TypedField[str] = Field(default_factory=TypedField)
    employer_specific_restriction: TypedField[str] = Field(default_factory=TypedField)
    employment_authorized_indicator: TypedField[str] = Field(default_factory=TypedField)
    automatic_extension_or_receipt_rule: TypedField[str] = Field(default_factory=TypedField)
    passport_number: TypedField[str] = Field(default_factory=TypedField)
    passport_issuing_country: TypedField[str] = Field(default_factory=TypedField)
    visa_number: TypedField[str] = Field(default_factory=TypedField)
    i94_admission_number: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class WorkVisaEadCardExtractionResult(BaseModel):
    """A work visa ead card extraction plus its outcome (mirrors the other extractor results)."""

    data: WorkVisaEadCardExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "WorkVisaEadCardExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=WorkVisaEadCardExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("document_title", coerce_str),
    ("immigration_document_type", coerce_str),
    ("full_name", coerce_str),
    ("document_or_card_number", coerce_str),
    ("uscis_or_a_number", coerce_str),
    ("receipt_number", coerce_str),
    ("date_of_birth", coerce_date),
    ("country_of_birth_or_citizenship", coerce_str),
    ("visa_or_ead_category", coerce_str),
    ("status_or_class_of_admission", coerce_str),
    ("valid_from_date", coerce_date),
    ("expiration_or_admit_until_date", coerce_date),
    ("employer_or_petitioner_name", coerce_str),
    ("employer_specific_restriction", coerce_str),
    ("employment_authorized_indicator", coerce_str),
    ("automatic_extension_or_receipt_rule", coerce_str),
    ("passport_number", coerce_str),
    ("passport_issuing_country", coerce_str),
    ("visa_number", coerce_str),
    ("i94_admission_number", coerce_str),
)


def _parse_work_visa_ead_card_json(text: str) -> WorkVisaEadCardExtractionResult | None:
    """Defensively parse a model response into a work visa ead card result. Never raises."""
    snippet = extract_json_object(text)
    if snippet is None:
        return None
    try:
        payload: Any = json.loads(snippet)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    core_payload, non_null, coercion_lost = parse_typed_core(payload, _CORE_SPEC)
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = WorkVisaEadCardExtraction.model_validate(
            {**core_payload, "additional_sections": sections}
        )
    except ValidationError:
        return None

    status = derive_status(non_null, coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return WorkVisaEadCardExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_work_visa_ead_card(
    content: bytes, media_type: str
) -> WorkVisaEadCardExtractionResult:
    """Extract work visa ead card values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return WorkVisaEadCardExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return WorkVisaEadCardExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="work_visa_ead_card",
    )
    if call.text is None:
        return WorkVisaEadCardExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_work_visa_ead_card_json(call.text)
    if result is None:
        logger.warning("work_visa_ead_card_extraction_parse_failed")  # no raw response logged
        return WorkVisaEadCardExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "work_visa_ead_card_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
```

#### `app/ai/prompts/extraction/work_visa_ead_card.txt`
```
GENERATED STARTER PROMPT (LP-434) — REPLACE WITH / MERGE INTO THE TUNED WORK VISA EAD CARD
PROMPT. A scaffold so the module works end-to-end; keep the JSON contract below. The
typed-core field set comes from the schema spec — refine the wording with Priya.
----------------------------------------------------------------------

You are a data extraction assistant for a US residential mortgage loan processor.
You are given a single WORK VISA EAD CARD. Read it faithfully and return structured data.

CAPTURE EVERYTHING ON THE DOCUMENT — lose nothing. There are two buckets:

1. TYPED CORE — put these into their named slots:
     document_title                       (string)
     immigration_document_type            (string) Card families: EAD (Form I-766), work visa (foil in passport), I-94 admission record, permanent-resident card (I-551) — this field routes the reading
     full_name                            (string)
     document_or_card_number              (string)
     uscis_or_a_number                    (string) A-number appears as 'A#', 'USCIS#', or 'Alien Reg. No.' with 8-9 digits — normalize into this field
     receipt_number                       (string)
     date_of_birth                        (date (YYYY-MM-DD))
     country_of_birth_or_citizenship      (string)
     visa_or_ead_category                 (string) EAD category codes (e.g. C09, A05, C08) live on the front beside 'Category'; capture the code verbatim even when the human label (e.g. 'pending adjustment of status') is absent
     status_or_class_of_admission         (string)
     valid_from_date                      (date (YYYY-MM-DD))
     expiration_or_admit_until_date       (date (YYYY-MM-DD)) 'Duration of Status (D/S)' is a valid admit-until value and must NOT be forced into a date; capture the literal
     employer_or_petitioner_name          (string)
     employer_specific_restriction        (string)
     employment_authorized_indicator      (string)
     automatic_extension_or_receipt_rule  (string)
     passport_number                      (string)
     passport_issuing_country             (string)
     visa_number                          (string)
     i94_admission_number                 (string)

2. ADDITIONAL SECTIONS — EVERYTHING ELSE, grouped by section (e.g. "Other"). Do not
   force these into the typed core — capture them here so nothing is lost.

FOR EVERY FIELD include WHERE you read it:
  - "page"    (integer)  the 1-based page the value appears on
  - "snippet" (string)   the verbatim text you read the value from

CRITICAL RULES:
  - If a value is NOT present or NOT legible, use null — NEVER guess or invent.
  - Money may include "$"/commas (they will be parsed); dates in any common format.
  - NEVER place an SSN or account number in additional_sections — catch-all values are stored unmasked; keep every identifier in its named typed-core slot.
  - For any masked field, output the LAST 4 CHARACTERS ONLY — never the full value.

PER-FIELD CONFIDENCE — in addition to the per-document "confidence" below, return a
"field_confidence" object mapping EACH typed-core field name to your certainty
(a number 0.0-1.0) that THAT field's value is correct. Use null for any field you
cannot assess (absent, illegible, or uncertain). Rate each field independently and
never inflate. Example: "field_confidence": {"<field_a>": 0.95, "<field_b>": 0.7}.

Respond with ONLY a single JSON object, no markdown fences and no prose, exactly:
{
  "typed_core": {
    "document_title": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "immigration_document_type": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "full_name": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "document_or_card_number": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "uscis_or_a_number": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "receipt_number": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "date_of_birth": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "country_of_birth_or_citizenship": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "visa_or_ead_category": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "status_or_class_of_admission": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "valid_from_date": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "expiration_or_admit_until_date": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "employer_or_petitioner_name": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "employer_specific_restriction": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "employment_authorized_indicator": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "automatic_extension_or_receipt_rule": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "passport_number": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "passport_issuing_country": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "visa_number": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "i94_admission_number": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>}
  },
  "additional_sections": [
    {"section": "<section name>", "fields": [
      {"label": "<field label>", "value": <string|null>, "page": <int|null>, "snippet": <string|null>}
    ]}
  ],
  "field_confidence": {"<typed_core field name>": <0.0-1.0|null>, "...": <0.0-1.0|null>},
  "confidence": <number 0.0-1.0>,
  "reasoning": "<one short sentence describing the document>"
}
```

#### `tests/ai/test_work_visa_ead_card_extraction.py`
```python
"""Tests for work visa ead card extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

Shape/mechanism, not accuracy (guide §10): the typed core is coerced with source, an
all-null core is FAILED, unparseable JSON returns None, and the ``.failed()`` factory
holds. No real samples exist — accuracy is validated as real documents flow through.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.ai.client import AIClientError
from app.ai.extraction import model_call
from app.ai.extraction.work_visa_ead_card import (
    WorkVisaEadCardExtraction,
    WorkVisaEadCardExtractionResult,
    _parse_work_visa_ead_card_json,
    extract_work_visa_ead_card,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy work_visa_ead_card"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "document_title": _core("SAMPLE"),
        "immigration_document_type": _core("SAMPLE"),
        "full_name": _core("SAMPLE"),
        "document_or_card_number": _core("SAMPLE"),
        "uscis_or_a_number": _core("SAMPLE"),
        "receipt_number": _core("SAMPLE"),
        "date_of_birth": _core("2024-01-15"),
        "country_of_birth_or_citizenship": _core("SAMPLE"),
        "visa_or_ead_category": _core("SAMPLE"),
        "status_or_class_of_admission": _core("SAMPLE"),
        "valid_from_date": _core("2024-01-15"),
        "expiration_or_admit_until_date": _core("2024-01-15"),
        "employer_or_petitioner_name": _core("SAMPLE"),
        "employer_specific_restriction": _core("SAMPLE"),
        "employment_authorized_indicator": _core("SAMPLE"),
        "automatic_extension_or_receipt_rule": _core("SAMPLE"),
        "passport_number": _core("SAMPLE"),
        "passport_issuing_country": _core("SAMPLE"),
        "visa_number": _core("SAMPLE"),
        "i94_admission_number": _core("SAMPLE"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "confidence": 0.9,
    "reasoning": "generated test fixture.",
}
FULL_JSON = json.dumps(FULL_PAYLOAD)


def _mock_complete(
    monkeypatch: pytest.MonkeyPatch, *, text: str | None = None, exc: Exception | None = None
) -> AsyncMock:
    if exc is not None:
        mock = AsyncMock(side_effect=exc)
    else:
        mock = AsyncMock(
            return_value=SimpleNamespace(
                text=text, input_tokens=150, output_tokens=60, model="m", stop_reason="end_turn"
            )
        )
    monkeypatch.setattr(model_call, "complete", mock)
    return mock


def test_typed_core_coerced_with_source() -> None:
    d = _parse_work_visa_ead_card_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.document_title.value == "SAMPLE"
    assert d.document_title.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"document_title": _core(None)}}
    parsed = _parse_work_visa_ead_card_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_work_visa_ead_card_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_work_visa_ead_card(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_work_visa_ead_card(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = WorkVisaEadCardExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == WorkVisaEadCardExtraction()
```

#### `app/ai/extraction/custom.py`
```python
"""Custom extraction — GENERATED from a schema spec by the LP-434 generator.

The LP-39a shape: a typed core (each field a ``TypedField`` with source) + a grouped
catch-all (``additional_sections``). Honest nulls, graceful ``.failed()``, and
metadata-only logging — a verbatim mirror of the hand-written flat extractors
(``property_tax_bill`` is the reference).

**GENERATED STARTER — accuracy is UNVALIDATED.** The field set comes from the spec and
the prompt is a scaffold; both need a human pass and Priya's review of real extractions
before they are trusted (guide §11). Structurally correct and mechanically tested is not
the same as tuned.
"""

import json
from datetime import date
from decimal import Decimal
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError

from app.ai.client import build_document_message
from app.ai.extraction.model_call import run_extraction_completion
from app.ai.extraction.parsing import (
    CoreSpec,
    coerce_date,
    coerce_decimal,
    coerce_int,
    coerce_str,
    derive_status,
    parse_catch_all,
    parse_typed_core,
)
from app.ai.extraction.shape import CatchAllSection, TypedField
from app.ai.parsing import coerce_confidence, extract_json_object
from app.ai.prompt_loader import load_prompt
from app.models.extraction import ExtractionStatus

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "extraction/custom.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class CustomExtraction(BaseModel):
    """A custom in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    document_title: TypedField[str] = Field(default_factory=TypedField)
    document_subtype: TypedField[str] = Field(default_factory=TypedField)
    issuer_name: TypedField[str] = Field(default_factory=TypedField)
    party_name: TypedField[str] = Field(default_factory=TypedField)
    party_name_2: TypedField[str] = Field(default_factory=TypedField)
    party_count: TypedField[int] = Field(default_factory=TypedField)
    document_issue_date: TypedField[date] = Field(default_factory=TypedField)
    property_address: TypedField[str] = Field(default_factory=TypedField)
    loan_number: TypedField[str] = Field(default_factory=TypedField)
    account_case_reference_number: TypedField[str] = Field(default_factory=TypedField)
    primary_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    current_status: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class CustomExtractionResult(BaseModel):
    """A custom extraction plus its outcome (mirrors the other extractor results)."""

    data: CustomExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "CustomExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=CustomExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("document_title", coerce_str),
    ("document_subtype", coerce_str),
    ("issuer_name", coerce_str),
    ("party_name", coerce_str),
    ("party_name_2", coerce_str),
    ("party_count", coerce_int),
    ("document_issue_date", coerce_date),
    ("property_address", coerce_str),
    ("loan_number", coerce_str),
    ("account_case_reference_number", coerce_str),
    ("primary_amount", coerce_decimal),
    ("current_status", coerce_str),
)


def _parse_custom_json(text: str) -> CustomExtractionResult | None:
    """Defensively parse a model response into a custom result. Never raises."""
    snippet = extract_json_object(text)
    if snippet is None:
        return None
    try:
        payload: Any = json.loads(snippet)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    core_payload, non_null, coercion_lost = parse_typed_core(payload, _CORE_SPEC)
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = CustomExtraction.model_validate({**core_payload, "additional_sections": sections})
    except ValidationError:
        return None

    status = derive_status(non_null, coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return CustomExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_custom(content: bytes, media_type: str) -> CustomExtractionResult:
    """Extract custom values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return CustomExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return CustomExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="custom",
    )
    if call.text is None:
        return CustomExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_custom_json(call.text)
    if result is None:
        logger.warning("custom_extraction_parse_failed")  # no raw response logged
        return CustomExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "custom_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
```

#### `app/ai/prompts/extraction/custom.txt`
```
GENERATED STARTER PROMPT (LP-434) — REPLACE WITH / MERGE INTO THE TUNED CUSTOM
PROMPT. A scaffold so the module works end-to-end; keep the JSON contract below. The
typed-core field set comes from the schema spec — refine the wording with Priya.
----------------------------------------------------------------------

You are a data extraction assistant for a US residential mortgage loan processor.
You are given a single CUSTOM. Read it faithfully and return structured data.

CAPTURE EVERYTHING ON THE DOCUMENT — lose nothing. There are two buckets:

1. TYPED CORE — put these into their named slots:
     document_title                 (string)
     document_subtype               (string)
     issuer_name                    (string)
     party_name                     (string)
     party_name_2                   (string)
     party_count                    (integer)
     document_issue_date            (date (YYYY-MM-DD))
     property_address               (string)
     loan_number                    (string)
     account_case_reference_number  (string)
     primary_amount                 (number)
     current_status                 (string)

2. ADDITIONAL SECTIONS — EVERYTHING ELSE, grouped by section (e.g. "Other"). Do not
   force these into the typed core — capture them here so nothing is lost.

3. NESTED LISTS — one FLAT ROW per repeating item (bare values + a page/snippet):
     unmapped_key_value_pairs — each row: label, value

FOR EVERY FIELD include WHERE you read it:
  - "page"    (integer)  the 1-based page the value appears on
  - "snippet" (string)   the verbatim text you read the value from

CRITICAL RULES:
  - If a value is NOT present or NOT legible, use null — NEVER guess or invent.
  - Money may include "$"/commas (they will be parsed); dates in any common format.

PER-FIELD CONFIDENCE — in addition to the per-document "confidence" below, return a
"field_confidence" object mapping EACH typed-core field name to your certainty
(a number 0.0-1.0) that THAT field's value is correct. Use null for any field you
cannot assess (absent, illegible, or uncertain). Rate each field independently and
never inflate. Example: "field_confidence": {"<field_a>": 0.95, "<field_b>": 0.7}.

Respond with ONLY a single JSON object, no markdown fences and no prose, exactly:
{
  "typed_core": {
    "document_title": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "document_subtype": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "issuer_name": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "party_name": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "party_name_2": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "party_count": {"value": <int|null>, "page": <int|null>, "snippet": <string|null>},
    "document_issue_date": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "property_address": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "loan_number": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "account_case_reference_number": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    "primary_amount": {"value": <number|null>, "page": <int|null>, "snippet": <string|null>},
    "current_status": {"value": <string|null>, "page": <int|null>, "snippet": <string|null>}
  },
  "additional_sections": [
    {"section": "<section name>", "fields": [
      {"label": "<field label>", "value": <string|null>, "page": <int|null>, "snippet": <string|null>}
    ]}
  ],
  "unmapped_key_value_pairs": [{"label": <string|null>, "value": <string|null>, "page": <int|null>, "snippet": <string|null>}],
  "field_confidence": {"<typed_core field name>": <0.0-1.0|null>, "...": <0.0-1.0|null>},
  "confidence": <number 0.0-1.0>,
  "reasoning": "<one short sentence describing the document>"
}
```

#### `tests/ai/test_custom_extraction.py`
```python
"""Tests for custom extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

Shape/mechanism, not accuracy (guide §10): the typed core is coerced with source, an
all-null core is FAILED, unparseable JSON returns None, and the ``.failed()`` factory
holds. No real samples exist — accuracy is validated as real documents flow through.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.ai.client import AIClientError
from app.ai.extraction import model_call
from app.ai.extraction.custom import (
    CustomExtraction,
    CustomExtractionResult,
    _parse_custom_json,
    extract_custom,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy custom"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "document_title": _core("SAMPLE"),
        "document_subtype": _core("SAMPLE"),
        "issuer_name": _core("SAMPLE"),
        "party_name": _core("SAMPLE"),
        "party_name_2": _core("SAMPLE"),
        "party_count": _core(2024),
        "document_issue_date": _core("2024-01-15"),
        "property_address": _core("SAMPLE"),
        "loan_number": _core("SAMPLE"),
        "account_case_reference_number": _core("SAMPLE"),
        "primary_amount": _core("1234.56"),
        "current_status": _core("SAMPLE"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "confidence": 0.9,
    "reasoning": "generated test fixture.",
}
FULL_JSON = json.dumps(FULL_PAYLOAD)


def _mock_complete(
    monkeypatch: pytest.MonkeyPatch, *, text: str | None = None, exc: Exception | None = None
) -> AsyncMock:
    if exc is not None:
        mock = AsyncMock(side_effect=exc)
    else:
        mock = AsyncMock(
            return_value=SimpleNamespace(
                text=text, input_tokens=150, output_tokens=60, model="m", stop_reason="end_turn"
            )
        )
    monkeypatch.setattr(model_call, "complete", mock)
    return mock


def test_typed_core_coerced_with_source() -> None:
    d = _parse_custom_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.document_title.value == "SAMPLE"
    assert d.document_title.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"document_title": _core(None)}}
    parsed = _parse_custom_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_custom_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_custom(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_custom(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = CustomExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == CustomExtraction()
```
