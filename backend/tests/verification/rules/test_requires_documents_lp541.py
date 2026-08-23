"""LP-541 — every rule declares WHICH documents its inputs come from.

A `couldnt_check` today reads the same whether the document is absent or present-but-inadequate, and
those are different jobs: one becomes an outbound request to the borrower, the other is desk work.
On LF-WCHG the split is 6 rules to request against 5 to read, and nothing in the UI distinguished them.

READ-TIME CLASSIFICATION ONLY. No verdict, gate, outcome or tag reads this field, so a wrong entry
mis-sorts a card and can never change a conclusion. That is what makes hand-authored data safe here.
"""

from __future__ import annotations

import pytest
from app.schemas.verification import _missing_documents, _requested_documents
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.rules.specs import RuleSpec, load_rule_spec


def test_every_active_rule_declares_its_documents() -> None:
    """COMPLETENESS IS THE WHOLE POINT. A partial declaration is worse than none: the UI would show
    "request this" on the rules we happened to annotate and nothing on the rest, and a processor reads
    an absent marker as "not a missing document" rather than as "not yet classified".

    `None` is deliberately distinct from `[]` so this test can tell an UNANNOTATED rule from one that
    genuinely reads no document (a computed LTV, a MISMO-only field)."""
    undeclared = [
        r for r in sorted(ACTIVE_RULE_IDS) if load_rule_spec(r).requires_documents is None
    ]

    assert not undeclared, f"these rules cannot be classified as request-vs-review: {undeclared}"


def test_an_uncataloged_document_type_fails_at_load() -> None:
    """A typo'd slug would match no document forever, so the rule would report the file as missing
    something it holds — silently, and only on the files that actually have it."""
    spec = load_rule_spec("IN-8").model_dump()
    spec["requires_documents"] = (("voe", "verbal_voee"),)  # pragma: allowlist secret

    with pytest.raises(ValueError, match="uncataloged"):
        RuleSpec(**spec)


def test_an_empty_alternative_group_is_rejected() -> None:
    """ "any one of nothing" can never be satisfied, so it would mark every file as missing it."""
    spec = load_rule_spec("IN-8").model_dump()
    spec["requires_documents"] = ((),)

    with pytest.raises(ValueError, match="never be satisfied"):
        RuleSpec(**spec)


# --------------------------------------------------------------------------------------------- #
# THE SHAPE THAT THE FIRST VERSION GOT WRONG
# --------------------------------------------------------------------------------------------- #
def _missing(rule_id: str, on_file: set[str]) -> list[tuple[str, ...]]:
    """The declared groups no document on the file satisfies — the read path's classification."""
    groups = load_rule_spec(rule_id).requires_documents or ()
    return [group for group in groups if not set(group) & on_file]


def test_alternatives_within_a_group_are_interchangeable() -> None:
    """IN-8 accepts a WRITTEN or a VERBAL VOE — either closes the gap, so holding one is not a gap."""
    assert _missing("IN-8", {"verbal_voe"}) == []
    assert _missing("IN-8", {"voe"}) == []
    assert _missing("IN-8", {"pay_stub", "w2"}) != []


def test_groups_are_all_required_so_a_second_document_cannot_mask_a_missing_first() -> None:
    """THE MODELLING ERROR, PINNED. A flat list made CR-6 read as "read what is here" on LF-WCHG —
    a file with NO credit report — purely because the Closing Disclosure it also needs was present.

    CR-6 needs the report AND a closing date; IN-8 needs a written OR a verbal VOE. Flattened, the two
    are indistinguishable, and the field exists precisely to tell them apart."""
    assert _missing("CR-6", {"closing_disclosure"}) == [("credit_report",)]
    assert _missing("CR-6", {"credit_report", "closing_disclosure"}) == []


# --------------------------------------------------------------------------------------------- #
# THE READ-PATH CLASSIFICATION
# --------------------------------------------------------------------------------------------- #
_LFWCHG = {
    "drivers_license",
    "w2",
    "pay_stub",
    "bank_statement",
    "homeowners_insurance",
    "property_tax_bill",
    "mortgage_statement",
    "uscis_notice_of_action",
    "lender_dashboard_screenshot",
    "form_1098",
    "closing_disclosure",
}


