"""LP-527 — the finding composer: a model rewrites the text, and cannot do anything else.

What is under test is the SAFETY ENVELOPE, not the prose. Whether a sentence reads well is a judgement
a person makes by looking at a real run; whether a generation can invent a fact, change a verdict, or
word the same problem differently twice is decidable here, and each of those is the reason this is
allowed to run at all.

The four constraints, in the order they matter:

1. it only ever rewrites a finding that already exists — no verdict depends on it;
2. it cannot introduce a number that was not in its input;
3. every failure falls back to the template, which is a real sentence (that is why LP-524/525 came
   first);
4. identical facts give identical prose, so an unchanged finding does not reword itself every run.
"""

from __future__ import annotations

import pytest
from app.ai.finding_prose import (
    Composition,
    FactSummary,
    _parse,
    unsupported_numbers,
)

_SUMMARY = FactSummary(
    rule_name="Insurance adequacy",
    subject="Home Insurance (2).pdf",
    problem="the binder does not state a dwelling loss-settlement basis",
    fix="Obtain the declarations page showing the Coverage A loss-settlement basis.",
    facts={"the dwelling loss-settlement basis": "unknown", "Coverage A": "$577,000"},
)


# --------------------------------------------------------------------------------------------- #
# 2. IT CANNOT INTRODUCE A FACT
# --------------------------------------------------------------------------------------------- #
def test_an_invented_number_is_caught() -> None:
    """⚠️ THE CHECK THAT MAKES GENERATION SAFE, and it is DETERMINISTIC. Asking a model whether a model
    hallucinated has the same failure mode as the thing being checked. A number is either in the source
    or it is not.

    "the 2024 W-2" on a file that never mentioned 2024 sends a processor to request a document nobody
    asked for — worse than vague text, because it is confidently wrong."""
    invented = Composition(
        action="Obtain the 2024 W-2.", why="The file is missing it for the 2024 tax year."
    )

    assert unsupported_numbers(_SUMMARY, invented) == {"2024"}


def test_numbers_that_came_from_the_summary_pass() -> None:
    grounded = Composition(
        action="Obtain the declarations page for the policy.",
        why="The binder shows Coverage A of $577,000 but never states how a dwelling loss settles.",
    )

    assert unsupported_numbers(_SUMMARY, grounded) == set()


def test_comma_formatting_is_not_mistaken_for_a_new_number() -> None:
    """$577,000 in the output against 577000 in the source is the SAME fact. A checker that rejected
    it would reject nearly every good generation, and a rejection that fires constantly gets removed."""
    reformatted = Composition(action="Confirm it.", why="Coverage A is $577,000.")
    source = FactSummary(rule_name="r", subject="s", problem="p", fix=None, facts={"a": "577000"})

    assert unsupported_numbers(source, reformatted) == set()


def test_a_single_digit_is_not_treated_as_a_fact() -> None:
    """ "one of the two binders" is ordinary prose. Rejecting on single digits would fire on almost
    every composition, so the check deliberately starts at two."""
    prose = Composition(action="Confirm 1 thing.", why="There are 2 policies in the file.")

    assert unsupported_numbers(_SUMMARY, prose) == set()


# --------------------------------------------------------------------------------------------- #
# 3. EVERY FAILURE FALLS BACK
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "response",
    [
        "",
        "not json at all",
        "{",
        '{"action": "Do it."}',  # no why
        '{"why": "Because."}',  # no action
        '{"action": "", "why": "Because."}',  # empty
        '{"action": 12, "why": "Because."}',  # wrong type
    ],
)
def test_every_malformed_response_is_rejected_whole(response: str) -> None:
    """⚠️ NEVER A PARTIAL COMPOSITION. Half a rewrite — an action with no why — reads as a truncated
    system rather than a finding. Rejection is total, and the template stands."""
    assert _parse(response) is None


def test_a_response_wrapped_in_prose_is_still_read() -> None:
    """Models add "Here is the JSON:". Rejecting on that would throw away good compositions for a
    formatting habit."""
    parsed = _parse(
        'Here you go:\n{"action": "Obtain it.", "why": "It is missing."}\nHope that helps'
    )

    assert parsed is not None and parsed.action == "Obtain it."


