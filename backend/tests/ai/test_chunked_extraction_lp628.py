"""LP-628 — page-chunked extraction, for documents whose OUTPUT scales with their content.

LF-AWBB (staging, 2026-08-24) produced ``extraction_truncated_after_retry``: 34,386 input tokens
generated >32,768 output and was STILL mid-document at the retry ceiling. Two thirds of the spend
bought nothing. No fixed ceiling can bound a quantity that grows with transaction count, so the
guard's "retry once, higher" cannot be the answer for this shape of document.

These tests pin the three things that make chunking safe rather than merely smaller:

* the WHOLE document goes to every chunk (context), with only the instruction varying;
* a row is claimed by exactly one chunk via BEGINS, so nothing is double counted and no
  de-duplicator is needed (two real $4.50 charges on one day are indistinguishable from a dup);
* a partial result is NEVER returned — one bad chunk fails the whole extraction.
"""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from app.ai.extraction import bank_statement as bs_module
from app.ai.extraction import chunked as chunked_module
from app.ai.extraction import model_call
from app.ai.extraction.bank_statement import (
    _chunk_instruction,
    _merge_chunk_results,
    _parse_bank_statement_json,
    extract_bank_statement,
)
from app.ai.extraction.chunked import (
    MAX_CHUNKS,
    SINGLE_PAGE_REASON,
    TOO_MANY_CHUNKS_REASON,
    PageRange,
    plan_page_ranges,
    run_chunked_extraction,
)
from app.models.extraction import ExtractionStatus

_PDF = b"%PDF-1.4 fake"


def _resp(text: str, *, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        text=text, input_tokens=100, output_tokens=50, model="m", stop_reason=stop_reason
    )


def _statement_json(
    *,
    transactions: list[dict[str, Any]],
    account: str | None = "****1234",
    total_deposits: str | None = "5000.00",
    confidence: float = 0.9,
) -> str:
    core: dict[str, Any] = {}
    if account is not None:
        core["account_number_masked"] = {"value": account, "page": 1, "snippet": "acct"}
    if total_deposits is not None:
        core["total_deposits"] = {"value": total_deposits, "page": 1, "snippet": "Deposits"}
    return json.dumps(
        {
            "typed_core": core,
            "transactions": transactions,
            "additional_sections": [],
            "confidence": confidence,
            "reasoning": "ok",
        }
    )


def _txn(day: int, amount: str) -> dict[str, Any]:
    return {"date": f"2026-07-{day:02d}", "description": f"txn {day}", "amount": amount}


# --------------------------------------------------------------------------------------------- #
# The page plan
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("pages", "per", "expected"),
    [
        (12, 5, [(1, 5), (6, 10), (11, 12)]),
        (10, 5, [(1, 5), (6, 10)]),  # exact multiple — no empty trailing range
        (1, 5, [(1, 1)]),
        (3, 1, [(1, 1), (2, 2), (3, 3)]),
    ],
    ids=["remainder", "exact-multiple", "single-page", "one-per-chunk"],
)
def test_page_ranges_cover_every_page_exactly_once(
    pages: int, per: int, expected: list[tuple[int, int]]
) -> None:
    """Ranges must TILE the document: no gap (a lost page is lost transactions) and no overlap (an
    overlap is a duplicated transaction, and there is no safe way to de-duplicate afterwards)."""
    ranges = plan_page_ranges(pages, per)

    assert [(r.start, r.end) for r in ranges] == expected
    covered = [page for r in ranges for page in range(r.start, r.end + 1)]
    assert covered == list(range(1, pages + 1)), "pages must tile exactly once"


@pytest.mark.parametrize("per", [0, -1])
def test_a_nonpositive_chunk_size_cannot_produce_an_empty_plan(per: int) -> None:
    """A zero/negative setting must not silently yield NO ranges — that would extract nothing and
    report success. Floored at 1, mirroring `_first_n_pages_sync`'s own defensive floor."""
    ranges = plan_page_ranges(4, per)

    assert len(ranges) == 4


