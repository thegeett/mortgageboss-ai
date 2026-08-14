"""LP-485 — the date-compare family: CL-1 (rate lock), CR-13 (credit age), PR-6 (appraisal age).

⚠️ CALENDAR MONTHS, NOT DAY APPROXIMATIONS. Fannie states both validity windows in months (B1-1-03: four
months; B4-1.2-04: twelve months / four for an update). A 30-day approximation differs from the calendar by
up to three days at four months — enough to pass a document the guide fails. ``_age_months_ceiling`` counts
COMPLETE months and these pin the boundary behaviour.

⚠️ PR-6 HAS THREE BANDS, and the middle one is a CONDITION, not a failure: an appraisal at six months is
usable WITH an update (Form 1004D). Reporting it ``fired`` would tell a processor the file is broken when it
needs one more document. These pin that it is ``needs_review``, and that the band ordering is load-bearing.

⚠️ NEVER CLEAR ON A MISSING DOCUMENT. A file with no loan estimate / credit report / appraisal must reach
couldnt_check, never "the lock is fine" / "the credit is current" / "the appraisal is current". Proven here
at the recipe layer (the tag abstains to ``unknown``) and at the gate layer (an unknown tag → couldnt_check).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from app.verification.rule_engine.gate import GateStatus, evaluate_gate
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.model import (
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.derived import (
    _age_months_ceiling,
    _appraisal_age_months,
    _credit_report_age_months,
    _rate_lock_days_to_closing,
)

_UNKNOWN = "unknown"


def _tag(value: str) -> Tag:
    return Tag(
        value=value,
        confidence=None,
        reasoning="test",
        source_facts=("x",),
        produced_by=TagProducedBy.PARSED,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _snapshot(**tags_by_subject: dict[str, Tag]) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        documents=DocumentsSection.present([]),
        mismo=MismoSection.present({}),
        tags=TagsSection.present(dict(tags_by_subject)),
    )


def _with(**dates: str) -> Snapshot:
    """A snapshot carrying each named tag on its own document subject (the real keying)."""
    mapping = {
        "closing": "contract.closing_date",
        "lock": "rate_lock.expiration",
        "credit": "credit.report_date",
        "appraisal": "property.appraisal_date",
    }
    return _snapshot(
        **{f"doc-{k}": {mapping[k]: _tag(v)} for k, v in dates.items()}  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- #
# Calendar-month arithmetic — the reason this family does not use day counts
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("earlier", "later", "expected"),
    [
        (date(2026, 4, 1), date(2026, 8, 1), 4),  # exactly four months — inclusive, still 4
        (date(2026, 4, 2), date(2026, 8, 1), 4),  # 3m30d — a PARTIAL month ROUNDS UP
        (date(2025, 8, 1), date(2026, 8, 1), 12),  # a full year
        (date(2026, 8, 1), date(2026, 8, 1), 0),  # same day
        (date(2026, 8, 1), date(2026, 7, 1), -1),  # later precedes earlier → negative
        (date(2026, 1, 31), date(2026, 2, 28), 1),  # month-end: a full month HAS elapsed
    ],
)
def test_age_months_ceiling(earlier: date, later: date, expected: int) -> None:
    assert _age_months_ceiling(earlier, later) == expected


def test_four_calendar_months_is_not_120_days() -> None:
    """The boundary the guideline actually draws. 04-01 -> 08-01 is 122 days but exactly 4 months; a
    120-day rule would FIRE on it. This is why the tag counts months."""
    earlier, later = date(2026, 4, 1), date(2026, 8, 1)
    assert (later - earlier).days == 122
    assert _age_months_ceiling(earlier, later) == 4  # within a four-month window


@pytest.mark.parametrize(
    ("pulled", "closing", "days_old"),
    [
        (date(2026, 3, 25), date(2026, 8, 1), 129),  # 4m 7d
        (date(2026, 3, 2), date(2026, 8, 1), 152),  # 4m 30d — the worst case
        (date(2026, 3, 31), date(2026, 8, 1), 123),  # 4m 1d — the first day over
    ],
)
def test_a_document_past_its_window_does_not_clear_it(
    pulled: date, closing: date, days_old: int
) -> None:
    """⚠️ THE REPORTED FN. Flooring to COMPLETE months while the rules compare with strict ``>`` meant
    ``floor(age) > 4`` only fired at FIVE complete months — so a credit report up to 4 months 30 days old
    (152 days) returned 4 and CLEARED a four-month limit. Every case here is genuinely over four months
    and must exceed the limit, not sit on it."""
    assert (closing - pulled).days == days_old
    assert _age_months_ceiling(pulled, closing) > 4


def test_exactly_at_the_limit_still_passes() -> None:
    """The other half: rounding up must not make an exactly-conforming document fail. "No more than four
    months" is INCLUSIVE, so a document exactly four months old sits AT the limit, not over it."""
    assert _age_months_ceiling(date(2026, 4, 1), date(2026, 8, 1)) == 4
    assert not _age_months_ceiling(date(2026, 4, 1), date(2026, 8, 1)) > 4
    assert _age_months_ceiling(date(2025, 8, 1), date(2026, 8, 1)) == 12  # PR-6's 12-month gate
    assert not _age_months_ceiling(date(2025, 8, 1), date(2026, 8, 1)) > 12