# --------------------------------------------------------------------------------------------- #
# 4. IDENTICAL FACTS, IDENTICAL PROSE
# --------------------------------------------------------------------------------------------- #
def test_the_same_facts_hash_the_same() -> None:
    """The cache key IS the determinism guarantee. Without it the same unchanged problem is worded
    differently on every run, and a processor re-reads it thinking something changed."""
    twin = FactSummary(
        rule_name="Insurance adequacy",
        subject="Home Insurance (2).pdf",
        problem="the binder does not state a dwelling loss-settlement basis",
        fix="Obtain the declarations page showing the Coverage A loss-settlement basis.",
        facts={"Coverage A": "$577,000", "the dwelling loss-settlement basis": "unknown"},
    )

    assert twin.cache_key() == _SUMMARY.cache_key()


def test_a_changed_fact_changes_the_key() -> None:
    """A file that genuinely changed must re-compose — a cache that never invalidates would pin stale
    prose to new facts, which is worse than regenerating."""
    changed = FactSummary(
        rule_name=_SUMMARY.rule_name,
        subject=_SUMMARY.subject,
        problem=_SUMMARY.problem,
        fix=_SUMMARY.fix,
        facts={"Coverage A": "$601,000"},
    )

    assert changed.cache_key() != _SUMMARY.cache_key()


def test_the_summary_carries_no_field_the_prompt_cannot_use() -> None:
    """The summary is the ONLY thing a composition may draw on, so what it omits is as deliberate as
    what it holds: no rule id, no tag id, no confidence, no verdict — a processor's finding should
    describe the loan file, not the software that inspected it."""
    payload = _SUMMARY.to_json()

    for leak in ("rule_id", "IH-1", "tag_id", "confidence", "couldnt_check", "verdict"):
        assert leak not in payload


# --------------------------------------------------------------------------------------------- #
# THE PROMPT'S OWN CONTRACT
# --------------------------------------------------------------------------------------------- #
def test_the_prompt_forbids_the_two_things_that_would_undo_this() -> None:
    """Belt and braces with the deterministic check: the prompt says not to invent facts and not to
    mention the machinery. The check enforces the first; nothing but the prompt enforces the second,
    which is why it is asserted rather than assumed."""
    from app.ai.finding_prose import SYSTEM_PROMPT

    assert "Never introduce a number" in SYSTEM_PROMPT
    assert "Never mention the AI" in SYSTEM_PROMPT
    assert "imperative" in SYSTEM_PROMPT


# --------------------------------------------------------------------------------------------- #
# LP-528 — the two leaks the FIRST REAL COMPOSED RUN exposed
# --------------------------------------------------------------------------------------------- #
def test_machinery_talk_is_rejected() -> None:
    """⚠️ FOUND ON A REAL RUN. The prompt forbids mentioning the software and the model wrote "The
    system cannot verify derogatory seasoning requirements" anyway, four times. A processor does not
    care what the system can do — only what the file is missing. A prompt instruction is a hope; this
    is the guarantee."""
    from app.ai.finding_prose import machinery_talk

    leaked = Composition(
        action="Upload the credit report.",
        why="The system cannot verify seasoning without it.",
    )

    assert machinery_talk(leaked) == {"the system"}


def test_ordinary_prose_is_not_mistaken_for_machinery_talk() -> None:
    """The banned list must not fire on a good sentence, or every composition falls back and the
    feature is off in all but name."""
    from app.ai.finding_prose import machinery_talk

    good = Composition(
        action="Obtain the declarations page for the policy.",
        why="The binder never states how a dwelling loss is settled.",
    )

    assert machinery_talk(good) == set()


def test_the_summary_never_carries_a_raw_content_id() -> None:
    """⚠️ THE OTHER REAL-RUN LEAK. A first version passed `subject_key` — a content-id hash — and the
    model faithfully wrote it into user-facing text: "the retained property on doc7031677534131285",
    "for liability lia7a033a46ec70cc10". LP-377-B exists to keep that away from a processor, and the
    read path already had `resolve_subject_label`; the composer now uses the same resolver."""
    from app.models.finding import Finding
    from app.services.finding_prose import summarize

    finding = Finding(
        loan_file_id=None,
        rule_id="DT-6",
        message="the application states a lower monthly payment",
        subject_key="doc7031677534131285",
        load_bearing_tags=[],
        details={},
    )

    summary = summarize(finding, rule_name="DTI", document_filenames={})

    assert "doc7031677534131285" not in summary.to_json()
