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
from app.models.finding import Finding

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
def test_the_prompt_tells_the_model_not_to_restate_the_threshold() -> None:
    """The append guarantees the arithmetic; it cannot stop the model ALSO writing its own vaguer
    version, and the first run with it live said the same thing twice — "exceeds the materiality
    threshold" immediately before the exact figure. The guarantee and the tidiness are separate
    problems, and only the tidiness is safe to solve with a prompt."""
    from app.ai.finding_prose import SYSTEM_PROMPT

    assert "materiality threshold" in SYSTEM_PROMPT
    assert "appended to your text automatically" in SYSTEM_PROMPT


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


def test_echoing_our_own_template_wording_is_not_machinery_talk() -> None:
    """ "this check" and "could not be determined" appear in the TEMPLATE messages the model receives as
    its `problem` input, so banning them would reject a faithful composition for echoing its source.

    (I first blamed them for CR-6 x4 and PR-6 falling back to templates on a real run. The logs said
    otherwise — every rejection was "the system" — so this pins a correctness property rather than a
    regression, and the real cause is addressed in the prompt.)"""
    from app.ai.finding_prose import machinery_talk

    echoed = Composition(
        action="Upload the tri-merge credit report.",
        why="Whether this account carries a derogatory mark could not be determined from the file.",
    )

    assert machinery_talk(echoed) == set()


def test_naming_the_software_as_an_actor_is_still_rejected() -> None:
    """The narrowing must not let the original leak back through."""
    from app.ai.finding_prose import machinery_talk

    for phrase in (
        "The system cannot verify it.",
        "The rule engine could not run.",
        "The AI judged it.",
    ):
        assert machinery_talk(Composition(action="Do it.", why=phrase)), phrase


# --------------------------------------------------------------------------------------------- #
# LP-535 — a requirement the composer was free to delete
# --------------------------------------------------------------------------------------------- #
def test_the_materiality_derivation_survives_a_composition_that_dropped_it() -> None:
    """⚠️ FOUND ON THE SECOND COMPOSED RUN. LP-518 puts the arithmetic in the finding on purpose: a
    processor who reads "$2,000.00 is above the $1,316.67 (10% of $13,166.70 monthly qualifying income)
    materiality floor" can argue with the threshold; one who reads "exceeds the materiality threshold"
    can only take it on faith.

    The composer deleted it from FOUR of five AS-12 findings and kept only the bare number in the fifth.
    That is a composer doing its job — it was asked to shorten — which is exactly why the requirement
    cannot live in the prose it is allowed to rewrite."""
    from app.services.finding_prose import _with_derivation

    derivation = (
        "$2,000.00 is above the $1,316.67 (10% of $13,166.70 monthly qualifying income) floor"
    )
    finding = Finding(
        loan_file_id=None,
        rule_id="AS-12",
        message="",
        subject_key="txn1",
        load_bearing_tags=[],
        details={"derivation": derivation},
    )

    restored = _with_derivation(
        "Obtain the statement. It exceeds the materiality threshold.", finding
    )

    assert "10% of $13,166.70" in restored
    # Its own sentence — the derivation already carries a bracketed clause, so wrapping it in another
    # pair produced nested parentheses on every AS-12 finding of the run that introduced this.
    assert "((" not in restored and f"({derivation}" not in restored


def test_a_composition_that_kept_the_derivation_is_not_given_it_twice() -> None:
    """Appending unconditionally would print the arithmetic twice on every composition that honoured
    it — a fix that reads as a bug."""
    from app.services.finding_prose import _with_derivation

    derivation = (
        "$2,000.00 is above the $1,316.67 (10% of $13,166.70 monthly qualifying income) floor"
    )
    finding = Finding(
        loan_file_id=None,
        rule_id="AS-12",
        message="",
        subject_key="txn1",
        load_bearing_tags=[],
        details={"derivation": derivation},
    )
    kept = "At $2,000.00 it is above the 10% of $13,166.70 monthly qualifying income floor."

    assert _with_derivation(kept, finding) == kept


