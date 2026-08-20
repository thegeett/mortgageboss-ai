"""LP-597 — the composer stops inventing a corpus, and a rejection stops being terminal.

TWO REAL FINDINGS FROM ONE RUN, on a loan file with ZERO documents uploaded:

  IN-2  "The file contains pay stubs, but none of them display a pay date."   <- there are none
  OC-1  "The stated occupancy is consistent across all loan documents."        <- there are none

Neither template says that. IN-2's spec has no couldnt_check branch at all (the engine's generic
"could not be determined" text was what the model was handed), and OC-1's says "agrees with the file's
other occupancy DECLARATIONS" — the 1003's own fields. The model turned an absence into a corpus, in
both cases to make the sentence read concretely.

The prompt already forbade this ("Use ONLY facts present in the summary. Never introduce a ... document
name"). It could not be obeyed: nothing in the summary said what the file contains. That is the gap.
"""

from __future__ import annotations

import json

import pytest
from app.ai.finding_prose import (
    _REJECTION_GUIDANCE,
    _RETRYABLE,
    Composition,
    FactSummary,
    compose,
)

pytestmark = pytest.mark.anyio


def _summary(**kw: object) -> FactSummary:
    base = {
        "rule_name": "IN-2",
        "subject": "the loan",
        "problem": "x could not be determined",
        "fix": None,
    }
    return FactSummary(**{**base, **kw})  # type: ignore[arg-type]


def test_zero_documents_survives_the_payload_filter() -> None:
    """THE BUG THIS FIX ALMOST SHIPPED WITH. `to_json` drops falsy values, and `documents_on_file: 0`
    is the single most load-bearing value the summary carries — zero documents is precisely when the
    model invents. Filtering it out would have made the whole ticket inert."""
    payload = json.loads(_summary(documents_on_file=0).to_json())

    assert payload["documents_on_file"] == 0


def test_a_real_count_is_carried_too() -> None:
    payload = json.loads(_summary(documents_on_file=7).to_json())

    assert payload["documents_on_file"] == 7


def test_the_prompt_forbids_asserting_a_document_is_present() -> None:
    """A prompt instruction is a hope, not a guarantee — but the hope has to exist and be specific.
    Pinned so a future prompt edit cannot quietly drop it."""
    from app.ai.finding_prose import SYSTEM_PROMPT

    assert "NEVER ASSERT THAT A DOCUMENT IS IN THE FILE" in SYSTEM_PROMPT
    assert "documents_on_file" in SYSTEM_PROMPT
    # The two sentences that actually shipped, named so the rule is anchored to the real failures.
    assert "the file contains pay stubs" in SYSTEM_PROMPT
    assert "consistent across all loan documents" in SYSTEM_PROMPT


# --------------------------------------------------------------------------- #
# The retry — a rejected composition means the finding ships raw template text
# --------------------------------------------------------------------------- #


class _Model:
    """Replays scripted completions and records each user message it was sent."""

    def __init__(self, *texts: str) -> None:
        self.texts, self.messages = list(texts), []

    async def __call__(self, **kw: object) -> object:
        self.messages.append(kw["messages"][0]["content"])  # type: ignore[index]

        class _R:
            stop_reason = "end_turn"
            output_tokens = 10
            text = self.texts[min(len(self.messages) - 1, len(self.texts) - 1)]

        return _R()


async def test_an_invented_number_is_retried_and_the_second_answer_stands(monkeypatch) -> None:
    """The first draft invents $9,999; the second obeys. Before this, the finding shipped the raw
    template — which reads as engine prose because templates are written to be rewritten."""
    model = _Model(
        json.dumps({"action": "Obtain a pay stub for $9,999.00", "why": "because"}),
        json.dumps({"action": "Obtain the borrower's most recent pay stub", "why": "because"}),
    )
    monkeypatch.setattr("app.ai.finding_prose.complete", model)

    result = await compose(_summary())

    assert isinstance(result, Composition)
    assert "9,999" not in result.message
    assert len(model.messages) == 2


async def test_the_retry_is_told_what_was_wrong(monkeypatch) -> None:
    """At temperature 0 a bare "try again" mostly reproduces the same draw. The appended reason is
    what makes the second attempt different from the first."""
    model = _Model(json.dumps({"action": "Obtain a pay stub for $9,999.00", "why": "because"}))
    monkeypatch.setattr("app.ai.finding_prose.complete", model)

    await compose(_summary())

    assert "REJECTED" in model.messages[1]
    assert _REJECTION_GUIDANCE["unsupported_numbers"] in model.messages[1]


async def test_only_one_retry_then_the_template_stands(monkeypatch) -> None:
    """The guard must not become a loop: two bad drafts and the template wins."""
    model = _Model(json.dumps({"action": "Obtain a pay stub for $9,999.00", "why": "because"}))
    monkeypatch.setattr("app.ai.finding_prose.complete", model)

    assert await compose(_summary()) is None
    assert len(model.messages) == 2  # the original and exactly one retry


async def test_a_transport_failure_is_not_retried_here(monkeypatch) -> None:
    """Transport already has its own retry policy in the client; a second layer here would multiply
    it. Only the model's own recoverable mistakes are retried."""
    from app.ai.client import AIClientError

    calls = {"n": 0}

    async def _boom(**kw: object) -> object:
        calls["n"] += 1
        raise AIClientError("down")

    monkeypatch.setattr("app.ai.finding_prose.complete", _boom)

    assert await compose(_summary()) is None
    assert calls["n"] == 1
    assert "call_failed" not in _RETRYABLE
