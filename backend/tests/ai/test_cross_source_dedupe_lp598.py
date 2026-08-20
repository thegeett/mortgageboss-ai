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


def _payload(title: str, detail: str) -> str:
    return json.dumps(
        {
            "findings": [
                {
                    "kind": "value_mismatch",
                    "title": title,
                    "detail": detail,
                    "sources": [
                        {"label": "application", "value": "451829.00"},
                        {"label": "owned property schedule", "value": "451829.00"},
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
    )

    assert len(_parse(text)) == 1


def test_a_finding_that_merely_mentions_agreement_is_kept() -> None:
    """A detail can legitimately note that one pair agrees while reporting that another does not."""
    text = _payload(
        "Income stated on the application is not supported by the pay documents",
        "The employer names match, but the stated $13,166.67 monthly does not reconcile to the "
        "annualised figure on the pay stubs.",
    )

    assert len(_parse(text)) == 1


def test_the_prompt_no_longer_invites_reporting_agreement() -> None:
    """The root cause: the model was ASKED to report consistency, and did."""
    assert "Also say when figures that LOOK inconsistent are actually consistent" not in (
        SNAPSHOT_CROSS_SOURCE_PROMPT
    )
    assert "If two figures MATCH, that is not a finding" in SNAPSHOT_CROSS_SOURCE_PROMPT