def test_a_finding_with_no_derivation_is_untouched() -> None:
    """Most rules have no materiality floor at all; none of them should grow a trailing clause."""
    from app.services.finding_prose import _with_derivation

    finding = Finding(
        loan_file_id=None,
        rule_id="IH-1",
        message="",
        subject_key="doc1",
        load_bearing_tags=[],
        details={},
    )

    assert (
        _with_derivation("Obtain the declarations page.", finding)
        == "Obtain the declarations page."
    )


# --------------------------------------------------------------------------------------------- #
# LP-537 — the evidence a ratifier is being asked to countersign
# --------------------------------------------------------------------------------------------- #
def _judgment_finding(rule_id: str, tags: list[dict[str, str]]) -> Finding:
    return Finding(
        loan_file_id=None,
        rule_id=rule_id,
        message="x",
        subject_key="loan",
        load_bearing_tags=tags,
        details={},
    )


def test_the_tags_own_reasoning_reaches_the_composer() -> None:
    """⚠️ WHY DT-7 SHIPPED A BARE ASSERTION. The summary carried the VALUE ("complete") and dropped the
    tag's reasoning, which is the sentence naming the documents. The model wrote "Every ability-to-repay
    factor has a supporting document in the file" because a bare conclusion was all it was given.

    DT-7 and OC-2 are ratification items — a human is asked to countersign an AI verdict on a tag with
    no measured accuracy, and that ratification is the ONLY reason either rule is allowed to run
    (activation_bars: "OC-2 never needed the tag CALIBRATED" because a human signs each). A
    countersignature on a conclusion whose basis is hidden is not a control, it is a click."""
    from app.services.finding_prose import summarize

    finding = _judgment_finding(
        "DT-7",
        [
            {
                "tag_id": "dti.atr_factors_documented",
                "value": "complete",
                "reasoning": "W-2s for 2023 and 2024, pay stubs from March 2025, bank statements.",
            }
        ],
    )

    evidence = summarize(finding, rule_name="ATR").evidence

    assert "pay stubs from March 2025" in " ".join(evidence.values())


def test_an_identifier_in_the_reasoning_is_translated_not_deleted() -> None:
    """⚠️ THE REGRESSION THE FIRST ATTEMPT SHIPPED. Tag prompts REQUIRE citing tags by id, so reasoning
    is full of `occupancy.consistent_with_signals` and MISMO paths. Deleting them turned OC-2's

        "The single borrower's declaration.intenttooccupytype is 'Yes'"

    into "The single borrower's is 'Yes'" — which loses the subject, and the subject WAS the point: it
    shows the model corroborated the stated occupancy with the borrower's own declaration of it. That
    circularity is exactly what a ratifier is there to catch, and erasing the identifier erased it."""
    from app.services.finding_prose import summarize

    finding = _judgment_finding(
        "OC-2",
        [
            {
                "tag_id": "occupancy.consistent_with_signals",
                "value": "yes",
                "reasoning": "The borrower's declaration.intenttooccupytype is 'Yes'.",
            }
        ],
    )

    text = " ".join(summarize(finding, rule_name="Occupancy").evidence.values())

    assert "declaration.intenttooccupytype" not in text  # never the raw path
    assert "intenttooccupytype" in text  # but the subject survives
    assert "borrower's is" not in text  # the hole the first version left


def test_a_tag_id_in_the_OUTPUT_is_rejected() -> None:
    """The strip is on the way in; this is the way out. Belt and braces, because the model also sees
    the rule name and could construct one — and LP-377-B's rule is about what a processor READS."""
    from app.ai.finding_prose import leaked_identifiers

    leaked = Composition(
        action="Confirm it.", why="The occupancy.consistent_with_signals tag says yes."
    )

    assert leaked_identifiers(leaked) == {"occupancy.consistent_with_signals"}
    assert leaked_identifiers(Composition(action="Obtain the W-2.", why="It is missing.")) == set()


def test_a_long_reasoning_is_capped() -> None:
    """A finding can rest on six tags (AS-12). Uncapped, one verbose tag crowds out the rest."""
    from app.services.finding_prose import _EVIDENCE_LIMIT, summarize

    finding = _judgment_finding(
        "DT-7",
        [{"tag_id": "dti.atr_factors_documented", "value": "complete", "reasoning": "x " * 800}],
    )

    assert len(next(iter(summarize(finding, rule_name="ATR").evidence.values()))) <= _EVIDENCE_LIMIT
