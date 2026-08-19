"""LP-486 / ADR-376 — CR-12 (disputed accounts) and the CLOSED-VOCABULARY ABSTAIN pattern.

⚠️ THE FINDING THIS RULE IS BUILT AROUND. The credit report's ``is_disputed`` field carries a clean ``Y``/
``N`` on the two bench reports (34 N, 1 Y across 35 rows) and FREE TEXT on LF-96SV — a different bureau
format — where the same field holds ``ACCOUNT IN FORBEARANCE``, ``ACCOUNT CLOSED BY CREDIT GRANTOR`` and
``ACCOUNT PREVIOUSLY IN DISPUTE-NOW RESOLVED-REPORTED BY SUBSCRIBER``. **ONE FIELD, TWO ENCODINGS.**

A rule written as ``is_disputed == "Y"`` would read the free-text report as NOT disputed — a silent false
negative on a fraud-adjacent rule that ships ``auto``. So the producer recognises a CLOSED vocabulary and
ABSTAINS on anything else; the gate turns that into ``couldnt_check``.

⚠️ ``PREVIOUSLY IN DISPUTE - NOW RESOLVED`` is in NEITHER list on purpose. It must abstain, not resolve to
"no": reading a resolution the bureau did not state is an inference, and this rule does not infer.
"""

from __future__ import annotations

import pytest
from app.verification.rule_engine.enumerators import LiabilityRow
from app.verification.rule_engine.gate import GateStatus, evaluate_gate
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.derived import (
    _DISPUTE_PHRASES,
    _NOT_DISPUTE_PHRASES,
    _liability_dispute_status,
)

_UNKNOWN = "unknown"


def _row(value: str | None) -> LiabilityRow:
    fields = (
        {} if value is None else {"is_disputed": Field.present(value, source=FieldSource.EXTRACTED)}
    )
    return LiabilityRow(
        subject_id="lst-x",
        source="credit_report_reported",
        fields=fields,
        values={},
        origin="lst-x",
        unresolved_reason=None,
        snapshot=None,  # type: ignore[arg-type]
    )


def _status(value: str | None) -> str:
    result, _ = _liability_dispute_status(None, "lst-x", _row(value))  # type: ignore[arg-type]
    return str(result)


# --------------------------------------------------------------------------- #
# The two REAL encodings, from stored data
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("value", "expected"), [("Y", "yes"), ("N", "no")])
def test_the_bench_reports_clean_flag(value: str, expected: str) -> None:
    """The two bench credit reports: 34 N + 1 Y across 35 rows."""
    assert _status(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ACCOUNT IN FORBEARANCE", "no"),
        ("ACCOUNT CLOSED BY CREDIT GRANTOR", "no"),
        # ⚠️ THE CASE THIS RULE EXISTS FOR — verbatim from LF-96SV. Unrecognised → ABSTAIN.
        ("ACCOUNT PREVIOUSLY IN DISPUTE-NOW RESOLVED-REPORTED BY SUBSCRIBER", _UNKNOWN),
    ],
)
def test_lf96sv_free_text_format(value: str, expected: str) -> None:
    """⚠️ THE MOST IMPORTANT TEST IN THE TICKET. Real values from LF-96SV's bureau format. The resolved-
    dispute wording must abstain — never `no`, which would be an inference the report did not state."""
    assert _status(value) == expected


def test_the_resolved_dispute_wording_is_not_read_as_undisputed() -> None:
    assert _status("PREVIOUSLY IN DISPUTE-NOW RESOLVED") == _UNKNOWN
    assert _status("PREVIOUSLY IN DISPUTE-NOW RESOLVED") != "no"


# --------------------------------------------------------------------------- #
# The closed vocabulary, exhaustively
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "phrase",
    [
        "account disputed by consumer",
        "consumer disputes this account",
        "dispute in progress",
        "account information disputed by consumer",
        "consumer disputes account information",
    ],
)
def test_every_dispute_phrase_is_recognised(phrase: str) -> None:
    assert _status(phrase) == "yes"