# --------------------------------------------------------------------------------------------- #
# What is sent — whole document, varying instruction, cache breakpoint
# --------------------------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_every_chunk_receives_the_whole_document_and_only_the_instruction_varies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE core design decision. A page SLICE cannot see the account header, the "page 4 of 12"
    footer, or the balance carried in from earlier pages. Sending the whole file to each chunk is
    what keeps a row correct, and identical bytes are also what makes the cache work at all."""
    monkeypatch.setattr(chunked_module, "pdf_page_count", AsyncMock(return_value=6))
    calls: list[dict[str, Any]] = []

    async def _fake(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return _resp(_statement_json(transactions=[]))

    monkeypatch.setattr(model_call, "complete", _fake)

    result = await run_chunked_extraction(
        content=_PDF,
        media_type="application/pdf",
        system="SYSTEM",
        max_tokens=16384,
        log_label="bank_statement",
        instruction_for=_chunk_instruction,
        pages_per_chunk=3,
    )

    assert result.ok and len(result.parts) == 2
    doc_blocks = [c["messages"][0]["content"][0] for c in calls]
    assert doc_blocks[0]["source"]["data"] == doc_blocks[1]["source"]["data"], (
        "identical document bytes per chunk — the premise of both the context and the cache"
    )
    instructions = [c["messages"][0]["content"][1]["text"] for c in calls]
    assert instructions[0] != instructions[1], "only the instruction varies"


@pytest.mark.asyncio
async def test_the_cache_breakpoint_is_on_the_document_not_the_instruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Placement is load-bearing, not cosmetic. Bedrock measures the cache minimum against the
    CUMULATIVE prefix and Haiku 4.5's minimum is 4,096 tokens; our largest extraction system prompt
    is ~3,120, so a marker on the system block alone would cache NOTHING and say nothing about it.
    Marking the document puts system+document behind the breakpoint. And the marker must NOT be on
    the instruction — that block differs per chunk, so caching it would write an entry per chunk
    and read none."""
    monkeypatch.setattr(chunked_module, "pdf_page_count", AsyncMock(return_value=4))
    calls: list[dict[str, Any]] = []

    async def _fake(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return _resp(_statement_json(transactions=[]))

    monkeypatch.setattr(model_call, "complete", _fake)

    await run_chunked_extraction(
        content=_PDF,
        media_type="application/pdf",
        system="SYSTEM",
        max_tokens=16384,
        log_label="bank_statement",
        instruction_for=_chunk_instruction,
        pages_per_chunk=2,
    )

    document, instruction = calls[0]["messages"][0]["content"]
    assert document["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in instruction


def test_the_instruction_claims_a_row_by_where_it_BEGINS() -> None:
    """The word that removes the need for de-duplication. A row straddling a page break belongs to
    exactly one chunk — the one holding its first line."""
    text = _chunk_instruction(PageRange(6, 10), 12)

    assert "BEGINS on pages 6-10" in text
    assert "12 pages" in text
    # Everything else is a whole-document read, or the merge's first-non-null would take a figure
    # that only described one page range.
    assert "describes the whole statement" in text


# --------------------------------------------------------------------------------------------- #
# Refusals — the cases where chunking must NOT be attempted
# --------------------------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_a_non_pdf_is_not_chunked() -> None:
    """An image has no pages to range over. It extracts whole, exactly as today."""
    result = await run_chunked_extraction(
        content=b"\xff\xd8fake",
        media_type="image/jpeg",
        system="S",
        max_tokens=8192,
        log_label="bank_statement",
        instruction_for=_chunk_instruction,
    )

    assert not result.ok and result.failure_reason is not None


@pytest.mark.asyncio
async def test_an_unreadable_page_count_fails_rather_than_assuming_one_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guessing "1 page" on an unreadable PDF would extract the first page of a long statement and
    report SUCCESS — a silently-partial loan file, the exact outcome this ticket exists to prevent."""
    monkeypatch.setattr(chunked_module, "pdf_page_count", AsyncMock(return_value=None))

    result = await run_chunked_extraction(
        content=_PDF,
        media_type="application/pdf",
        system="S",
        max_tokens=8192,
        log_label="bank_statement",
        instruction_for=_chunk_instruction,
    )

    assert not result.ok and "page count" in (result.failure_reason or "")


@pytest.mark.asyncio
async def test_an_absurdly_long_document_is_refused_before_spending_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A document needing more than MAX_CHUNKS parts is not a dense statement, it is the wrong
    document. Fanning out dozens of calls at it would spend real money to produce nonsense."""
    monkeypatch.setattr(
        chunked_module, "pdf_page_count", AsyncMock(return_value=(MAX_CHUNKS + 1) * 5)
    )
    complete = AsyncMock()
    monkeypatch.setattr(model_call, "complete", complete)

    result = await run_chunked_extraction(
        content=_PDF,
        media_type="application/pdf",
        system="S",
        max_tokens=8192,
        log_label="bank_statement",
        instruction_for=_chunk_instruction,
        pages_per_chunk=5,
    )

    assert result.failure_reason == TOO_MANY_CHUNKS_REASON
    complete.assert_not_awaited(), "refused BEFORE the first call — no money spent"


@pytest.mark.asyncio
async def test_a_single_page_document_is_refused_instead_of_re_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One page cannot be split, so the only possible range is the whole document — the same
    request that just truncated twice. Spending a third identical call to rediscover that is pure
    waste, so refuse before making it."""
    monkeypatch.setattr(chunked_module, "pdf_page_count", AsyncMock(return_value=1))
    complete = AsyncMock()
    monkeypatch.setattr(model_call, "complete", complete)

    result = await run_chunked_extraction(
        content=_PDF,
        media_type="application/pdf",
        system="S",
        max_tokens=8192,
        log_label="bank_statement",
        instruction_for=_chunk_instruction,
    )

    assert result.failure_reason == SINGLE_PAGE_REASON
    complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_document_shorter_than_the_chunk_size_is_still_split(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caught by a failing test rather than by review. With pages_per_chunk=5 a 4-page statement
    plans ONE range covering everything — identical request, identical output, identical
    truncation, one more call's cost. A dense short statement is exactly what needs splitting, and
    a page-count threshold would never see it, so the range tightens whenever the plan would not
    split on its own."""
    monkeypatch.setattr(chunked_module, "pdf_page_count", AsyncMock(return_value=4))
    ranges_seen: list[str] = []

    async def _fake(**kwargs: Any) -> SimpleNamespace:
        ranges_seen.append(kwargs["messages"][0]["content"][1]["text"])
        return _resp(_statement_json(transactions=[]))

    monkeypatch.setattr(model_call, "complete", _fake)

    result = await run_chunked_extraction(
        content=_PDF,
        media_type="application/pdf",
        system="S",
        max_tokens=8192,
        log_label="bank_statement",
        instruction_for=_chunk_instruction,
        pages_per_chunk=5,
    )

    assert result.ok and len(result.parts) == 2, "4 pages, chunk size 5 -> still two parts"
    assert "PAGES 1 TO 2" in ranges_seen[0] and "PAGES 3 TO 4" in ranges_seen[1]


@pytest.mark.asyncio
async def test_one_truncated_chunk_fails_the_whole_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """A chunk that overflows its own budget means the page range is too coarse. Reported as
    truncation (not a parse failure) because the fix is a smaller range, and that is only
    discoverable if the two are distinguishable."""
    monkeypatch.setattr(chunked_module, "pdf_page_count", AsyncMock(return_value=4))

    async def _fake(**kwargs: Any) -> SimpleNamespace:
        return _resp(_statement_json(transactions=[]), stop_reason="max_tokens")

    monkeypatch.setattr(model_call, "complete", _fake)

    result = await run_chunked_extraction(
        content=_PDF,
        media_type="application/pdf",
        system="S",
        max_tokens=8192,
        log_label="bank_statement",
        instruction_for=_chunk_instruction,
        pages_per_chunk=2,
    )

    assert not result.ok and result.parts == ()
    assert "truncated" in (result.failure_reason or "")


# --------------------------------------------------------------------------------------------- #
# The merge — the substance of the work
# --------------------------------------------------------------------------------------------- #
def _parsed(text: str) -> Any:
    parsed = _parse_bank_statement_json(text)
    assert parsed is not None
    return parsed


def test_transactions_concatenate_in_page_order() -> None:
    """The one field that accumulates, and the only reason chunking exists."""
    parts = [
        _parsed(_statement_json(transactions=[_txn(1, "10.00"), _txn(2, "20.00")])),
        _parsed(_statement_json(transactions=[_txn(3, "30.00")])),
    ]

    merged = _merge_chunk_results(parts)

    assert merged is not None
    assert [str(t.amount) for t in merged.data.transactions] == ["10.00", "20.00", "30.00"]


def test_a_printed_total_is_taken_once_and_never_summed() -> None:
    """THE correction that reading the prompt forced. `total_deposits` is the statement's OWN
    printed figure ("total deposits for the period", carrying a page + snippet) — not a sum the
    model computed. Every chunk sees the whole document and reads the SAME box, so adding them
    would double the deposits on a two-chunk statement and inflate every reserves calculation
    downstream. First-non-null, exactly like the account number."""
    parts = [
        _parsed(_statement_json(transactions=[_txn(1, "10.00")], total_deposits="5000.00")),
        _parsed(_statement_json(transactions=[_txn(2, "20.00")], total_deposits="5000.00")),
    ]

    merged = _merge_chunk_results(parts)

    assert merged is not None
    assert str(merged.data.total_deposits.value) == "5000.00", "taken once, not 10000.00"


def test_a_header_field_is_taken_from_the_first_chunk_that_states_it() -> None:
    """A chunk may legitimately not report a field. The merge must not lose a value just because
    the first part happened to omit it."""
    parts = [
        _parsed(_statement_json(transactions=[], account=None)),
        _parsed(_statement_json(transactions=[], account="****9876")),
    ]

    merged = _merge_chunk_results(parts)

    assert merged is not None
    assert merged.data.account_number_masked.value == "****9876"


def test_two_chunks_disagreeing_halves_confidence_rather_than_picking_a_winner() -> None:
    """Every chunk read the SAME whole document, so a contradiction is not one chunk misreading a
    page — it means the file is not one statement. That is a fact for a human, not something to
    average away."""
    parts = [
        _parsed(_statement_json(transactions=[], account="****1111", confidence=0.9)),
        _parsed(_statement_json(transactions=[], account="****2222", confidence=0.9)),
    ]

    merged = _merge_chunk_results(parts)

    assert merged is not None
    assert merged.confidence == pytest.approx(0.45)


def test_confidence_is_the_weakest_chunk_not_the_average() -> None:
    """A merged statement is no more trustworthy than its least-certain part."""
    parts = [
        _parsed(_statement_json(transactions=[_txn(1, "1.00")], confidence=0.9)),
        _parsed(_statement_json(transactions=[_txn(2, "2.00")], confidence=0.4)),
    ]

    merged = _merge_chunk_results(parts)

    assert merged is not None and merged.confidence == pytest.approx(0.4)


def test_no_parts_merges_to_nothing() -> None:
    """Guards the caller: an empty run must fail honestly, never produce an empty "success"."""
    assert _merge_chunk_results([]) is None


# --------------------------------------------------------------------------------------------- #
# End to end through the extractor
# --------------------------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_a_persistently_truncated_statement_is_rescued_by_chunking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LF-AWBB's exact shape, end to end: both guarded attempts truncate, then the chunked path
    produces the complete list the ceiling could never hold."""
    monkeypatch.setattr(chunked_module, "pdf_page_count", AsyncMock(return_value=4))
    monkeypatch.setattr(bs_module, "pdf_page_count", AsyncMock(return_value=4))
    seen: list[int] = []

    async def _fake(**kwargs: Any) -> SimpleNamespace:
        seen.append(kwargs["max_tokens"])
        if len(seen) <= 2:  # the guard's first attempt + its high-ceiling retry
            return _resp("{truncated", stop_reason="max_tokens")
        day = len(seen) - 2
        return _resp(_statement_json(transactions=[_txn(day, f"{day}0.00")]))

    monkeypatch.setattr(model_call, "complete", _fake)

    result = await extract_bank_statement(_PDF, "application/pdf")

    assert result.status is not ExtractionStatus.FAILED
    assert [str(t.amount) for t in result.data.transactions] == ["10.00", "20.00"]
    assert result.data.page_count_present.value == 4, "still the DETERMINISTIC count (LP-381)"


@pytest.mark.asyncio
async def test_an_unparseable_chunk_fails_the_extraction_rather_than_storing_a_short_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PARTIAL IS TOTAL. A merged list short by one page range is invisible to a processor and to
    every downstream rule; a failed extraction is visible and falls back to Tier 3."""
    monkeypatch.setattr(chunked_module, "pdf_page_count", AsyncMock(return_value=4))
    monkeypatch.setattr(bs_module, "pdf_page_count", AsyncMock(return_value=4))
    seen: list[int] = []

    async def _fake(**kwargs: Any) -> SimpleNamespace:
        seen.append(kwargs["max_tokens"])
        if len(seen) <= 2:
            return _resp("{truncated", stop_reason="max_tokens")
        if len(seen) == 3:
            return _resp(_statement_json(transactions=[_txn(1, "10.00")]))
        return _resp("not json at all")

    monkeypatch.setattr(model_call, "complete", _fake)

    result = await extract_bank_statement(_PDF, "application/pdf")

    assert result.status is ExtractionStatus.FAILED
    assert result.data.transactions == [], "never a partial list"


@pytest.mark.asyncio
async def test_an_untruncated_statement_never_takes_the_chunked_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cost control: the overwhelming majority of documents never truncate, and their behaviour
    must be byte-for-byte what it is today — one call, no page count, no cache write."""
    monkeypatch.setattr(bs_module, "pdf_page_count", AsyncMock(return_value=2))
    page_count = AsyncMock(return_value=2)
    monkeypatch.setattr(chunked_module, "pdf_page_count", page_count)
    calls = 0

    async def _fake(**kwargs: Any) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return _resp(_statement_json(transactions=[_txn(1, "10.00")]))

    monkeypatch.setattr(model_call, "complete", _fake)

    result = await extract_bank_statement(_PDF, "application/pdf")

    assert calls == 1
    page_count.assert_not_awaited(), "chunking never engaged"
    assert [str(t.amount) for t in result.data.transactions] == ["10.00"]
