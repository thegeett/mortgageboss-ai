"""LP-613 — the review fixes, each pinned by the failure it prevents.

Seven defects from one review, and three of them had been reported before and not fixed. Every test
here names the wrong behaviour rather than the right one, because in each case the wrong behaviour
looked reasonable: a scope gate that abstains, a dedupe that tidies a sentence, a grounding check that
is generous about spelling.
"""

from __future__ import annotations

import pytest
from app.ai.finding_prose import Composition, FactSummary, unsupported_numbers
from app.ai.snapshot_cross_source import _canonical_path, _parse, snapshot_paths
from app.verification.cross_source import GOVERNED_OWNED_TYPES
from app.verification.rules.specs import load_rule_spec


# --------------------------------------------------------------------------------------------- #
# 1. CR-6 — a stated liability is OUT OF SCOPE, not un-checkable
# --------------------------------------------------------------------------------------------- #
def test_cr6_scopes_to_the_credit_report_leg() -> None:
    """Without the source predicate every MISMO-stated liability was a permanent couldnt_check.

    `liab.is_derogatory` is produced only for `credit_report_reported` rows (LP-606's subject_source
    gate), so on a stated row the tag is ABSENT — and an absent predicate resolves to couldnt_check,
    not not_applicable. A file WITH a tri-merge report therefore shipped one "Upload the tri-merge
    credit report" per stated liability, which the processor had already done and could never clear.
    CR-1 and CR-12 carry the identical predicate; CR-6 was the one that did not.
    """
    spec = load_rule_spec("CR-6")
    assert spec.deterministic is not None
    predicates = spec.deterministic.applicability
    assert not isinstance(predicates, dict | type(None)), "CR-6 needs BOTH predicates, not one"
    tags = {p.tag_id for p in predicates}
    assert "liability.source" in tags, "a stated row must be scope-false, not data-missing"
    assert "liab.is_derogatory" in tags, "the derogatory gate must survive (LP-524's flooding fix)"


@pytest.mark.parametrize("rule_id", ["CR-1", "CR-6", "CR-12"])
def test_the_credit_report_rules_agree_on_scope(rule_id: str) -> None:
    """One question, one scope. These three read the same subject family and must not disagree."""
    spec = load_rule_spec(rule_id)
    assert spec.deterministic is not None
    predicates = spec.deterministic.applicability
    listed = predicates if isinstance(predicates, tuple | list) else [predicates]
    assert any(
        p.tag_id == "liability.source" and p.value == "credit_report_reported" for p in listed
    ), f"{rule_id} must scope to the report leg"


# --------------------------------------------------------------------------------------------- #
# 2. The AI defers on a question a governed rule now owns
# --------------------------------------------------------------------------------------------- #
def test_the_retired_questions_are_deferred_unconditionally() -> None:
    """Retiring a deterministic rule removed the FIRING, not the question.

    The AI defers run-scoped, on types something fired this run. LP-606/LP-611 retired the employer
    and name rules because a strict comparison contradicted a tolerant governed rule in front of a
    processor — so on a name-order or spelling variance nothing fires, the type is absent from
    `fired_types`, and the AI re-emits the retired sentence beside ID-1's "consistent across all
    sources". The contradiction returns from the other side.
    """
    assert "identity_discrepancy" in GOVERNED_OWNED_TYPES
    assert "employer_mismatch" in GOVERNED_OWNED_TYPES


# --------------------------------------------------------------------------------------------- #
# 3. Snapshot addresses — one spelling for identity, two accepted for grounding
# --------------------------------------------------------------------------------------------- #
_KEYS = frozenset(
    {
        "mismo",
        "mismo.facts",
        "mismo.facts.liability.3.unpaid_balance",
        "liability.3.unpaid_balance",
        "owned_property.1.lien_upb",
    }
)


def _key_for(path_a: str, path_b: str) -> str | None:
    body = (
        '{"findings":[{"kind":"value_mismatch","title":"Balance differs","detail":"d","sources":['
        f'{{"path":"{path_a}","label":"a","value":"451829"}},'
        f'{{"path":"{path_b}","label":"b","value":"460000"}}]}}]}}'
    )
    drafts = _parse(body, _KEYS)
    return drafts[0].finding_key if drafts else None


def test_identity_does_not_depend_on_which_spelling_the_model_picked() -> None:
    """Grounding accepts the route AND the leaf; identity hashed whichever arrived.

    A model citing `mismo.facts.liability.3.unpaid_balance` one run and `liability.3.unpaid_balance`
    the next produced two `finding_key`s for one finding: the first resolved as "fixed by a file
    change", its sign-off lost, and a duplicate opened beside it. That is the failure this module
    exists to prevent, arriving through the door left open for grounding.
    """
    route = _key_for("mismo.facts.liability.3.unpaid_balance", "owned_property.1.lien_upb")
    leaf = _key_for("liability.3.unpaid_balance", "owned_property.1.lien_upb")

    assert route is not None and leaf is not None, "both spellings must still ground"
    assert route == leaf, "one address, one identity"