@pytest.mark.parametrize(
    "phrase",
    [
        "ACCOUNT IN FORBEARANCE",
        "ACCOUNT CLOSED BY CREDIT GRANTOR",
        "PAID ACCOUNT",
        "TRANSFERRED",
        "ACCOUNT CLOSED",
        "DEFERRED",
    ],
)
def test_every_account_status_remark_is_not_a_dispute(phrase: str) -> None:
    assert _status(phrase) == "no"


@pytest.mark.parametrize(
    "value",
    ["", "   ", "SOMETHING THE BUREAU INVENTED", "disputed?", "see remarks"],
)
def test_anything_unrecognised_abstains(value: str) -> None:
    """⚠️ Never `no`. An unfamiliar encoding is the case that must not silently clear."""
    assert _status(value) == _UNKNOWN


def test_absent_field_abstains_never_no() -> None:
    assert _status(None) == _UNKNOWN


@pytest.mark.parametrize(
    "value",
    ["  account   Disputed BY consumer ", "ACCOUNT DISPUTED BY CONSUMER", "Dispute In Progress"],
)
def test_case_and_whitespace_are_normalised(value: str) -> None:
    """Case-fold + collapse whitespace is the ONLY normalisation — no stemming, no fuzzy match."""
    assert _status(value) == "yes"


def test_normalisation_does_not_stem_or_fuzzy_match() -> None:
    """A near-miss is still a miss: the rule abstains rather than guessing at intent."""
    assert _status("account dispute by consumer") == _UNKNOWN  # 'dispute' not 'disputed'
    assert _status("consumer disputed this account") == _UNKNOWN


# --------------------------------------------------------------------------- #
# ⚠️ Spec ↔ producer: the vocabulary cannot drift
# --------------------------------------------------------------------------- #
def test_cr12_vocabulary_matches_the_spec() -> None:
    """The spec's reference_values is where Priya edits; the recipe is what runs. If they ever diverge,
    the rule stops matching the domain ruling — silently. This pins them identical."""
    values = load_rule_spec("CR-12").reference_values.values
    assert set(values["dispute_phrases"].split("|")) == set(_DISPUTE_PHRASES)
    assert set(values["not_dispute_phrases"].split("|")) == set(_NOT_DISPUTE_PHRASES)


def test_the_two_vocabularies_do_not_overlap() -> None:
    assert not (_DISPUTE_PHRASES & _NOT_DISPUTE_PHRASES)


# --------------------------------------------------------------------------- #
# The rule body and the gate
# --------------------------------------------------------------------------- #
def test_the_catch_all_is_an_abstain_not_a_pass() -> None:
    """⚠️ CR-12 ships `auto`. A `satisfied` default would turn any future third value into a silent
    all-clear with no human in the loop."""
    outcomes = load_rule_spec("CR-12").deterministic.outcomes
    assert [o.verdict for o in outcomes] == ["fired", "satisfied", "couldnt_check"]
    assert outcomes[-1].default is True


def test_missing_input_gates_to_couldnt_check() -> None:
    """Proven by CODE PATH: gate.py routes an absent tag and an "unknown" tag to couldnt_check BEFORE the
    rule body runs, so a file with no credit report can never read as "no disputed accounts"."""
    spec = load_rule_spec("CR-12")
    assert "liab.is_disputed" in spec.deterministic.gated_tags
    assert (
        evaluate_gate({"liab.is_disputed": None}, confidence_floor=None).status
        is GateStatus.COULDNT_CHECK
    )
    unknown = Tag(
        value=_UNKNOWN,
        confidence=None,
        reasoning="unrecognised",
        source_facts=("x",),
        produced_by=TagProducedBy.DERIVED,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )
    assert (
        evaluate_gate({"liab.is_disputed": unknown}, confidence_floor=None).status
        is GateStatus.COULDNT_CHECK
    )


def test_cr12_does_not_touch_dti_treatment() -> None:
    """Priya's scope boundary: CR-12 flags a dispute for review; whether the debt leaves DTI is the
    agency liability rule's call, not this rule's."""
    spec = load_rule_spec("CR-12")
    assert (
        spec.deterministic.load_bearing_tags
        == (
            "liab.creditor_name",  # LP-556 — names WHICH debt the finding is about (provenance, not gated)
            "liab.is_disputed",
        )
    )
    body = (spec.criteria + " " + (spec.reference_values.guideline_text or "")).lower()
    assert "does not decide" in body or "detection only" in body