@pytest.mark.parametrize(
    ("rule_id", "expected"),
    [
        # Absent — a processor has to go and GET these.
        ("CR-6", ["credit report"]),
        ("CR-13", ["credit report"]),
        ("PR-6", ["appraisal"]),
        ("CL-1", ["rate lock agreement"]),
        ("IN-8", ["VOE"]),
        ("ID-7", ["title commitment"]),
        # LP-620 — MOVED from the read side. IN-4 wants START and END dates, and its own fix offers "a
        # written verification of employment, or pay stubs and W-2s that establish the dates". Pay stubs
        # and W-2s being on file was read as "the document is here", but undated ones are the very case
        # the fix names — so the VOE it had never declared is what actually closes the gap. `finding_prose`
        # had already recorded the omission ("IN-4's fix offers a verification of employment that IN-4 does
        # not declare") and worked around it on the prose side; the button had no such workaround.
        ("IN-4", ["VOE"]),
        # Present — the document is here and does not answer the question. Desk work, not a request.
        ("IH-1", []),
        ("IH-3", []),
        ("IN-3", []),
    ],
)
def test_the_real_file_classifies_the_way_a_human_reads_it(
    rule_id: str, expected: list[str]
) -> None:
    """The document set is LF-WCHG's actual inventory. Every one of these was couldnt_check on that run
    and read identically on the card; on LP-541's original classification six were a request and four
    were something to go and read. IN-4 moved to the request side in LP-620.

    The labels are the READABLE forms — "VOE", not "voe" — because they are what the sub-header prints
    and what a processor puts in an email."""
    assert _missing_documents(load_rule_spec(rule_id), _LFWCHG) == expected


def test_an_unclassifiable_rule_reports_nothing_missing_rather_than_guessing() -> None:
    """A retired rule has no spec, so it cannot be classified. Reporting `[]` puts it with "read what is
    here", which asks a processor to LOOK — the other side would assert an absence we never established."""
    assert _missing_documents(None, _LFWCHG) == []


# --------------------------------------------------------------------------------------------- #
# LP-542 — a purchase-only document is not "missing" from a refinance
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("rule_id", ["PC-2", "PC-3", "FR-3"])
def test_a_purchase_only_document_is_not_reported_missing_on_a_refinance(rule_id: str) -> None:
    """THE SAME MISTAKE AS OC-2'S IMPOSSIBLE ASK, in a different place. A refinance has no purchase
    contract and never will, so "waiting on purchase agreement" sends a processor after something
    unobtainable. Latent when this shipped — no purchase-scoped rule was couldnt_check on the file that
    exposed it — which is exactly why it is pinned rather than left to be found later."""
    assert _missing_documents(load_rule_spec(rule_id), set(), loan_purpose="purchase")
    assert _missing_documents(load_rule_spec(rule_id), set(), loan_purpose="refinance") == []


def test_a_group_with_an_obtainable_alternative_survives_on_a_refinance() -> None:
    """Only a group whose EVERY alternative is purchase-only is dropped. PR-2 wants an appraisal and a
    purchase agreement as separate groups — the appraisal is obtainable on a refinance and must stay,
    or the rule would silently stop reporting a document it genuinely needs."""
    assert _missing_documents(load_rule_spec("PR-2"), set(), loan_purpose="refinance") == [
        "appraisal"
    ]


# --------------------------------------------------------------------------------------------- #
# LP-620 — a finding may answer for itself where the spec cannot
# --------------------------------------------------------------------------------------------- #
def test_a_findings_own_request_overrides_the_spec_derived_list() -> None:
    """The consistency engine's single-source abstention needs one MORE source than the file has, which
    a presence test can never report. When the evaluator records what it is waiting on, that wins."""
    assert _requested_documents(
        {"requested_documents": ["Another document stating the borrower's date of birth"]}
    ) == ["Another document stating the borrower's date of birth"]


def test_a_finding_that_records_nothing_falls_back_to_the_spec() -> None:
    """Nearly every rule is already classified correctly by its declaration, and must stay that way —
    the override is an addition to the mechanism, not a replacement for it."""
    assert _requested_documents({}) == []
    assert _requested_documents({"requested_documents": []}) == []


@pytest.mark.parametrize(
    "stored",
    [
        {"requested_documents": "appraisal"},  # a string, not a list
        {"requested_documents": [None, 3]},  # non-strings
        {"requested_documents": ["", "   "]},  # blank labels
    ],
)
def test_a_malformed_stored_value_falls_through_rather_than_reaching_a_button(
    stored: dict[str, object],
) -> None:
    """`details` is stored JSON and outlives the code that wrote it. A legacy or malformed value must
    degrade to the spec-derived list — a blank or non-string label would render as "Request " and
    create a needs item titled after nothing."""
    assert _requested_documents(stored) == []
