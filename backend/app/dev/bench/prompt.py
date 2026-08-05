"""Bench PII-placeholder prompt + throttle detection — kept SEPARATE from production, applied at RUNTIME.

⚠️ Production must be provably untouched. So this does NOT edit any file in
``app/ai/prompts/extraction/`` and does NOT add a flag to a production prompt. Instead:

* the extra instruction lives in its OWN file (``bench_pii_instruction.txt``, next to this
  module — never under the production prompt tree), and
* it is APPENDED to the extraction system prompt at call time by a scoped monkeypatch of the
  shared extraction call site (``model_call.complete`` — every extractor funnels through
  ``run_extraction_completion`` → ``_attempt`` → ``complete``). The patch lives only inside a
  ``with bench_pii_prompt():`` / ``with bench_run_context():`` block in the dev bench process; production
  never enters it.

The same runtime patch is where the bench observes **throttling**. When ``complete()`` exhausts its
transient-retry budget it raises ``AIClientError`` and BOTH call sites swallow it into a generic
"AI call failed" sentinel (``_attempt`` → ``None``; classification → ``unknown``), losing the fact that
it was a rate-limit rather than a bad document. So the bench wrapper inspects the exception's cause and,
if it is transient (429 / Bedrock throttle / capacity / 5xx / timeout), records it in a run-scoped tally
BEFORE re-raising — so the bench can tag those documents ``rate_limited`` and never mistake a throttle
for a coverage gap. ``bench_run_context`` also patches ``classification.complete`` so throttling on the
per-document classification call (not just extraction) is seen too.

A test (``test_extraction_bench.py``) asserts the production prompt files are byte-unchanged and that no
production module imports this one — so the separation is enforced, not just intended.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from app.ai.client import AIClientError, AICompletion, _is_transient

_INSTRUCTION_PATH = Path(__file__).with_name("bench_pii_instruction.txt")


@lru_cache(maxsize=1)
def bench_pii_instruction() -> str:
    """The dev-only PII-placeholder instruction appended to the extraction prompt."""
    return _INSTRUCTION_PATH.read_text(encoding="utf-8")


@dataclass
class CallTally:
    """Run-scoped throttle bookkeeping, populated by the patched ``complete`` (see below).

    ``current_doc_throttled`` is reset by the engine before each document and read after, to tag that
    document's record; ``throttled_calls`` is the cumulative count of throttled model calls in the run.
    """

    current_doc_throttled: bool = False
    throttled_calls: int = 0


# Set by ``bench_run_context``; the patched ``complete`` reads it. A ContextVar (not a global) so it
# propagates through the await chain and cannot bleed between concurrent contexts.
_TALLY: ContextVar[CallTally | None] = ContextVar("bench_call_tally", default=None)


def _record_if_throttled(err: AIClientError) -> None:
    """If ``err`` was caused by a transient failure (throttle/capacity/5xx/timeout) — i.e. an
    INFRASTRUCTURE failure, not a bad document — mark the current document and bump the run tally."""
    cause = err.__cause__
    if cause is not None and isinstance(cause, Exception) and _is_transient(cause):
        tally = _TALLY.get()
        if tally is not None:
            tally.current_doc_throttled = True
            tally.throttled_calls += 1


def _patched_complete(real: Any, suffix: str) -> Any:
    """Wrap ``complete``: append ``suffix`` to the system prompt (may be empty) and observe throttling.
    Always re-raises — production's swallow-into-sentinel behaviour is unchanged; the bench only watches."""

    async def _patched(*, system: str, **kwargs: Any) -> AICompletion:
        try:
            return cast(AICompletion, await real(system=system + suffix, **kwargs))
        except AIClientError as err:
            _record_if_throttled(err)
            raise

    return _patched


@contextmanager
def bench_pii_prompt() -> Iterator[None]:
    """Within this block, every EXTRACTION model call gets the PII-placeholder instruction appended to
    its system prompt (and throttling is observed if a tally is active). Scoped: installed on entry,
    removed on exit — it touches only the bench run, never production."""
    import app.ai.extraction.model_call as model_call

    real_complete: Any = model_call.complete  # type: ignore[attr-defined]
    suffix = "\n" + bench_pii_instruction()
    with patch.object(model_call, "complete", _patched_complete(real_complete, suffix)):
        yield


@contextmanager
def bench_run_context() -> Iterator[CallTally]:
    """The umbrella context for one document's work: patches BOTH the extraction call site
    (``model_call.complete`` — with the PII suffix) and the classification call site
    (``classification.complete`` — no suffix; its short reasoning is redacted separately) so throttling
    on EITHER model call is seen, and yields the run-scoped :class:`CallTally`.

    Production is untouched: the patches are removed on exit and the tally only observes."""
    import app.ai.classification as classification
    import app.ai.extraction.model_call as model_call

    tally = CallTally()
    token = _TALLY.set(tally)
    real_extract: Any = model_call.complete  # type: ignore[attr-defined]
    real_classify: Any = classification.complete  # type: ignore[attr-defined]
    suffix = "\n" + bench_pii_instruction()
    try:
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(model_call, "complete", _patched_complete(real_extract, suffix))
            )
            stack.enter_context(
                patch.object(classification, "complete", _patched_complete(real_classify, ""))
            )
            yield tally
    finally:
        _TALLY.reset(token)
