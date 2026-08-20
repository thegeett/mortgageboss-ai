"""LP-598 — the cross-check tab renamed seven findings and called it resolution.

WHAT HAPPENED. One snapshot change on LF-3CVT (LP-596's owned-property schedule landing in it) and
every cross-check finding changed identity at once:

    citizenship_documentation        -> citizenship_status_no_supporting_documents
    credit_report_absent             -> liability_balances_no_credit_report
    income_documentation_absent      -> stated_income_no_documentation
    asset_documentation_absent       -> asset_value_no_statements
    property_taxes_insurance_missing -> property_taxes_insurance_hoa_missing
    existing_mortgage_payoff_balance -> existing_mortgage_balance_mismatch

Seven read as "resolved by a file change" while eight identical ones opened beside them. Nothing had
resolved — the model had re-phrased its own category slugs.

THE CAUSE was half-recognised already: `finding_key` normalises the SOURCES before hashing them,
precisely because model-authored strings drift — and then hashed `kind` VERBATIM, which is
model-authored free text subject to the same drift. The kind now comes from a fixed vocabulary.

The second defect in the same run: three of the eight "findings" were passes, one of them titled
`existing_mortgage_balance_mismatch` over a detail reading "These figures match, confirming
consistency". The prompt had invited exactly that ("Also say when figures that LOOK inconsistent are
actually consistent"). The invitation is gone; a narrow check backs it up.
"""

from __future__ import annotations

import json

from app.ai.snapshot_cross_source import (
    _KINDS,
    SNAPSHOT_CROSS_SOURCE_PROMPT,
    SnapshotFindingDraft,
    _parse,
)


def _draft(kind: str, sources: list[tuple[str, str]]) -> SnapshotFindingDraft:
    return SnapshotFindingDraft(
        kind=kind,
        title="t",
        detail="d",
        sources=[{"label": lab, "value": val} for lab, val in sources],
    )


_SOURCES = [
    ("citizenship status", "Non-permanent resident alien"),
    ("supporting documents", "none"),
]


def test_the_same_facts_keep_one_identity_when_the_model_renames_the_category() -> None:
    """THE REGRESSION, in one assertion. These are the two real slugs from consecutive runs."""
    before = _draft("citizenship_documentation", _SOURCES)
    after = _draft("citizenship_status_no_supporting_documents", _SOURCES)

    assert before.finding_key == after.finding_key


def test_every_observed_rename_collapses_to_one_finding() -> None:
    """All six pairs from the run, so a future change to normalisation has to face the real data."""
    renames = [
        ("credit_report_absent", "liability_balances_no_credit_report"),
        ("income_documentation_absent", "stated_income_no_documentation"),
        ("asset_documentation_absent", "asset_value_no_statements"),
        ("property_taxes_insurance_missing", "property_taxes_insurance_hoa_missing"),
        ("existing_mortgage_payoff_balance", "existing_mortgage_balance_mismatch"),
    ]
    for old, new in renames:
        assert _draft(old, _SOURCES).finding_key == _draft(new, _SOURCES).finding_key, (
            f"{old} and {new} still mint separate findings"
        )


def test_a_genuinely_different_category_is_still_a_different_finding() -> None:
    """Identity must not collapse EVERYTHING about one fact pair — the kind still discriminates, it
    just can only take six values now."""
    assert _draft("value_mismatch", _SOURCES).finding_key != (
        _draft("date_inconsistency", _SOURCES).finding_key
    )


def test_an_invented_kind_collapses_to_other_rather_than_being_kept_verbatim() -> None:
    """A verbatim slug is the thing that broke identity. Anything off-vocabulary becomes `other`, so
    two different inventions about the same facts are the SAME finding rather than two."""
    assert _draft("some_new_slug", _SOURCES).normalised_kind == "other"
    assert _draft("a_different_invention", _SOURCES).finding_key == (
        _draft("some_new_slug", _SOURCES).finding_key
    )


def test_the_vocabulary_survives_punctuation_drift() -> None:
    assert _draft("Value-Mismatch", _SOURCES).normalised_kind == "value_mismatch"
    assert _draft("value mismatch", _SOURCES).normalised_kind == "value_mismatch"


def test_the_prompt_lists_exactly_the_vocabulary_the_code_enforces() -> None:
    """A prompt offering a seventh category the code silently rewrites to `other` would reintroduce
    drift by a different route."""
    for kind in _KINDS - {"other"}:
        assert kind in SNAPSHOT_CROSS_SOURCE_PROMPT, f"{kind} is enforced but never offered"


# --------------------------------------------------------------------------- #
# Passes reported as findings
# --------------------------------------------------------------------------- #


