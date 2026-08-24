"""Page-chunked extraction (LP-628) — for documents whose OUTPUT scales with their content.

The truncation guard in :mod:`app.ai.extraction.model_call` retries a cut-off extraction once at
a higher ceiling. That works when a document is merely denser than its type's budget expected. It
CANNOT work when the output size is a property of the document rather than of our configuration.

A bank statement is the standard case: its extracted output is dominated by the transaction list,
so output grows with transaction count. LF-AWBB (staging, 2026-08-24) proved the failure —
34,386 input tokens produced >32,768 output and was still mid-document at the retry ceiling:

    extraction  16,384 out  stop_reason=max_tokens   (68s, discarded)
    retry       32,768 out  stop_reason=max_tokens   (126s, discarded)
    tier 3 fallback -> needs_review

Two thirds of the spend bought nothing. Raising the ceiling again only moves the cliff: a
statement with twice the transactions fails at any fixed number.

This module splits the WORK by page range instead of raising the ceiling. Each chunk asks for the
transactions of a few pages, so each response is bounded by pages-per-chunk rather than by the
length of the document.

WHAT IS NOT SPLIT IS THE DOCUMENT. Every chunk receives the WHOLE file and is told which pages to
report on. Sending page slices would be marginally cheaper, but a slice cannot see the account
header, the "page 4 of 12" footer, or the running balance carried in from earlier pages — exactly
the context that keeps a transaction row correct. Prompt caching is what makes this affordable:
the document is byte-identical across chunks, so it is written to cache once and read back by
every later chunk (measured: ~52% off the uncached cost of this strategy at 3 chunks, landing
within ~$0.009 of the slice approach for the whole document).

DOUBLE COUNTING is prevented structurally, not by de-duplication. Each chunk is told to report a
transaction only if its row BEGINS within that chunk's pages, so a row straddling a page break is
claimed by exactly one chunk. The alternative — overlapping pages and de-duplicating — needs a
reliable identity for a transaction, and there is none: two genuine $4.50 charges on the same day
with the same description are common, and a de-duplicator that removes one silently deletes money
from a loan file. A rule about where a row STARTS needs no identity at all.

PARTIAL RESULTS ARE NEVER RETURNED. If any chunk fails or truncates, the whole extraction fails
with an honest reason and the caller falls back exactly as it does today. A missing transaction
inside a stored extraction is invisible to a processor and to every downstream rule; a failed
extraction is visible. This follows the same fail-closed principle as LP-375 and LP-622.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import structlog

from app.ai.client import build_document_message
from app.ai.extraction.model_call import ExtractionCall, _attempt, _failure_reason
from app.services.pdf_utils import pdf_page_count

logger = structlog.get_logger(__name__)

_PDF_MEDIA_TYPE = "application/pdf"

#: Pages handed to one chunk. Chosen for ACCURACY, not cost — chunk count is very nearly
#: cost-neutral because every page is sent exactly once either way and only the (small) system
#: prompt repeats: measured on the LF-AWBB statement, 2 chunks cost $0.0464 and 4 cost $0.0533.
#: Five pages keeps a chunk's transaction list comfortably inside its type's own budget while
#: staying large enough that most statements need only one or two chunks.
DEFAULT_PAGES_PER_CHUNK = 5

#: Refuse to chunk beyond this many parts. A document needing more than this is not a dense
#: statement, it is the wrong document (a scanned bundle, a mis-classified package), and fanning
#: out dozens of calls against it would spend real money to produce nonsense. Fail honestly.
MAX_CHUNKS = 12

#: The honest reason when a document would need more than :data:`MAX_CHUNKS`.
TOO_MANY_CHUNKS_REASON = "document too long to extract in page chunks"

#: The honest reason when there is nothing to split. A one-page document that overflows the output
#: ceiling is a genuinely unextractable page, not a chunking problem.
SINGLE_PAGE_REASON = "single-page document - too dense to extract and cannot be split"

#: The honest reason when a range truncated and could not be split any finer.
TRUNCATED_RANGE_REASON = "response truncated - page range too dense to extract in full"

#: How much output we assume is still UNSEEN beyond an observed truncation. The observed figure is a
#: floor, not a measurement: the response stopped at the ceiling with the document unfinished, so the
#: true size is unknown and strictly larger. Sizing the plan against the floor is what produced the
#: two-chunk plan that could not fit — half of "more than 32,768" is still more than 16,384.
_OVERFLOW_HEADROOM = 2

#: How many times one range may be split when it truncates. One level takes a 5-page range to two
#: ~2-page ranges, which is a large step; a second is allowed for a genuinely dense document, and past
#: that the honest answer is that the pages themselves are too dense (the SINGLE_PAGE argument).
MAX_SPLIT_DEPTH = 2


def _minimum_chunks(observed_output_tokens: int | None, max_tokens: int) -> int:
    """How many chunks the plan needs AT LEAST, given output we already watched overflow.

    Two is the floor (a plan that does not split is not a plan), and was previously also the ceiling
    for every document of 10 pages or fewer — `min(per, ceil(n/2))` yields exactly two ranges for every
    page count from 2 to 10 at the default 5. That is the one number that cannot work here: this path
    is only reached AFTER the whole document overflowed the 32,768 retry ceiling, and each chunk runs
    at `max_tokens` (16,384 for a bank statement). Half of more-than-32,768 is more than 16,384, so
    both chunks truncated and the run failed having spent two more full-document calls to learn it.
    """
    if not observed_output_tokens or max_tokens <= 0:
        return 2
    needed = -(-observed_output_tokens * _OVERFLOW_HEADROOM // max_tokens)
    return max(2, needed)


@dataclass(frozen=True)
class PageRange:
    """An inclusive, 1-based page range — the unit of work for one chunk."""

    start: int
    end: int

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.start}-{self.end}"


def _split(page_range: PageRange) -> tuple[PageRange, ...] | None:
    """Halve a range, or ``None`` when it is a single page and cannot be split further."""
    if page_range.start >= page_range.end:
        return None
    midpoint = page_range.start + (page_range.end - page_range.start) // 2
    return (
        PageRange(page_range.start, midpoint),
        PageRange(midpoint + 1, page_range.end),
    )


@dataclass(frozen=True)
class ChunkedExtraction:
    """The outcome of a chunked run.

    ``parts`` holds one :class:`ExtractionCall` per page range, in page order, and is only
    populated when EVERY chunk succeeded — see the module docstring on partial results. When
    ``failure_reason`` is set, ``parts`` is empty and the caller fails as it would have anyway.
    """

    parts: tuple[ExtractionCall, ...]
    page_count: int
    failure_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.failure_reason is None and bool(self.parts)


def plan_page_ranges(page_count: int, pages_per_chunk: int) -> tuple[PageRange, ...]:
    """Split ``page_count`` pages into consecutive inclusive ranges of at most ``pages_per_chunk``.

    Floors ``pages_per_chunk`` at 1 so a non-positive setting cannot produce an empty plan (and
    therefore a silently-skipped document) — the same defensive floor ``_first_n_pages_sync``
    applies to its own cap.
    """
    per = max(1, pages_per_chunk)
    return tuple(
        PageRange(start, min(start + per - 1, page_count))
        for start in range(1, max(1, page_count) + 1, per)
    )


def is_chunkable(media_type: str) -> bool:
    """Only a PDF has pages to range over. Images extract whole, as they do today."""
    return media_type.lower().strip() == _PDF_MEDIA_TYPE


async def run_chunked_extraction(
    *,
    content: bytes,
    media_type: str,
    system: str,
    max_tokens: int,
    log_label: str,
    instruction_for: Callable[[PageRange, int], str],
    pages_per_chunk: int = DEFAULT_PAGES_PER_CHUNK,
    observed_output_tokens: int | None = None,
) -> ChunkedExtraction:
    """Extract ``content`` one page range at a time, sending the WHOLE document to each chunk.

    ``instruction_for(page_range, page_count)`` builds the per-chunk instruction — the only part
    of the request that varies, and deliberately placed AFTER the cached document block so it
    cannot invalidate the cached prefix.

    Never raises. Returns a :class:`ChunkedExtraction` whose ``failure_reason`` is set (and
    ``parts`` empty) if the document cannot be chunked or any single chunk fails.

    Chunks run SEQUENTIALLY, which is required rather than merely simple: a cache entry only
    becomes readable once the first response has begun streaming, so firing every chunk at once
    from cold would have each pay the cache-WRITE premium and read nothing. Running in order also
    keeps the process-local Bedrock rate limiter's pacing meaningful. The cost is wall-clock, and
    it fits: a chunk emits roughly one range's worth of transactions, well under the ~68s the
    whole-document call took, so even ``MAX_CHUNKS`` stays inside the 600s task budget (LP-625).
    """
    if not is_chunkable(media_type):
        return ChunkedExtraction((), 0, "document is not a PDF - cannot extract by page range")

    page_count = await pdf_page_count(content)
    if not page_count or page_count < 1:
        # Unreadable page count is NOT "one page" — guessing would silently extract a fraction of
        # a long statement and report success. Fail and let the caller's existing path handle it.
        return ChunkedExtraction((), 0, "could not determine the document's page count")

    if page_count < 2:
        # A single page cannot be split, so chunking has nothing to offer it — the one range would
        # be the whole document and would truncate exactly as the guarded attempts just did. Fail
        # instead of spending a third identical call to learn that.
        return ChunkedExtraction((), page_count, SINGLE_PAGE_REASON)

    # A document shorter than `pages_per_chunk` would otherwise plan a SINGLE range covering
    # everything — same request, same output, same truncation, one more call's cost. Whenever the
    # natural plan does not split, tighten the range so it does: a dense 4-page statement is
    # exactly the case that needs splitting, and it is invisible to a page-count threshold.
    #
    # SIZED AGAINST THE OVERFLOW WE ACTUALLY SAW, not against a fixed halving — see `_minimum_chunks`
    # for why halving is the one factor guaranteed not to work on the path that reaches here.
    effective_per = min(
        max(1, pages_per_chunk),
        -(-page_count // _minimum_chunks(observed_output_tokens, max_tokens)),
    )

    ranges = plan_page_ranges(page_count, effective_per)
    if len(ranges) > MAX_CHUNKS:
        logger.warning(
            "extraction_chunk_plan_rejected",
            extractor=log_label,
            page_count=page_count,
            would_be_chunks=len(ranges),
            max_chunks=MAX_CHUNKS,
        )
        return ChunkedExtraction((), page_count, TOO_MANY_CHUNKS_REASON)

    logger.info(
        "extraction_chunk_plan",
        extractor=log_label,
        page_count=page_count,
        chunks=len(ranges),
        pages_per_chunk=pages_per_chunk,
    )

    parts: list[ExtractionCall] = []
    # A WORK QUEUE, not a plain loop over the plan, so a range that truncates can be SPLIT and retried
    # rather than failing the run. The `extraction_chunk_truncated` log has always said "the fix is a
    # smaller range"; nothing acted on it, so a plan that came up one step short threw away every
    # chunk that had already succeeded. Halves are pushed to the FRONT, and every range still pending
    # covers later pages, so `parts` stays in page order without a sort.
    pending: list[tuple[PageRange, int]] = [(page_range, 0) for page_range in ranges]
    calls_made = 0
    while pending:
        page_range, depth = pending.pop(0)
        # The same ceiling the plan is checked against, now covering re-splits too: a document that
        # keeps truncating must not fan out indefinitely at a full document's cost per call.
        calls_made += 1
        if calls_made > MAX_CHUNKS:
            logger.warning(
                "extraction_chunk_budget_exhausted",
                extractor=log_label,
                page_count=page_count,
                max_chunks=MAX_CHUNKS,
            )
            return ChunkedExtraction((), page_count, TOO_MANY_CHUNKS_REASON)
        index = calls_made
        try:
            message = build_document_message(
                content=content,
                media_type=media_type,
                instruction=instruction_for(page_range, page_count),
                # The breakpoint that makes whole-document chunking affordable. Identical bytes
                # across every chunk of this document, so chunk 1 writes and the rest read.
                cache=True,
            )
        except ValueError:
            return ChunkedExtraction((), page_count, "unsupported document media type")

        completion, infra_kind = await _attempt(
            system=system,
            message=message,
            max_tokens=max_tokens,
            log_label=log_label,
            # Planned count, not a denominator: a re-split makes the true total larger
            # than the plan, and "chunk 3/2" is more confusing than an open count.
            phase=f"chunk {index} (planned {len(ranges)})",
        )
        if completion is None:
            logger.warning(
                "extraction_chunk_failed",
                extractor=log_label,
                chunk=index,
                planned=len(ranges),
                pages=str(page_range),
                error_kind=infra_kind,
            )
            return ChunkedExtraction((), page_count, _failure_reason(infra_kind))

        if completion.stop_reason == "max_tokens":
            # A single range overflowing its budget means the range is too coarse for this document.
            # SPLIT IT AND RETRY, rather than failing the run: the pages this range covers are dense,
            # which says nothing about the ranges already extracted or still queued. Reported as
            # itself either way — a truncation is not a parse failure, and only a distinguishable log
            # makes the density discoverable.
            halves = _split(page_range) if depth < MAX_SPLIT_DEPTH else None
            logger.warning(
                "extraction_chunk_truncated",
                extractor=log_label,
                chunk=index,
                pages=str(page_range),
                max_tokens=max_tokens,
                depth=depth,
                retrying_as=len(halves) if halves else 0,
            )
            if halves is None:
                # Out of splits, or a single page: the pages themselves are too dense, which is the
                # SINGLE_PAGE argument arriving one level down. Fail honestly and let the caller fall
                # back — never a partial merge (see the module docstring).
                return ChunkedExtraction((), page_count, TRUNCATED_RANGE_REASON)
            pending[0:0] = [(half, depth + 1) for half in halves]
            continue

        parts.append(
            ExtractionCall(
                completion.text,
                completion.input_tokens,
                completion.output_tokens,
                None,
                False,
                # The whole point of the cached prefix: on every chunk after the first, the document
                # is billed here rather than in `input_tokens`. Dropping these made the cheaper
                # strategy look free instead of cheap.
                cache_read_tokens=completion.cache_read_tokens,
                cache_write_tokens=completion.cache_write_tokens,
            )
        )

    logger.info(
        "extraction_chunked_done",
        extractor=log_label,
        page_count=page_count,
        chunks=len(parts),
        output_tokens=sum(p.output_tokens or 0 for p in parts),
    )
    return ChunkedExtraction(tuple(parts), page_count)
