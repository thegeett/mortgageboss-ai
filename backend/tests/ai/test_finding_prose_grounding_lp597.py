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


# --------------------------------------------------------------------------- #
# LP-599 — the composer put "correctly" back after the spec removed it
# --------------------------------------------------------------------------- #


def _composition(text: str):
    from app.ai.finding_prose import Composition

    return Composition(action=text, why="because")


def test_the_exact_sentence_that_shipped_is_rejected() -> None:
    """VERBATIM FROM STAGING. DT-8's template was rewritten to drop "correctly" and the reference to a
    gated ratio; the composer paraphrased it straight back and a processor read this:

        "The existing mortgage with UNITED WHSLE MORT is correctly excluded from the
         debt-to-income ratio."

    Fixing the template does not hold when a model rewrites it. "Correctly" claims the check confirmed
    the lien BELONGS excluded — that it sits on the subject property — which nothing established.
    """
    from app.ai.finding_prose import editorialises_correctness

    shipped = _composition(
        "The existing mortgage with UNITED WHSLE MORT is correctly excluded from the "
        "debt-to-income ratio."
    )

    assert editorialises_correctness(shipped) == {"correctly"}


def test_the_words_a_passing_finding_actually_needs_are_left_alone() -> None:
    """THE LINE THIS CHECK MUST NOT CROSS. The prompt's own worked examples for a pass are
    "Employment is verified for the full two-year history" and "Reserves are fully documented".
    Banning those would break the guidance the same file gives three rules above."""
    from app.ai.finding_prose import editorialises_correctness

    for kept in (
        "Employment is verified for the full two-year history.",
        "Reserves are fully documented.",
        "This payment is on the application's liability list.",
        "The two-year employment history is continuous.",
    ):
        assert editorialises_correctness(_composition(kept)) == set(), kept


def test_every_editorialising_word_is_caught() -> None:
    from app.ai.finding_prose import _EDITORIALISING, editorialises_correctness

    for word in _EDITORIALISING:
        assert editorialises_correctness(_composition(f"This is {word} handled.")) == {word}


def test_the_prompt_forbids_it_and_says_which_words_are_still_fine() -> None:
    """A ban with no carve-out would have the model avoid "documented" and "verified" too, which the
    pass guidance depends on."""
    from app.ai.finding_prose import SYSTEM_PROMPT

    assert "Never write that something is CORRECTLY" in SYSTEM_PROMPT
    assert '"documented" and "verified" ARE fine' in SYSTEM_PROMPT


async def test_it_is_retried_rather_than_falling_back_to_the_template(monkeypatch) -> None:
    """The template is the thing being rescued here — DT-8's raw text is what a rejection ships, and
    it reads as engine prose. A retry is what turns this into a fix rather than a different failure."""
    model = _Model(
        json.dumps({"action": "The mortgage is correctly excluded from the ratio", "why": "b"}),
        json.dumps({"action": "The application marks this mortgage as paid off", "why": "b"}),
    )
    monkeypatch.setattr("app.ai.finding_prose.complete", model)

    # settled=True: DT-8's is a SATISFIED finding, so a statement is the right shape and LP-603's
    # inverse guard ("a review must ask for something") does not apply. The fixture said otherwise
    # before, which made it an incoherent pair — a pass-style sentence on an unresolved finding.
    result = await compose(_summary(settled=True))

    assert result is not None
    assert "correctly" not in result.message
    assert len(model.messages) == 2
    assert "not yours to assert" in model.messages[1]


# --------------------------------------------------------------------------- #
# LP-601 — a guard that only runs on a cache MISS never sees stored prose
# --------------------------------------------------------------------------- #


def test_the_shared_verdict_catches_every_guard() -> None:
    """`compose` and the cache filter both go through `rejection_reason`, so a guard cannot be added
    to one and forgotten in the other — which is how DT-8 kept shipping "correctly excluded" after
    LP-599 banned it."""
    from app.ai.finding_prose import rejection_reason

    summary = _summary(documents_on_file=0)

    assert rejection_reason(summary, _composition("Obtain the pay stub")) is None
    assert rejection_reason(summary, _composition("It is correctly excluded")) == "editorialising"
    assert rejection_reason(summary, _composition("The system could not check")) == "machinery_talk"
    assert (
        rejection_reason(summary, _composition("Obtain a stub for $9,999"))
        == "unsupported_numbers:1"
    )