# --------------------------------------------------------------------------- #
# CL-1 — rate lock vs closing
# --------------------------------------------------------------------------- #
def test_lock_expiring_after_closing_is_positive() -> None:
    value, reason = _rate_lock_days_to_closing(
        _with(closing="2026-09-01", lock="2026-09-15"), "loan", None
    )
    assert value == "14" and "margin 14 day(s)" in reason


def test_lock_expiring_before_closing_is_negative() -> None:
    value, reason = _rate_lock_days_to_closing(
        _with(closing="2026-09-15", lock="2026-09-01"), "loan", None
    )
    # ⚠️ The reasoning must NOT also say "before" — `days` is signed, so "-14 day(s) BEFORE closing" is
    # the double negative the CL-1 spec was corrected for. This string is processor-visible too.
    assert value == "-14"
    assert "margin -14 day(s)" in reason
    assert "BEFORE" not in reason


def test_no_loan_estimate_abstains_never_zero() -> None:
    """⚠️ A file with no loan estimate must NOT read as 'the lock is fine'. Absent ≠ 0."""
    value, reason = _rate_lock_days_to_closing(_with(closing="2026-09-01"), "loan", None)
    assert value == _UNKNOWN
    assert "rate lock expiration" in reason


def test_no_closing_date_abstains() -> None:
    value, reason = _rate_lock_days_to_closing(_with(lock="2026-09-01"), "loan", None)
    assert value == _UNKNOWN and "closing date" in reason


# --------------------------------------------------------------------------- #
# CR-13 — credit report age
# --------------------------------------------------------------------------- #
def test_credit_report_age_in_months() -> None:
    value, _ = _credit_report_age_months(
        _with(credit="2026-04-01", closing="2026-08-01"), "loan", None
    )
    assert value == "4"


def test_no_credit_report_abstains_never_zero() -> None:
    value, reason = _credit_report_age_months(_with(closing="2026-08-01"), "loan", None)
    assert value == _UNKNOWN and "credit report" in reason


# --------------------------------------------------------------------------- #
# PR-6 — appraisal age
# --------------------------------------------------------------------------- #
def test_appraisal_age_in_months() -> None:
    value, _ = _appraisal_age_months(
        _with(appraisal="2025-08-01", closing="2026-08-01"), "loan", None
    )
    assert value == "12"


def test_no_appraisal_abstains_never_zero() -> None:
    value, reason = _appraisal_age_months(_with(closing="2026-08-01"), "loan", None)
    assert value == _UNKNOWN and "appraisal" in reason


# --------------------------------------------------------------------------- #
# Disagreement — two documents, two different dates → no single answer
# --------------------------------------------------------------------------- #
def test_documents_disagreeing_on_closing_date_abstain() -> None:
    snapshot = _snapshot(
        d1={"contract.closing_date": _tag("2026-09-01")},
        d2={"contract.closing_date": _tag("2026-10-01")},
        d3={"rate_lock.expiration": _tag("2026-09-15")},
    )
    value, reason = _rate_lock_days_to_closing(snapshot, "loan", None)
    assert value == _UNKNOWN and "disagree" in reason


# --------------------------------------------------------------------------- #
# ⚠️ PR-6's THREE BANDS — read off the spec's own ordered outcomes
# --------------------------------------------------------------------------- #
def _pr6_band(age_months: int) -> str:
    """Which outcome PR-6's ordered, first-match-wins body selects at a given age."""
    spec = load_rule_spec("PR-6")
    values = spec.reference_values.values
    max_months = int(values["max_appraisal_age_months"])
    update_after = int(values["appraisal_update_after_months"])
    for outcome in spec.deterministic.outcomes:
        if outcome.default:
            return outcome.verdict
        cmp = outcome.when_compare
        assert cmp is not None
        right = max_months if cmp.right == "max_months" else update_after
        if age_months > right:
            return outcome.verdict
    raise AssertionError("no outcome matched and no default")


@pytest.mark.parametrize(
    ("age_months", "expected"),
    [
        (0, "satisfied"),
        (4, "satisfied"),  # exactly four months needs no update
        (5, "needs_review"),  # ⚠️ a CONDITION, not a failure
        (11, "needs_review"),
        (12, "needs_review"),  # twelve months is still within the limit
        (13, "fired"),  # beyond twelve → a NEW appraisal
    ],
)
def test_pr6_three_bands(age_months: int, expected: str) -> None:
    assert _pr6_band(age_months) == expected


def test_pr6_middle_band_is_not_a_fired_verdict() -> None:
    """⚠️ The whole point of the middle band: an appraisal needing an update is a condition to satisfy,
    not a broken file. If this ever becomes `fired`, processors lose that distinction."""
    assert _pr6_band(6) == "needs_review"
    assert _pr6_band(6) != "fired"


