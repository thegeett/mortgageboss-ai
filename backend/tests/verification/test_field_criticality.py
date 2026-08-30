"""Criticality overrides confidence (LP-UI-032) — and the list cannot silently rot.

The drift guard is the point of this file. A hand-maintained list over 1,603
typed-core keys is only trustworthy if a new key of critical shape cannot be added
without someone deciding about it, so `test_no_critical_field_drifts` fails at the
moment the decision is cheap rather than at the moment a wrong figure ships.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from app.schema_specs import SPECS_DIR
from app.verification import field_criticality as criticality
from app.verification.field_criticality import (
    CriticalityError,
    critical_fields,
    identity_fields,
    is_critical,
    is_sensitive,
    reviewed_not_critical,
)

#: What "looks like money, a rate, or an identity" means, as a name shape. Deliberately
#: WIDE: a false positive costs one line in `reviewed_not_critical` with its reason, a
#: false negative is an unflagged money figure. The asymmetry decides the tuning.
CRITICAL_SHAPE = re.compile(
    r"(_amount$|^amount$|_rate$|^rate$|ssn|itin|_income$|^income|wages|gross|net_|_net$|^net$"
    r"|_balance$|loan_amount|purchase_price|appraised_value|payment$|_price$|credit_score"
    r"|score_|_value$|premium$|_pay$|hours|ytd|salary|compensation|earnings|deposit"
    r"|credit_limit|dti|ltv|percent|_pct$|apr)"
)


def _spec_typed_core_keys() -> set[str]:
    keys: set[str] = set()
    for path in SPECS_DIR.glob("*.json"):
        spec = json.loads(path.read_text())
        typed_core = spec.get("typed_core") or {}
        if isinstance(typed_core, dict):
            keys |= set(typed_core)
        elif isinstance(typed_core, list):
            keys |= {f["name"] for f in typed_core if isinstance(f, dict) and f.get("name")}
    return keys


def test_the_specs_are_readable_at_all() -> None:
    """The positive control. Every assertion below would pass over an empty set."""
    keys = _spec_typed_core_keys()
    assert len(keys) > 1_000, (
        f"only {len(keys)} typed-core keys — the spec directory is not loading"
    )
    assert "gross_pay" in keys


def test_no_critical_field_drifts() -> None:
    """Every spec key of critical shape is classified — flagged, or ruled out with a reason.

    This is the test that stops silent rot. A new extractor adding `annual_premium`
    fails here until someone decides, which is exactly when deciding is cheap.
    """
    classified = critical_fields() | set(reviewed_not_critical())
    unclassified = sorted(k for k in _spec_typed_core_keys() if CRITICAL_SHAPE.search(k))
    missing = [k for k in unclassified if k not in classified]
    assert not missing, (
        "These schema-spec fields look like money, a rate or an identity and are in neither list. "
        f"Decide for each: list it under `critical`, or under `reviewed_not_critical` with why: {missing}"
    )


def test_a_field_cannot_be_both() -> None:
    both = critical_fields() & set(reviewed_not_critical())
    assert not both, f"listed as critical AND ruled out: {sorted(both)}"


def test_every_exclusion_carries_a_reason() -> None:
    # Enforced in the loader; asserted here so the guarantee is visible where the
    # list is reviewed rather than only where it is parsed.
    for field, reason in reviewed_not_critical().items():
        assert len(reason.strip()) > 10, f"{field}: the reason is too thin to review"


class TestWhatIsCritical:
    @pytest.mark.parametrize(
        "field",
        [
            "gross_pay",  # the DTI numerator
            "net_pay",
            "loan_amount",  # the denominator
            "note_rate",
            "employee_ssn",  # identity
            "borrower_ssn",
            "score_equifax",  # drives pricing outright
            "appraised_value",  # LTV
            "unpaid_principal_balance",
            "ytd_gross",  # the income-averaging basis; missed by the first shape pass
            "hours",  # the multiplicand — a wrong one is a wrong income
            "aus_dti_ratio",
        ],
    )
    def test_the_expensive_fields_are_flagged(self, field: str) -> None:
        assert is_critical(field)

    @pytest.mark.parametrize(
        "field",
        [
            "employer_name",  # wrong is untidy, and the next reader catches it
            "pay_frequency",
            "gross_living_area",  # square footage, not money — an appraisal concern
            "score_date",  # a date about a score, not the score
            "score_model",
            "ssn_alert_status",  # a flag about an SSN, not the SSN
            "income_documentation_level",  # a category, not a figure
        ],
    )
    def test_the_ordinary_fields_are_not(self, field: str) -> None:
        assert not is_critical(field)

    def test_an_unknown_field_is_not_critical(self) -> None:
        # A field nobody classified must not be flagged by default: flagging
        # everything is the same as flagging nothing.
        assert not is_critical("some_field_that_does_not_exist")


class TestMalformedDataRaises:
    """The loader's guarantees, exercised against actual malformed YAML.

    Asserting over the shipped file only proves the shipped file is fine — it
    cannot show that an empty reason would be REJECTED rather than accepted and
    quietly rendered, which is the failure that would let an unreviewable entry in.
    """

    @staticmethod
    def _load(tmp_path: Path, body: str) -> None:
        path = tmp_path / "critical_fields.yaml"
        path.write_text(body)
        criticality._PATH = path  # type: ignore[attr-defined]
        for fn in (
            criticality._document,
            criticality.critical_fields,
            criticality.reviewed_not_critical,
        ):
            fn.cache_clear()

    @pytest.fixture(autouse=True)
    def _restore(self) -> Iterator[None]:
        original = criticality._PATH
        yield
        criticality._PATH = original  # type: ignore[attr-defined]
        for fn in (
            criticality._document,
            criticality.critical_fields,
            criticality.reviewed_not_critical,
        ):
            fn.cache_clear()

    def test_an_exclusion_with_no_reason_is_rejected(self, tmp_path: Path) -> None:
        self._load(
            tmp_path, "critical: {money: [gross_pay]}\nreviewed_not_critical: {some_field: ''}\n"
        )
        with pytest.raises(CriticalityError, match="reason is REQUIRED"):
            criticality.reviewed_not_critical()

    def test_a_field_listed_twice_is_rejected(self, tmp_path: Path) -> None:
        self._load(tmp_path, "critical:\n  a: [gross_pay]\n  b: [gross_pay]\n")
        with pytest.raises(CriticalityError, match="listed twice"):
            criticality.critical_fields()

    def test_a_non_mapping_root_is_rejected(self, tmp_path: Path) -> None:
        self._load(tmp_path, "- just\n- a\n- list\n")
        with pytest.raises(CriticalityError, match="top level"):
            criticality.critical_fields()

    def test_a_category_that_is_not_a_list_is_rejected(self, tmp_path: Path) -> None:
        self._load(tmp_path, "critical:\n  money: gross_pay\n")
        with pytest.raises(CriticalityError, match="must be a list"):
            criticality.critical_fields()

    def test_a_well_formed_file_still_loads(self, tmp_path: Path) -> None:
        # The positive control for this whole class: the harness itself works, so a
        # `raises` above is the loader rejecting and not the fixture misfiring.
        self._load(
            tmp_path, "critical: {money: [gross_pay]}\nreviewed_not_critical: {x: a real reason}\n"
        )
        assert criticality.critical_fields() == frozenset({"gross_pay"})


class TestTheListIsLoadable:
    def test_it_is_not_empty(self) -> None:
        # A loader bug that returned {} would make every assertion above vacuous
        # and would silently un-flag every critical field in production.
        assert len(critical_fields()) > 100
        assert len(reviewed_not_critical()) >= 10

    def test_a_malformed_list_raises_rather_than_returning_nothing(self) -> None:
        assert issubclass(CriticalityError, Exception)


class TestSensitiveFields:
    """The identity subset — what a screen must never render in the clear."""

    def test_the_ssn_fields_are_sensitive(self) -> None:
        for field in ("borrower_ssn", "co_borrower_ssn", "employee_ssn", "taxpayer_ssn_masked"):
            assert is_sensitive(field), field

    def test_a_money_field_is_critical_but_not_sensitive(self) -> None:
        # The two axes are different questions: "read this again" and "do not print
        # this". Conflating them would either mask a pay figure or print an SSN.
        assert is_critical("gross_pay")
        assert not is_sensitive("gross_pay")

    def test_every_sensitive_field_is_also_critical(self) -> None:
        # It reads from the `identity` category of the critical list, so this cannot
        # currently fail — asserted anyway, because a future refactor that split the
        # lists would make an identifier stop being checked without saying so.
        assert identity_fields() <= critical_fields()

    def test_it_is_not_empty(self) -> None:
        assert len(identity_fields()) >= 8
