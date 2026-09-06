"""Bench runtime context — throttle/failure detection, kept SEPARATE from production.

⚠️ **This context does NOT modify the prompt.** The bench used to append a PII-placeholder instruction
here so extraction returned ``[NAME]``/``[SSN]``/… — that was **removed** (Geet's decision): the
redaction was blanking data the comparison needs (employer EINs, business addresses, reference numbers —
not personal PII). The bench now captures **real values**, so the output contains real borrower PII and
must never be committed/shared/moved off the machine.

What remains here is failure observation, which touches nothing about production behaviour: when
``complete()`` exhausts its transient-retry budget it raises ``AIClientError`` and BOTH call sites swallow
it into a generic "AI call failed" sentinel (``_attempt`` → ``None``; classification → ``unknown``),
losing whether it was a rate-limit, an auth error, or a bad document. So the bench wraps the two shared
call sites (``model_call.complete`` for extraction, ``classification.complete``) purely to **inspect the
exception cause and re-raise** — recording, per document, whether a call failed and whether it was a
transient throttle. The system prompt reaching ``complete`` is **byte-unchanged**; production is untouched
(the patches are removed on exit, no file under ``app/ai/`` is edited, and no production module imports
this one — asserted in ``test_extraction_bench.py``).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, cast
from unittest.mock import patch

from app.ai.client import AIClientError, AICompletion, _is_transient, infra_failure_kind


@dataclass
class CallTally:
    """Per-context failure bookkeeping, populated by the patched ``complete`` (see below).

    One tally lives per ``bench_run_context`` — i.e. per document (the engine enters the context inside
    ``run_one``). ``current_doc_failed`` / ``current_doc_throttled`` are read after the block to tag that
    document's record; ``throttled_calls`` counts the throttled model calls WITHIN this document (incl.
    retries). The run-level rollup is the engine's ``progress.rate_limited`` / ``progress.failed``.
    """

    current_doc_failed: bool = False
    current_doc_throttled: bool = False
    #: LP-636 — the ACTUAL infrastructure cause of the last failed call (rate_limited /
    #: connection / server_error / oversized / failed), for the report. Distinct from
    #: ``current_doc_throttled``, which means "re-runnable" and drives resume/abort.
    current_doc_infra_kind: str | None = None
    throttled_calls: int = 0
    last_error_type: str | None = None


# Set by ``bench_run_context``; the patched ``complete`` reads it. A ContextVar (not a global) so it
# propagates through the await chain and cannot bleed between concurrent contexts.
_TALLY: ContextVar[CallTally | None] = ContextVar("bench_call_tally", default=None)


def _record_failure(err: AIClientError) -> None:
    """Record an ``AIClientError`` on the current document. EVERY failure sets ``current_doc_failed`` and
    captures the underlying cause type; a TRANSIENT cause (throttle/capacity/5xx/timeout) additionally sets
    ``current_doc_throttled``. So a non-transient failure — missing/expired AWS credentials, access denied —
    is flagged as a failure but NOT a throttle: that is the auth-vs-throttle distinction the report needs."""
    tally = _TALLY.get()
    if tally is None:
        return
    cause = err.__cause__
    tally.current_doc_failed = True
    if cause is not None:
        tally.last_error_type = type(cause).__name__
    if cause is not None and isinstance(cause, Exception) and _is_transient(cause):
        tally.current_doc_throttled = True
        tally.throttled_calls += 1
    # LP-636 defect 2: record WHICH infrastructure cause it was, not merely that it was transient.
    # ``current_doc_throttled`` above stays as-is because the engine routes resume and abort off
    # it and its meaning there is "re-runnable", which is correct for the whole transient family.
    # But the REPORT called all of them "rate_limited", so a bench run investigating throttling
    # would have shown connection failures and 5xx as throttles — the same mislabel that sent the
    # staging diagnosis to the Bedrock quota, standing in the tool you would reach for to check.
    tally.current_doc_infra_kind = infra_failure_kind(err)


def _patched_complete(real: Any) -> Any:
    """Wrap ``complete`` to OBSERVE failures only — the call is forwarded byte-for-byte (no prompt
    change) and always re-raised, so production's behaviour is unchanged; the bench only watches."""

    async def _patched(**kwargs: Any) -> AICompletion:
        try:
            return cast(AICompletion, await real(**kwargs))
        except AIClientError as err:
            _record_failure(err)
            raise

    return _patched


@contextmanager
def bench_run_context() -> Iterator[CallTally]:
    """The umbrella context for one document's work: wraps BOTH the extraction call site
    (``model_call.complete``) and the classification call site (``classification.complete``) so a failure
    on EITHER model call is observed, and yields the run-scoped :class:`CallTally`.

    It does NOT modify the prompt — the system prompt reaching ``complete`` is byte-unchanged. Production
    is untouched: the patches are removed on exit and the tally only observes."""
    import app.ai.classification as classification
    import app.ai.extraction.model_call as model_call

    tally = CallTally()
    token = _TALLY.set(tally)
    real_extract: Any = model_call.complete  # type: ignore[attr-defined]
    real_classify: Any = classification.complete  # type: ignore[attr-defined]
    try:
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(model_call, "complete", _patched_complete(real_extract))
            )
            stack.enter_context(
                patch.object(classification, "complete", _patched_complete(real_classify))
            )
            yield tally
    finally:
        _TALLY.reset(token)