def _payload(
    title: str, detail: str, *, values: tuple[str, str] = ("451829.00", "451829.00")
) -> str:
    """One finding. `values` are the two SOURCE figures — LP-602 compares them, so a fixture claiming
    a mismatch has to carry figures that actually differ. The default is the equal pair, which is the
    real staging case."""
    return json.dumps(
        {
            "findings": [
                {
                    "kind": "value_mismatch",
                    "title": title,
                    "detail": detail,
                    "sources": [
                        {"label": "application", "value": values[0]},
                        {"label": "owned property schedule", "value": values[1]},
                    ],
                }
            ]
        }
    )


def test_a_mismatch_headline_over_a_body_that_says_they_match_is_dropped() -> None:
    """VERBATIM FROM THE RUN. The title is what a processor scans; this one sent them after nothing."""
    text = _payload(
        "Existing mortgage balance differs between application and owned property schedule",
        "The application lists an unpaid balance of $451,829.00. The owned property schedule shows a "
        "lien UPB of $451,829.00. These figures match, confirming consistency.",
    )

    assert _parse(text) == []


def test_a_real_mismatch_is_untouched() -> None:
    """The guard is narrow on purpose — it fires on the CONTRADICTION, not on the word 'mismatch'."""
    text = _payload(
        "Existing mortgage balance differs between application and owned property schedule",
        "The application lists $451,829.00 and the schedule shows $398,000.00, a difference of "
        "$53,829.00 that nothing on the file explains.",
        values=("451829.00", "398000.00"),
    )

    assert len(_parse(text)) == 1


def test_a_finding_that_merely_mentions_agreement_is_kept() -> None:
    """A detail can legitimately note that one pair agrees while reporting that another does not."""
    text = _payload(
        "Income stated on the application is not supported by the pay documents",
        "The employer names match, but the stated $13,166.67 monthly does not reconcile to the "
        "annualised figure on the pay stubs.",
        values=("13166.67", "9800.00"),
    )

    assert len(_parse(text)) == 1


def test_the_prompt_no_longer_invites_reporting_agreement() -> None:
    """The root cause: the model was ASKED to report consistency, and did."""
    assert "Also say when figures that LOOK inconsistent are actually consistent" not in (
        SNAPSHOT_CROSS_SOURCE_PROMPT
    )
    assert "If two figures MATCH, that is not a finding" in SNAPSHOT_CROSS_SOURCE_PROMPT


# --------------------------------------------------------------------------- #
# LP-602 — compare the figures, do not hunt for a phrase
# --------------------------------------------------------------------------- #


def test_a_mismatch_whose_own_sources_are_equal_is_dropped() -> None:
    """VERBATIM FROM STAGING, and the finding LP-598's guard was written for and missed.

        title:  "Existing mortgage balance differs between application and owned property schedule"
        kind:   value_mismatch
        sources: owned_property.1.lien_upb = "$451,829"
                 liability.3.unpaid_balance (UNITED WHSLE MORT) = "$451,829"
        detail: "... so they match. No mismatch exists here."

    LP-598 looked for "these match" in the prose; the model wrote "they match". A wording check is a
    guess about phrasing. The figures were sitting in `sources` the whole time.
    """
    text = _payload(
        "Existing mortgage balance differs between application and owned property schedule",
        "The application lists an owned property (the subject) with a lien UPB of $451,829. The "
        "liability schedule lists the UNITED WHSLE MORT mortgage with an unpaid balance of $451,829. "
        "However, both state $451,829, so they match. No mismatch exists here.",
        values=("$451,829", "$451,829"),
    )

    assert _parse(text) == []


def test_formatting_differences_are_not_a_mismatch() -> None:
    """The comparison normalises, so "$451,829" and "451829.00" are the SAME figure — the same
    normalisation identity already uses. Without it, a model citing one source formatted and the other
    raw would manufacture a discrepancy out of punctuation."""
    text = _payload(
        "Balance differs between the application and the schedule",
        "The two sections state different balances.",
        values=("$451,829", "451829.00"),
    )

    assert _parse(text) == []


def test_the_kind_alone_is_enough_to_claim_a_difference() -> None:
    """A title that does not use the word "differs" still claims one when `kind` is value_mismatch."""
    text = _payload(
        "Existing mortgage balance across the two sections",
        "Both sections report the same figure.",
        values=("451829.00", "451829.00"),
    )

    assert _parse(text) == []


def test_the_prompt_names_the_calculation_blocked_evasion() -> None:
    """The same run showed three "document absent" findings filed as `calculation_blocked` — the model
    routing around "do not report a missing document" by relabelling it. The prohibition now says it
    holds whatever kind is chosen, and what that kind is actually for."""
    from app.ai.snapshot_cross_source import SNAPSHOT_CROSS_SOURCE_PROMPT

    assert "reported as calculation_blocked" in SNAPSHOT_CROSS_SOURCE_PROMPT
    assert "This holds WHATEVER" in SNAPSHOT_CROSS_SOURCE_PROMPT
    assert "Use that kind only when a COMPUTED figure" in SNAPSHOT_CROSS_SOURCE_PROMPT
