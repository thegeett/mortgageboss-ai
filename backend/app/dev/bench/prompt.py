"""Bench PII-placeholder prompt — kept SEPARATE from production, applied at RUNTIME only.

⚠️ Production must be provably untouched. So this does NOT edit any file in
``app/ai/prompts/extraction/`` and does NOT add a flag to a production prompt. Instead:

* the extra instruction lives in its OWN file (``bench_pii_instruction.txt``, next to this
  module — never under the production prompt tree), and
* it is APPENDED to the extraction system prompt at call time by a scoped monkeypatch of the
  ONE shared extraction call site (``model_call.complete`` — every extractor funnels through
  ``run_extraction_completion`` → ``_attempt`` → ``complete``). The patch lives only inside a
  ``with bench_pii_prompt():`` block in the dev bench process; production never enters it.

A test (``test_extraction_bench.py``) asserts the production prompt files are byte-unchanged and
that no production module imports this one — so the separation is enforced, not just intended.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from app.ai.client import AICompletion

_INSTRUCTION_PATH = Path(__file__).with_name("bench_pii_instruction.txt")


@lru_cache(maxsize=1)
def bench_pii_instruction() -> str:
    """The dev-only PII-placeholder instruction appended to the extraction prompt."""
    return _INSTRUCTION_PATH.read_text(encoding="utf-8")


@contextmanager
def bench_pii_prompt() -> Iterator[None]:
    """Within this block, every EXTRACTION model call gets the PII-placeholder instruction appended
    to its system prompt. Scoped: the patch is installed on entry and removed on exit, so it touches
    only the bench run — never classification (which calls ``client.complete`` directly, bypassing
    ``model_call``) and never production."""
    import app.ai.extraction.model_call as model_call

    # model_call re-uses client.complete (imported, not re-exported); typed loosely because this is a
    # generic monkeypatch wrapper that just forwards the call with the system prompt extended.
    real_complete: Any = model_call.complete  # type: ignore[attr-defined]
    suffix = "\n" + bench_pii_instruction()

    async def _patched(*, system: str, **kwargs: Any) -> AICompletion:
        return cast(AICompletion, await real_complete(system=system + suffix, **kwargs))

    with patch.object(model_call, "complete", _patched):
        yield