def test_both_spellings_still_ground() -> None:
    """The permissive acceptance is the point of the grounding check and must survive the fix."""
    assert _canonical_path("mismo.facts.liability.3.unpaid_balance", _KEYS) == (
        "liability.3.unpaid_balance"
    )
    assert _canonical_path("liability.3.unpaid_balance", _KEYS) == "liability.3.unpaid_balance"


def test_a_path_the_snapshot_does_not_carry_is_left_alone() -> None:
    """Canonicalisation must not invent an address for something that grounds nowhere."""
    assert _canonical_path("not.a.real.address", _KEYS) == "not.a.real.address"


class _Stub:
    def model_dump(self, mode: str = "json") -> dict[str, object]:
        return {
            "mismo": {"facts": {"liability.3.unpaid_balance": {"value": "451829", "source": "m"}}},
            "documents": {"entries": [{"confidence": 0.9, "amount": 12}]},
        }


@pytest.mark.parametrize("generic", ["value", "source", "confidence", "amount"])
def test_a_bare_field_name_is_not_a_snapshot_address(generic: str) -> None:
    """Every key at every depth was accepted, so `path: "value"` passed the fabrication check.

    Worse, identity is (kind, paths): two unrelated findings of one kind that both cited such a name
    collapsed to a single `finding_key`, and the dedupe dropped the second with no log line.
    """
    assert generic not in snapshot_paths(_Stub())


def test_a_real_dotted_address_is_still_accepted_in_both_forms() -> None:
    keys = snapshot_paths(_Stub())
    assert "liability.3.unpaid_balance" in keys
    assert "mismo.facts.liability.3.unpaid_balance" in keys


# --------------------------------------------------------------------------------------------- #
# 4 + 5. The prose guards
# --------------------------------------------------------------------------------------------- #
def _summary(**over: object) -> FactSummary:
    base: dict[str, object] = {
        "rule_name": "Derogatory seasoning",
        "subject": "a tradeline",
        "problem": "A derogatory event needs seasoning.",
        "fix": "Upload the tri-merge credit report.",
    }
    base.update(over)
    return FactSummary(**base)  # type: ignore[arg-type]


def test_a_document_kind_slug_that_is_a_number_is_not_a_licensed_figure() -> None:
    """`document_kinds_on_file` reaches the allow-list through `to_json()`, and slugs carry digits.

    A file holding a 1099 licensed the literal "1099" anywhere in the output — the same leak the
    `documents_on_file` exclusion two lines above was written to close, on the newer field.
    """
    summary = _summary(document_kinds_on_file=("1099", "pay_stub"))
    unsupported = unsupported_numbers(summary, Composition("Verify 1099 income.", "why"))

    assert "1099" in unsupported, "a kind label must not license the number it looks like"


# --------------------------------------------------------------------------------------------- #
# 6. A disagreement keeps its multiplicity
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("rule_id", ["ID-1", "ID-2", "ID-3", "ID-4", "IN-5"])
def test_a_disagreement_states_how_many_sources_disagreed(rule_id: str) -> None:
    """Deduping `{sources}` by document TYPE erased the multiplicity a disagreement IS.

    Two pay stubs carrying different SSNs rendered "the SSN differs across sources (pay stub)" — one
    named source for a disagreement, which reads as a document contradicting itself and names neither
    of the two to compare. The fired templates carried no `{count}` either, so the number was not
    recovering what the dedupe removed.
    """
    spec = load_rule_spec(rule_id)
    assert spec.consistency is not None
    disagree = spec.consistency.on_disagree
    assert "{count}" in disagree.reasoning, (
        f"{rule_id}: a disagreement must say how many sources disagreed — "
        "the sources are no longer deduped there, and the number is the other half"
    )


def test_the_dedupe_survives_for_agreement() -> None:
    """The satisfied templates are why the dedupe exists: five documents of two kinds read
    "pay stub, W-2", not "pay stub, pay stub, W-2, W-2, W-2"."""
    spec = load_rule_spec("ID-1")
    assert spec.consistency is not None
    assert "{sources}" in spec.consistency.on_agree.reasoning
    assert "{count}" in spec.consistency.on_agree.reasoning


# --------------------------------------------------------------------------------------------- #
# 7. One borrower-name builder
# --------------------------------------------------------------------------------------------- #
def test_both_paths_resolve_a_borrower_name_through_one_builder() -> None:
    """The list said "Aditya Talluri" and the finding's own text said "Aditya K Talluri".

    LP-605 set out to make the compose path and the read path use "the same resolver, with the same
    maps" and got the maps: the API built `f"{first} {last}"` while the composer used
    `Borrower.full_name`, which includes the middle name.
    """
    from app.api import verification as api
    from app.services import finding_prose as prose
    from app.services.borrowers import borrower_display_names

    assert api.borrower_display_names is borrower_display_names
    assert prose.borrower_display_names is borrower_display_names
    assert not hasattr(prose, "_active_borrower_names"), (
        "the private snapshot helper loaded whole ORM rows, SSN included, to build a name"
    )