def test_pr6_band_order_is_load_bearing() -> None:
    """The >12 band must be declared BEFORE the >4 band. Reversed, every stale appraisal would report
    'needs an update' and the new-appraisal requirement would never fire."""
    verdicts = [o.verdict for o in load_rule_spec("PR-6").deterministic.outcomes]
    assert verdicts == ["fired", "needs_review", "satisfied"]


# --------------------------------------------------------------------------- #
# ⚠️ The gate: an unknown tag → couldnt_check, for every rule in the family
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("rule_id", "tag_id"),
    [
        ("CL-1", "rate_lock.days_to_closing"),
        ("CR-13", "credit.report_age_months_at_closing"),
        ("PR-6", "property.appraisal_age_months_at_closing"),
    ],
)
def test_missing_input_gates_to_couldnt_check(rule_id: str, tag_id: str) -> None:
    """Proven by CODE PATH: gate.py routes an ABSENT tag and an "unknown" tag to couldnt_check BEFORE any
    rule body runs — so none of these can report a pass on a file that lacks its document."""
    spec = load_rule_spec(rule_id)
    assert tag_id in spec.deterministic.gated_tags
    assert evaluate_gate({tag_id: None}, confidence_floor=None).status is GateStatus.COULDNT_CHECK
    assert (
        evaluate_gate({tag_id: _tag(_UNKNOWN)}, confidence_floor=None).status
        is GateStatus.COULDNT_CHECK
    )


# --------------------------------------------------------------------------- #
# The thresholds are the researched ones, with their citations
# --------------------------------------------------------------------------- #
def test_thresholds_are_the_cited_values() -> None:
    cr13 = load_rule_spec("CR-13")
    assert cr13.reference_values.values["max_credit_report_age_months"] == "4"
    assert "B1-1-03" in (cr13.guideline_reference or "")
    assert "04/02/2025" in (cr13.guideline_reference or "")
    pr6 = load_rule_spec("PR-6")
    assert pr6.reference_values.values["max_appraisal_age_months"] == "12"
    assert pr6.reference_values.values["appraisal_update_after_months"] == "4"
    assert "B4-1.2-04" in (pr6.guideline_reference or "")
    assert "06/04/2025" in (pr6.guideline_reference or "")


def test_cl1_carries_no_domain_threshold() -> None:
    """CL-1 is a date ordering: `zero` is a comparison boundary, not a number anyone signs off."""
    spec = load_rule_spec("CL-1")
    assert set(spec.reference_values.values) == {"zero"}
    assert spec.reference_values.threshold_needs_signoff is False


# --------------------------------------------------------------------------- #
# The DATE-SELECTION POLICY is per tag — the reported regression
# --------------------------------------------------------------------------- #
def test_an_appraisal_update_does_not_reset_the_twelve_month_clock() -> None:
    """⚠️ THE REGRESSION. B4-1.2-04 measures BOTH bands from the ORIGINAL effective date, and the
    classifier has one `appraisal` type — so a Form 1004D update is just a second appraisal date. Taking
    the MOST RECENT let the update reset the clock: a fifteen-month-old value reported as ~2 months and
    PR-6 defaulted to `satisfied`, contradicting its own "a NEW appraisal is required" band."""
    snap = _snapshot(
        **{
            "doc-orig": {"property.appraisal_date": _tag("2025-05-01")},
            "doc-1004d": {"property.appraisal_date": _tag("2026-06-01")},
            "doc-contract": {"contract.closing_date": _tag("2026-08-01")},
        }
    )
    value, reason = _appraisal_age_months(snap, "loan", None)
    assert value == "15", reason  # aged from the ORIGINAL, not the update
    assert int(value) > 12  # PR-6's "new appraisal required" band


def test_a_superseded_loan_estimate_cannot_mask_an_expired_lock() -> None:
    """⚠️ THE REGRESSION. `rate_lock.expiration`'s VALUE is an expiry, not a document date, so taking the
    latest meant "the most permissive lock anywhere in the file": an initial LE locked through September
    hid a re-lock that expired in July, and CL-1 passed an expired lock."""
    snap = _snapshot(
        **{
            "doc-le1": {"rate_lock.expiration": _tag("2026-09-30")},
            "doc-le2": {"rate_lock.expiration": _tag("2026-07-15")},
            "doc-contract": {"contract.closing_date": _tag("2026-08-01")},
        }
    )
    value, _ = _rate_lock_days_to_closing(snap, "loan", None)
    assert int(value) < 0, "the soonest expiry governs — the lock lapses before closing"


def test_a_credit_re_pull_DOES_reset_the_clock() -> None:
    """The other half: most-recent-wins is correct here because B1-1-03 SAYS so. A re-pull is the answer,
    not a contradiction — this is why the policy is per tag rather than one rule for the family."""
    snap = _snapshot(
        **{
            "doc-old": {"credit.report_date": _tag("2026-01-05")},
            "doc-new": {"credit.report_date": _tag("2026-07-20")},
            "doc-contract": {"contract.closing_date": _tag("2026-08-01")},
        }
    )
    value, _ = _credit_report_age_months(snap, "loan", None)
    assert value == "1"  # the fresh pull governs, not the stale one
