"""LP-122R — certify AS-5 (gift-letter) as completed rule #1 + freeze the shape.

This does NOT re-test the engine (LP-119/120/121 own that). It CERTIFIES AS-5's authored artifact:
its applicability in the version-controlled seed is the canonical wire shape, parses against the
``Applicability`` model (``extra="forbid"``), keeps the check-target discipline (the gift LETTER is
NOT a required input — its absence is the finding), and is validated by the LP-122R criterion. If a
later change breaks any of these, this freeze fails loudly.

The behavioural certification (four buckets, evaluator↔live-rule parity, end-to-end, provisional vs
validated) lives in ``test_applicability.py`` / ``test_evaluators.py`` / ``test_runner.py`` and is
referenced from ``docs/tickets/LP-122R.md``.
"""

import json

from app.services.rule_registry import DEFAULT_SEED_PATH
from app.verification.applicability.schema import Applicability

_AS5_RULE_ID = "xsrc.asset.gift_without_letter"

# The canonical AS-5 wire-format applicability (mirrors the LP-119 migration + the DB row).
_CANONICAL_APPLICABILITY = {
    "scope": {},
    "triggers": {
        "all": [
            {
                "kind": "entity_exists",
                "collection": "assets",
                "field": "is_gift",
                "op": "eq",
                "value": True,
            }
        ]
    },
    "required_inputs": [{"kind": "data_field", "path": "assets[].is_gift"}],
}


def _seed_rows() -> list[dict]:
    return json.loads(DEFAULT_SEED_PATH.read_text(encoding="utf-8"))


def _as5_row() -> dict:
    return next(r for r in _seed_rows() if r["rule_id"] == _AS5_RULE_ID)


def test_as5_seed_applicability_is_canonical() -> None:
    assert _as5_row()["applicability"] == _CANONICAL_APPLICABILITY


def test_as5_applicability_parses_under_extra_forbid() -> None:
    # Certifies zero validation errors — the shape the engine reads is well-formed.
    parsed = Applicability.model_validate(_as5_row()["applicability"])
    assert parsed == Applicability.model_validate(_CANONICAL_APPLICABILITY)


def test_as5_check_target_discipline() -> None:
    # The gift LETTER is the check-target (its absence is the finding, produced by the evaluator), so
    # it must NOT be a required input — otherwise a missing letter would be couldn't-check, not a finding.
    reqs = _as5_row()["applicability"]["required_inputs"]
    assert reqs == [{"kind": "data_field", "path": "assets[].is_gift"}]
    assert all(r["kind"] != "document" for r in reqs)


def test_as5_is_validated_by_the_criterion() -> None:
    # AS-5 has NO tunable numeric threshold (empty params) and reproduces the live verdict → validated.
    row = _as5_row()
    assert row["validated"] is True
    assert row["params"] == {}  # no Priya-threshold to confirm — the criterion for validated=true
    assert row["enabled"] is True


def test_validated_criterion_is_narrow() -> None:
    # The criterion is applied ~123 times, so guard it: only Priya-confirmed thresholds + certified
    # no-threshold live-parity rules are validated. A new validated=true row must be a deliberate,
    # documented certification.
    validated = {r["rule_id"] for r in _seed_rows() if r["validated"]}
    assert validated == {
        "xsrc.income.stated_vs_documented",  # IN-1 (Priya-confirmed 5%)
        "xsrc.asset.large_deposit_unsourced",  # AS-1 (Priya-confirmed 50%)
        _AS5_RULE_ID,  # AS-5 (no threshold, live-verdict parity — LP-122R)
        "xsrc.income.employer_count_matches_items",  # LP-124R (no threshold, reproduces live)
    }
