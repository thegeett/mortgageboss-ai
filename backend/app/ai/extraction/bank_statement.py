"""Bank statement extraction (LP-39c) — the hardest of the three Phase 1 types.

A pay stub / W-2 are flat (typed core + catch-all). A bank statement's key content
is a **list of transactions** (often dozens, across multiple pages) plus balances,
so the schema extends the LP-39a shape with a **first-class typed transactions
list** (ADR-061 — transactions live in the extraction JSON as structured rows):

    typed core (account/balance fields) + transactions[] + grouped catch-all

Mirrors the pay stub / W-2 modules and reuses the shared parser
(:mod:`app.ai.extraction.parsing`). Keeps all the shape guarantees: full-document
Opus reading, honest nulls / **no hallucinated transactions**, tolerant coercion
(a single bad field/row → ``None``, never failing the whole extraction), defensive
parsing, graceful failure (never raises), metadata-only logging.

**Hard parts (deliberate):** the transaction table spans pages (Option A — send the
whole document; the per-request page/size/token concern from the LP-37 revision is
most acute here), and a long list = long JSON, so ``max_tokens`` is generous and a
**truncated/malformed** response fails gracefully (``.failed()``), never crashing.

**Account number (ADR-149).** ``account_number_masked`` is captured masked, **never
logged**, and **displayed masked** (last-4) — the LP-39b SSN pattern, generalized.
"""

import datetime
import json
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError

from app.ai.client import build_document_message
from app.ai.extraction.chunked import PageRange, run_chunked_extraction
from app.ai.extraction.model_call import run_extraction_completion
from app.ai.extraction.parsing import (
    CoreSpec,
    coerce_date,
    coerce_decimal,
    coerce_int,
    coerce_str,
    derive_status,
    parse_catch_all,
    parse_flat_rows,
    parse_typed_core,
    source_payload,
)
from app.ai.extraction.shape import CatchAllSection, SourceLocation, TypedField
from app.ai.parsing import coerce_confidence, extract_json_object
from app.ai.prompt_loader import load_prompt
from app.models.extraction import ExtractionStatus
from app.services.pdf_utils import pdf_page_count

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "extraction/bank_statement.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Bank statements can have long, multi-page transaction lists → generous cap so the
# list isn't truncated. LP-461 adds a SECOND nested list (additional_accounts on a combined statement)
# → the sizing rule's ≥2-list tier (16384). A truncated/malformed response still fails gracefully.
_MAX_TOKENS = 16384


class Transaction(BaseModel):
    """One structured transaction row (ADR-061). Money as ``Decimal``, date as ``date``."""

    date: datetime.date | None = None
    description: str | None = None
    amount: Decimal | None = None
    transaction_type: str | None = None  # deposit / withdrawal / fee / interest / ...
    running_balance: Decimal | None = None
    # bug-001 — THE ACH ORIGINATOR, which is what tells two creditors apart.
    #
    # A statement prints "Chase Credit Crd Autopay  PPD ID: 4760039224". The payee name alone cannot
    # separate two debts owed to one institution — a Chase card and a Chase auto loan are both
    # "Chase" — and grouping on the name would merge them into one obligation, UNDERSTATING the
    # debt-to-income ratio, which is the dangerous direction. The originator id is the field that
    # actually distinguishes them, and it was being dropped.
    #
    # On the real file it settled the opposite question: all four Chase payments carry the SAME
    # PPD ID, so what looked like two accounts (two amounts, two days of the month) is one autopay
    # charged twice a month, reported four times.
    originator_id: str | None = None
    source: SourceLocation | None = None