def test_a_pass_finding_asking_for_work_is_still_caught_through_the_shared_path() -> None:
    from app.ai.finding_prose import rejection_reason

    settled = _summary(settled=True)

    assert rejection_reason(settled, _composition("Confirm the reserves are documented")) == (
        "asking_on_a_pass"
    )
    assert rejection_reason(settled, _composition("Reserves are fully documented")) is None


# --------------------------------------------------------------------------- #
# LP-603 — a finding on the list must say what to do about it
# --------------------------------------------------------------------------- #


def test_a_finding_that_is_not_resolved_must_ask_for_something() -> None:
    """VERBATIM FROM STAGING. OC-2 shipped this on a `needs_review`:

        "The stated primary residence occupancy is supported by the application."

    A sentence that reads as a pass, sitting in Needs attention, asking for nothing. OC-2 is a
    judgment rule and ratifies every verdict (ADR-336), so even a confident "yes" reaches a human —
    and the text has to make that ratification the ask rather than report that all is well.

    The `settled` direction was already guarded ("do not write a pass as a task"); this is its
    inverse, which had no check at all.
    """
    from app.ai.finding_prose import rejection_reason

    unresolved = _summary(settled=False)
    shipped = _composition("The stated primary residence occupancy is supported by the application")

    assert rejection_reason(unresolved, shipped) == "stating_on_a_review"
    assert rejection_reason(unresolved, _composition("Confirm the stated occupancy")) is None


def test_the_two_directions_do_not_contradict_each_other() -> None:
    """The pair has to be exclusive, or every composition is rejected whichever way it is written."""
    from app.ai.finding_prose import rejection_reason

    statement = _composition("Reserves are fully documented")
    task = _composition("Obtain the reserve documentation")

    assert rejection_reason(_summary(settled=True), statement) is None
    assert rejection_reason(_summary(settled=True), task) == "asking_on_a_pass"
    assert rejection_reason(_summary(settled=False), task) is None
    assert rejection_reason(_summary(settled=False), statement) == "stating_on_a_review"


def test_ih3_asks_for_both_sides_of_its_comparison() -> None:
    """IH-3 compares an insurance effective date against a closing date, and its couldnt_check fix
    presumed the policy was already in the file ("the policy's effective date", "if more than one
    homeowners policy is in the file"). On a file carrying NEITHER — the ordinary state at intake — it
    asked only for the Closing Disclosure, so a processor who uploaded it would find the rule still
    unable to answer."""
    from app.verification.rules.specs import load_rule_spec

    fix = load_rule_spec("IH-3").deterministic.couldnt_check_fix or ""

    assert "homeowners insurance declarations page or binder" in fix
    assert "Closing Disclosure" in fix


# --------------------------------------------------------------------------- #
# LP-607 — content ids are identifiers too
# --------------------------------------------------------------------------- #


def test_a_content_id_in_composed_text_is_rejected() -> None:
    """The dotted pattern cannot see these — they have no dot — so `docdbbe8db1f5a7d9ff` walked
    straight past the guard whose whole job is keeping internal keys away from a processor. ID-4
    shipped five of them in one sentence."""
    from app.ai.finding_prose import leaked_identifiers

    leaked = _composition(
        "Reconcile the address; it differs across sources "
        "(docdbbe8db1f5a7d9ff, doc6abd650d555473b0)."
    )

    assert leaked_identifiers(leaked) == {"docdbbe8db1f5a7d9ff", "doc6abd650d555473b0"}


def test_every_subject_key_prefix_is_covered() -> None:
    """`doc` was the one observed, but the subject-key vocabulary has four prefixes and any of them
    would read the same way to a processor."""
    from app.ai.finding_prose import leaked_identifiers

    for key in (
        "doc1a2b3c4d5e6f70",
        "lia7a033a46ec70cc10",
        "txn0f1e2d3c4b5a6978",
        "acct9988776655",
    ):
        assert leaked_identifiers(_composition(f"See {key} for detail.")) == {key}


def test_ordinary_words_are_not_mistaken_for_content_ids() -> None:
    """The pattern needs a hex run of real length, so prose that happens to start with those letters
    is untouched — "documented", "liability", "accounted for"."""
    from app.ai.finding_prose import leaked_identifiers

    clean = _composition("The documented liability is accounted for on the application.")

    assert leaked_identifiers(clean) == set()


def test_the_rejection_is_retried_rather_than_shipping_the_template() -> None:
    """Same reasoning as every other guard here: a rejection ships the raw engine template, so the
    retry is what makes this a fix instead of a different bad output."""
    from app.ai.finding_prose import _RETRYABLE

    assert "identifier" in _RETRYABLE