class BankStatementExtraction(BaseModel):
    """A bank statement: typed core + a typed transactions list + grouped catch-all.

    **Typed core** — account/balance fields (identity + assets/reserves + recency),
    each a :class:`TypedField` with source. **V1 starter — refine with Priya; grows
    in Phase 3.** **Transactions** — the decision-relevant list (deposits, ending
    balance, fees) as structured rows. **Catch-all** — everything else.

    ``account_number_masked`` is **sensitive** — never logged; masked in display.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    account_holder_name: TypedField[str] = Field(default_factory=TypedField)
    bank_name: TypedField[str] = Field(default_factory=TypedField)
    account_number_masked: TypedField[str] = Field(default_factory=TypedField)  # SENSITIVE
    account_type: TypedField[str] = Field(default_factory=TypedField)  # checking / savings
    statement_period_start: TypedField[datetime.date] = Field(default_factory=TypedField)
    statement_period_end: TypedField[datetime.date] = Field(default_factory=TypedField)
    beginning_balance: TypedField[Decimal] = Field(default_factory=TypedField)
    # ⚠️ LP-461: on a COMBINED statement (>1 deposit account) this ending_balance is only the FIRST
    # account's — see the additional_accounts note below. A future rule reading it as "the statement
    # balance" would understate a multi-account holder. The proper fix is the accounts[] restructure
    # (LP-461 ADR / future ticket), not this field.
    ending_balance: TypedField[Decimal] = Field(default_factory=TypedField)
    total_deposits: TypedField[Decimal] = Field(default_factory=TypedField)
    total_withdrawals: TypedField[Decimal] = Field(default_factory=TypedField)

    # --- LP-446 diff (002 spec) — the exists_today:false additions ----------- #
    # account_owner_name_2 / account_owner_count unblock AS-6's joint-account blindness (the co-holder gap).
    account_holder_names_raw: TypedField[str] = Field(default_factory=TypedField)
    account_owner_name_2: TypedField[str] = Field(default_factory=TypedField)
    account_owner_count: TypedField[int] = Field(default_factory=TypedField)
    account_holder_address: TypedField[str] = Field(default_factory=TypedField)
    account_status: TypedField[str] = Field(default_factory=TypedField)
    available_balance: TypedField[Decimal] = Field(default_factory=TypedField)
    average_daily_balance: TypedField[Decimal] = Field(default_factory=TypedField)
    nsf_fee_count: TypedField[int] = Field(default_factory=TypedField)
    nsf_fee_total: TypedField[Decimal] = Field(default_factory=TypedField)
    fees_total: TypedField[Decimal] = Field(default_factory=TypedField)
    minimum_balance_requirement: TypedField[Decimal] = Field(default_factory=TypedField)
    holds_or_pledges: TypedField[str] = Field(default_factory=TypedField)
    interest_paid: TypedField[Decimal] = Field(default_factory=TypedField)

    # --- LP-461 diff — verified scalar additions --------------------------- #
    service_fee_waived_indicator: TypedField[str] = Field(default_factory=TypedField)
    fee_waiver_options: TypedField[str] = Field(default_factory=TypedField)

    # --- Transactions (the structurally-new part, ADR-061) ------------------ #
    # ⚠️ LP-461: these are the FIRST account's transactions only. On a combined statement the additional
    # accounts' rows are NOT captured (additional_accounts carries balances, not rows) — so AS-8's chaining
    # and AS-1's deposit sweep see only account 1. The accounts[] restructure (future ticket) is the fix.
    transactions: list[Transaction] = Field(default_factory=list)

    # --- LP-461 diff — additional accounts on a COMBINED statement (bare rows) -------------- #
    # A "combined statement" lists >1 deposit account; the typed core + transactions above capture only
    # the FIRST. This surfaces the OTHERS' existence + balances (reserves) — but NOT their transactions.
    additional_accounts: list[dict[str, Any]] = Field(default_factory=list)

    # --- Page completeness (LP-381, AS-9) ----------------------------------- #
    # page_count_declared: the "of N" the statement PRINTS ("Page 1 of 5") — a MODEL read (null if not printed).
    # page_count_present: the DETERMINISTIC actual page total, set from the PDF post-extraction (NOT the model).
    page_count_declared: TypedField[int] = Field(default_factory=TypedField)
    page_count_present: TypedField[int] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class BankStatementExtractionResult(BaseModel):
    """A bank statement extraction plus its outcome (mirrors the other result types)."""

    data: BankStatementExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    # LP-628 review — the cached halves of the input, carried so the pipeline can price them.
    #
    # ON THIS RESULT TYPE ONLY, deliberately. Prompt caching is used by exactly one path (chunked
    # extraction, which only this extractor takes), so widening the shared `ExtractionResult` Protocol
    # would force 118 extractors to declare a field none of them can ever set. The pipeline reads them
    # with a 0 default for the same reason. If a second extractor starts caching, the Protocol is the
    # right place and this comment is the note saying so.
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @classmethod
    def failed(cls, reason: str) -> "BankStatementExtractionResult":
        """The graceful fallback: empty data, ``FAILED``, zero confidence."""
        return cls(
            data=BankStatementExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


# Typed-core fields + the coercer for each (transactions + everything else handled separately).
_CORE_SPEC: CoreSpec = (
    ("account_holder_name", coerce_str),
    ("bank_name", coerce_str),
    ("account_number_masked", coerce_str),
    ("account_type", coerce_str),
    ("statement_period_start", coerce_date),
    ("statement_period_end", coerce_date),
    ("beginning_balance", coerce_decimal),
    ("ending_balance", coerce_decimal),
    ("total_deposits", coerce_decimal),
    ("total_withdrawals", coerce_decimal),
    # LP-446 diff additions
    ("account_holder_names_raw", coerce_str),
    ("account_owner_name_2", coerce_str),
    ("account_owner_count", coerce_int),
    ("account_holder_address", coerce_str),
    ("account_status", coerce_str),
    ("available_balance", coerce_decimal),
    ("average_daily_balance", coerce_decimal),
    ("nsf_fee_count", coerce_int),
    ("nsf_fee_total", coerce_decimal),
    ("fees_total", coerce_decimal),
    ("minimum_balance_requirement", coerce_decimal),
    ("holds_or_pledges", coerce_str),
    ("interest_paid", coerce_decimal),
    (
        "page_count_declared",
        coerce_int,
    ),  # LP-381 — the printed "of N"; page_count_present is set separately
    # LP-461 diff additions
    ("service_fee_waived_indicator", coerce_str),
    ("fee_waiver_options", coerce_str),
)

# LP-461 — additional deposit accounts on a combined statement (bare rows; balances only, not txns).
_ADDITIONAL_ACCOUNTS_ROW: CoreSpec = (
    ("account_number_masked", coerce_str),
    ("account_type", coerce_str),
    ("beginning_balance", coerce_str),
    ("ending_balance", coerce_str),
)


def _parse_transactions(raw: Any) -> list[dict[str, Any]]:
    """Coerce the transactions list (date/amount/running_balance typed; source kept).

    **No hallucination**: only the rows the model returned are kept. A row's bad
    field → ``None`` (the row is kept), and a fully-empty row is dropped. Non-dict
    entries are skipped. Strings stay as-is.
    """
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row = {
            "date": coerce_date(entry.get("date")),
            "description": coerce_str(entry.get("description")),
            "amount": coerce_decimal(entry.get("amount")),
            "transaction_type": coerce_str(entry.get("transaction_type")),
            "running_balance": coerce_decimal(entry.get("running_balance")),
            "originator_id": coerce_str(entry.get("originator_id")),
            "source": source_payload(entry),
        }
        # Drop a fully-empty row (junk) — keep any row with at least one read value.
        if any(row[k] is not None for k in ("date", "description", "amount", "running_balance")):
            rows.append(row)
    return rows


def _parse_bank_statement_json(text: str) -> BankStatementExtractionResult | None:
    """Defensively parse a model response into the result. Never raises.

    Reads ``typed_core`` + ``transactions`` + ``additional_sections`` via the shared
    helpers. Status is derived from the typed core **and** the transactions (either
    counts as content). A truncated/malformed response → ``None`` (the caller fails
    gracefully). Returns ``None`` only when no JSON object can be parsed.
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

    core_payload, non_null, coercion_lost = parse_typed_core(payload, _CORE_SPEC)
    transactions = _parse_transactions(payload.get("transactions"))
    additional_accounts = parse_flat_rows(
        payload.get("additional_accounts"), _ADDITIONAL_ACCOUNTS_ROW
    )
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = BankStatementExtraction.model_validate(
            {
                **core_payload,
                "transactions": transactions,
                "additional_accounts": additional_accounts,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    # Transactions count as extracted content (a statement may be mostly its list).
    status = derive_status(non_null + len(transactions) + len(additional_accounts), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return BankStatementExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


def _chunk_instruction(page_range: PageRange, page_count: int) -> str:
    """The per-chunk instruction (LP-628). Sits AFTER the cached document block, so it varies
    freely without invalidating the cached prefix.

    Says BEGINS deliberately. A transaction printed across a page break belongs to exactly one
    chunk — the one whose pages contain its first line — which makes double counting impossible
    without needing to identify duplicate rows afterwards (two real $4.50 charges on one day are
    indistinguishable from a duplicate, so no de-duplicator could be trusted here).

    Everything OTHER than transactions stays whole-document. Each chunk sees the entire file, so
    the account header, the printed period totals and the "Page 1 of N" footer are read the same
    way in every chunk; the merge takes the first non-null and cross-checks the rest.
    """
    return (
        f"This document has {page_count} pages. You are extracting it in parts, and this part "
        f"covers PAGES {page_range.start} TO {page_range.end}.\n\n"
        f"For the `transactions` list: include a transaction ONLY if its row BEGINS on pages "
        f"{page_range.start}-{page_range.end}. If a transaction's row starts on an earlier page "
        f"and continues onto page {page_range.start}, it belongs to an earlier part - omit it. "
        f"If a row starts on page {page_range.end} and continues past it, INCLUDE it here, in "
        f"full. Do not repeat transactions from other pages.\n\n"
        f"Every OTHER field - the account holder, account number, statement period, the printed "
        f"balances and period totals, the printed page count - describes the whole statement, "
        f"not this page range. Read them from wherever they appear in the document, exactly as "
        f"you would if you were extracting it in one pass."
    )


def _first_stated(parts: Sequence[BankStatementExtractionResult], field: str) -> tuple[Any, int]:
    """The first non-null value for ``field`` across chunks, plus a count of chunks that stated a
    DIFFERENT one.

    Disagreement is reported rather than resolved. Every chunk read the same whole document, so
    two chunks returning different account numbers does not mean one misread a page — it means
    the file is not one statement. That is a fact for a human, not something to average away.
    """
    chosen: Any = None
    conflicts = 0
    for part in parts:
        value = getattr(part.data, field).value
        if value is None:
            continue
        if chosen is None:
            chosen = value
        elif value != chosen:
            conflicts += 1
    return chosen, conflicts


def _merge_chunk_results(
    parts: Sequence[BankStatementExtractionResult],
) -> BankStatementExtractionResult | None:
    """Merge per-page-range results into the one result that gets persisted (LP-628).

    Two rules, and only two:

    * ``transactions`` CONCATENATE, in page order. This is the only field that accumulates, and
      the only reason chunking exists.
    * Everything else is a WHOLE-DOCUMENT read — first non-null wins, later chunks cross-check.
      This includes the printed period totals: the prompt asks for the statement's own stated
      figures (each carries a ``page`` and ``snippet``), not for a sum the model computed, so a
      chunk reports the same printed total as every other chunk. There is nothing to recompute.

    Confidence is the MINIMUM across chunks, then halved if any chunk contradicted another. The
    merged result is no more trustworthy than its weakest part, and a contradiction is a reason
    for a human to look rather than a number to smooth over.

    Returns ``None`` if ``parts`` is empty (the caller then fails honestly).
    """
    if not parts:
        return None

    merged: dict[str, Any] = {}
    conflicts = 0
    for field, _coerce in _CORE_SPEC:
        value, field_conflicts = _first_stated(parts, field)
        conflicts += field_conflicts
        if value is not None:
            # Keep the whole TypedField (value + source), not just the value, so provenance
            # survives the merge — a finding that cites a page must still be able to.
            for part in parts:
                if getattr(part.data, field).value == value:
                    merged[field] = getattr(part.data, field)
                    break

    transactions = [txn for part in parts for txn in part.data.transactions]

    # Whole-document reads like the typed core: every chunk saw the same combined-statement rows
    # and the same catch-all sections, so concatenating would duplicate them.
    additional_accounts = next(
        (part.data.additional_accounts for part in parts if part.data.additional_accounts), []
    )
    sections = next(
        (part.data.additional_sections for part in parts if part.data.additional_sections), []
    )

    try:
        data = BankStatementExtraction.model_validate(
            {
                **merged,
                "transactions": transactions,
                "additional_accounts": additional_accounts,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    non_null = sum(1 for key, _ in _CORE_SPEC if getattr(data, key).value is not None)
    # COERCION LOSS IS INHERITED FROM THE PARTS, not asserted to be absent. The literal `False` here
    # discarded each chunk's own status: a chunk whose typed core lost a field to coercion is PARTIAL
    # on the whole-document path (the sibling call at `_parse_bank_statement_json` passes the real
    # flag) and merged to SUCCEEDED here. A statement with an unparseable printed balance therefore
    # reported as a clean extraction ONLY when it took the chunked path — the same document, two
    # different stories, decided by a code path the reader cannot see.
    #
    # ANY part being PARTIAL makes the merge PARTIAL: the merged typed core contains that part's
    # fields, so the loss is genuinely present in what is returned.
    coercion_lost = any(part.status is ExtractionStatus.PARTIAL for part in parts)
    status = derive_status(non_null + len(transactions) + len(additional_accounts), coercion_lost)
    confidence = min(part.confidence for part in parts)
    if conflicts:
        confidence = round(confidence / 2, 4)
        logger.warning(
            "bank_statement_chunk_conflict",
            conflicts=conflicts,
            chunks=len(parts),
        )

    reasoning = next((part.reasoning for part in parts if part.reasoning), None)
    result = BankStatementExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )
    result.input_tokens = sum(part.input_tokens or 0 for part in parts) or None
    result.output_tokens = sum(part.output_tokens or 0 for part in parts) or None
    # Summed the same way, and separately: the cached halves are billed at their own rates, so the
    # cost estimate needs them apart rather than folded into the input total.
    result.cache_read_tokens = sum(part.cache_read_tokens for part in parts)
    result.cache_write_tokens = sum(part.cache_write_tokens for part in parts)
    return result


async def _extract_in_chunks(
    content: bytes, media_type: str, system_prompt: str, *, observed_output_tokens: int | None
) -> tuple[BankStatementExtractionResult | None, str | None]:
    """Run the chunked path and merge it — ``(result, failure_reason)``, exactly one of them set.

    Returning the merged result rather than a partial one is the point: on failure the caller falls
    back exactly as it does today.

    THE REASON TRAVELS WITH THE FAILURE. This returned a bare ``None`` for every outcome, so the
    caller had nothing to report and fell back on the ORIGINAL truncation reason — which meant a
    rate-limited chunk was persisted as a CONTENT failure. `document_processing` gates its
    re-runnable branch on `reasoning == INFRA_RATE_LIMITED` (LP-464), so that mislabelling drove the
    matching OPEN need to REJECTED, and REJECTED is not re-matched: the successful re-run could never
    advance it. `TOO_MANY_CHUNKS_REASON`, `SINGLE_PAGE_REASON` and the per-range truncation reason
    were lost the same way — each one describes a different fix, and all three read as "truncated".
    """
    chunked = await run_chunked_extraction(
        content=content,
        media_type=media_type,
        system=system_prompt,
        max_tokens=_MAX_TOKENS,
        log_label="bank_statement",
        instruction_for=_chunk_instruction,
        # What the truncated attempt(s) actually produced, so the plan is sized against the overflow
        # we watched rather than a fixed halving that cannot fit it.
        observed_output_tokens=observed_output_tokens,
    )
    if not chunked.ok:
        return None, chunked.failure_reason

    parsed: list[BankStatementExtractionResult] = []
    for part in chunked.parts:
        if part.text is None:
            return None, "a page chunk returned no content"
        one = _parse_bank_statement_json(part.text)
        if one is None:
            # One unparseable chunk means the merged list would be short by that page range, with
            # nothing to show it. Fail the whole extraction (module docstring: partial is total).
            logger.warning("bank_statement_chunk_parse_failed", chunks=len(chunked.parts))
            return None, "could not parse a page chunk's extraction"
        # THE CALL'S TOKENS ONTO ITS PARSED RESULT, without which `_merge_chunk_results`' summing is
        # dead code: it sums `part.input_tokens` over these PARSED results, and `_parse_bank_statement_
        # _json` has no call to read them from, so every term was None and the merged total was None.
        # The chunked path therefore recorded NO tokens at all — a wider hole than the cache accounting
        # this was found next to, and invisible because a None total simply reads as "not measured".
        one.input_tokens = part.input_tokens
        one.output_tokens = part.output_tokens
        one.cache_read_tokens = part.cache_read_tokens
        one.cache_write_tokens = part.cache_write_tokens
        parsed.append(one)

    return _merge_chunk_results(parsed), None


async def extract_bank_statement(content: bytes, media_type: str) -> BankStatementExtractionResult:
    """Extract a bank statement (incl. its transactions) from bytes. Never raises.

    Mirrors the other extractors: empty/unsupported → ``failed`` without an API
    call; otherwise loads the prompt, sends the full document to the Opus-class
    model, and parses defensively (a truncated long transaction list → ``failed``).
    The bytes/base64, raw response, extracted values, transactions, and the
    **account number** are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return BankStatementExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return BankStatementExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="bank_statement",
    )

    result: BankStatementExtractionResult | None = None
    if call.truncated:
        # LP-628 — the document's OUTPUT is longer than any ceiling we can name, because it scales
        # with transaction count. Both the first attempt and the high-ceiling retry inside
        # `run_extraction_completion` have already been spent proving that. Splitting the WORK by
        # page range is the only thing that bounds the response; raising the ceiling again just
        # moves the cliff. On success this replaces the truncation failure entirely.
        result, chunk_reason = await _extract_in_chunks(
            content, media_type, system_prompt, observed_output_tokens=call.output_tokens
        )
        if result is None:
            # Chunking could not produce a WHOLE result — never a partial extraction (see chunked.py
            # on partial results). THE CHUNKED REASON WINS where there is one: it describes what
            # actually stopped this attempt, and the original truncation reason is by now the least
            # informative fact available. It also carries INFRA_RATE_LIMITED through to the caller's
            # re-runnable branch, which the truncation reason silently converted into a content
            # failure — and a content failure rejects the need permanently.
            return BankStatementExtractionResult.failed(
                chunk_reason or call.failure_reason or "AI call failed"
            )
    elif call.text is None:
        return BankStatementExtractionResult.failed(call.failure_reason or "AI call failed")
    else:
        result = _parse_bank_statement_json(call.text)

    if result is None:
        logger.warning("bank_statement_extraction_parse_failed")  # truncated/malformed
        return BankStatementExtractionResult.failed("could not parse extraction")

    if call.truncated:
        # The chunked merge already summed its own chunks. ADD the truncated attempt(s) rather than
        # overwriting with them: those tokens were genuinely spent before chunking started, and a
        # cost estimate that hides them would understate every document that took this path.
        result.input_tokens = (result.input_tokens or 0) + (call.input_tokens or 0) or None
        result.output_tokens = (result.output_tokens or 0) + (call.output_tokens or 0) or None
        # The truncated attempts were uncached (only the chunked path sends a cache marker), so this
        # ADDS nothing on that side today — written as an addition anyway so it stays correct if the
        # whole-document call ever caches too.
        result.cache_read_tokens += call.cache_read_tokens
        result.cache_write_tokens += call.cache_write_tokens
    else:
        result.input_tokens = call.input_tokens
        result.output_tokens = call.output_tokens
        result.cache_read_tokens = call.cache_read_tokens
        result.cache_write_tokens = call.cache_write_tokens

    # LP-381 (AS-9): page_count_present is the DETERMINISTIC page total — computed from the PDF, never a model
    # read (a model can miscount, and completeness must not be fabricated). Absent for non-PDF statements →
    # AS-9 honestly couldnt_checks. page_count_declared (the printed "of N") is the model's job, above.
    present = (
        await pdf_page_count(content) if media_type.lower().strip() == "application/pdf" else None
    )
    if present is not None:
        result.data.page_count_present = TypedField(value=present)

    # Metadata only: status, confidence, COUNTS — never values/account number/transactions.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "bank_statement_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        transaction_count=len(result.data.transactions),
        additional_accounts=len(result.data.additional_accounts),
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
