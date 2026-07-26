"""The golden eval cases - crafted fixtures + LABELED expected outcomes (LP-317 Phase 2).

Each :class:`FixtureTxn` declares one transaction's raw facts, the AI judgment a good model SHOULD
return (the keyless stub replays it - see :mod:`app.verification.eval.stubs`), and the labels the
harness scores against:

* TAG level - ``is_money_in`` / ``apparent_category`` / ``has_source`` (the stubbed AI answers) and
  ``expect_strength`` (the LP-314a strength the DETERMINISTIC derivation must produce).
* FINDING level - ``expect_outcome`` (the AS-1 evaluation outcome for that subject, or ``None`` when
  the subject is not applicable / not persisted).

In keyless mode the stub replays the AI answers, so the meaningful assertions are the DERIVED
strength and the finding outcome (candidate search + gate + rule + arithmetic - none of it stubbed).
Live mode scores the real AI's tags against these same labels (calibration, Phase 3).

Descriptions double as the stub lookup key, so each is UNIQUE within its case and redaction-safe (no
9+-digit runs - LP-302a would otherwise rewrite it and break the key). Every crafted case uses a
gross monthly income of 10000, so AS-1's spec 50%% threshold is a round 5000: a "large" deposit is
> 5000; the needs-review boundary is >= 5000.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Every crafted case: income 10000 → AS-1's 50% threshold = 5000.
CASE_INCOME = "10000"


@dataclass(frozen=True)
class FixtureTxn:
    """One fixture transaction: raw facts + the stubbed AI judgment + the labels to score."""

    key: str  # the (unique, redaction-safe) description - also the stub lookup key
    amount: str
    date: str
    transaction_type: str  # the RAW label (deposit/withdrawal/transfer/ach/wire/"") - never gates
    is_money_in: str  # stubbed Stage-A answer: in | out | unknown
    apparent_category: str  # stubbed Stage-A answer (from APPARENT_CATEGORY_VALUES)
    # Stubbed Stage-B answer (money-in subjects only; None for a debit, never judged):
    has_source: str | None = None  # yes | no | unknown
    cite_candidate: bool = False  # a "yes" that CITES a matched debit (source_index=1) vs a claim
    # Expected DERIVED strength (LP-314a) - scored at the TAG level (None if not a money-in subject):
    expect_strength: str | None = None  # verified | intrinsic | self_asserted | none
    # Expected AS-1 outcome for this subject - scored at the FINDING level (None = no finding):
    expect_outcome: str | None = None  # open | satisfied | needs_review | couldnt_check


@dataclass(frozen=True)
class EvalCase:
    """One golden case: a labeled fixture (or a frozen real snapshot) + coverage metadata."""

    case_id: str
    title: str
    level: str  # "finding" | "tag" | "real"
    txns: tuple[FixtureTxn, ...] = ()
    income: str | None = CASE_INCOME
    # Both-directions coverage (Phase 5): a case that MUST fire vs one that must NOT falsely fire.
    must_fire: bool = False
    no_false_fire: bool = False
    # case 12 only - load a frozen real tagged snapshot instead of building one from ``txns``.
    fixture_snapshot: str | None = None
    # case 12 only - the aggregate + per-strength expectations asserted on the real trace.
    expect_real: dict[str, int] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# FINDING-LEVEL cases (1-7)
# --------------------------------------------------------------------------- #

_CASE_1 = EvalCase(
    case_id="1",
    title="FIRES - large UNSOURCED transfer (the fraud case LF-6T3N structurally lacks)",
    level="finding",
    must_fire=True,
    txns=(
        FixtureTxn(
            key="TRANSFER INBOUND NO ORIGIN",
            amount="40000.00",
            date="2026-05-10",
            transaction_type="transfer",
            is_money_in="in",
            apparent_category="transfer_own",
            has_source="no",  # bare transfer, no matching debit, no income signal → unsourced
            expect_strength="none",
            expect_outcome="open",
        ),
    ),
)

_CASE_2 = EvalCase(
    case_id="2",
    title="NO FIRE - large VERIFIED transfer (matching own-account debit)",
    level="finding",
    no_false_fire=True,
    txns=(
        FixtureTxn(
            key="ONLINE TRANSFER FROM SAVINGS",
            amount="60000.00",
            date="2026-05-12",
            transaction_type="transfer",
            is_money_in="in",
            apparent_category="transfer_own",
            has_source="yes",
            cite_candidate=True,  # a real matched debit is present → the judge cites it
            expect_strength="verified",
            expect_outcome="satisfied",
        ),
        FixtureTxn(
            key="ONLINE TRANSFER TO CHECKING",
            amount="60000.00",
            date="2026-05-11",  # posts the day BEFORE the deposit - a genuine paper trail
            transaction_type="transfer",
            is_money_in="out",
            apparent_category="transfer_own",
        ),
    ),
)

_CASE_3 = EvalCase(
    case_id="3",
    title="NEEDS_REVIEW - large SELF-ASSERTED transfer (claim, no matching debit)",
    level="finding",
    no_false_fire=True,
    txns=(
        FixtureTxn(
            key="TRANSFER FROM MY BROKERAGE",
            amount="30000.00",
            date="2026-05-14",
            transaction_type="transfer",
            is_money_in="in",
            apparent_category="transfer_own",
            has_source="yes",  # the description CLAIMS a source…
            cite_candidate=False,  # …but no matching debit → the claim rests on the description alone
            expect_strength="self_asserted",
            expect_outcome="needs_review",
        ),
    ),
)

_CASE_4 = EvalCase(
    case_id="4",
    title="NO FIRE - INTRINSIC payroll (employer + PPD + employee)",
    level="finding",
    no_false_fire=True,
    txns=(
        FixtureTxn(
            key="PAYROLL ACME CORP PPD JOHN DOE",
            amount="18000.00",
            date="2026-05-01",
            transaction_type="deposit",
            is_money_in="in",
            apparent_category="payroll",
            has_source="yes",
            cite_candidate=False,  # income is intrinsic - no matching debit is needed
            expect_strength="intrinsic",
            expect_outcome="satisfied",
        ),
    ),
)

_CASE_5 = EvalCase(
    case_id="5",
    title="REGRESSION - unsourced deposit labeled NON-'credit' still fires (direction== bug)",
    level="finding",
    must_fire=True,
    txns=(
        FixtureTxn(
            # RAW transaction_type is NOT 'credit' - the old direction=='credit' filter would have
            # dropped it. is_money_in (an AI tag) resolves it to a deposit, so it IS evaluated.
            key="INCOMING ACH UNKNOWN ORIGIN",
            amount="25000.00",
            date="2026-05-16",
            transaction_type="ach",
            is_money_in="in",
            apparent_category="unknown",
            has_source="no",
            expect_strength="none",
            expect_outcome="open",
        ),
    ),
)

_CASE_6 = EvalCase(
    case_id="6",
    title="COULDNT_CHECK - large deposit with is_money_in=unknown (gate fails closed)",
    level="finding",
    txns=(
        FixtureTxn(
            key="AMBIGUOUS LINE ITEM",
            amount="20000.00",
            date="2026-05-18",
            transaction_type="",
            is_money_in="unknown",  # Stage A could not resolve direction → couldnt_check
            apparent_category="unknown",
            has_source=None,  # Stage B derives unknown from is_money_in unknown
            expect_outcome="couldnt_check",
        ),
    ),
)

_CASE_7 = EvalCase(
    case_id="7",
    title="INTRINSIC-NOT-A-LOOPHOLE - 'PAYROLL' word, NO markers → not auto-satisfied",
    level="finding",
    must_fire=True,
    txns=(
        FixtureTxn(
            # The description says PAYROLL but carries NO employer / PPD / employee markers, so a good
            # model does NOT categorize it payroll - it is unknown, unsourced → it FIRES, it is NOT
            # waved through as intrinsic income.
            key="PAYROLL",
            amount="22000.00",
            date="2026-05-20",
            transaction_type="deposit",
            is_money_in="in",
            apparent_category="unknown",
            has_source="no",
            expect_strength="none",
            expect_outcome="open",
        ),
    ),
)

# --------------------------------------------------------------------------- #
# TAG-LEVEL cases (8-11)
# --------------------------------------------------------------------------- #

_CASE_8 = EvalCase(
    case_id="8",
    title="TAG - is_money_in resolves label variance (credit/transfer/ACH/wire/'' → in; debit → out)",
    level="tag",
    txns=(
        FixtureTxn(
            "CREDIT MEMO ALPHA",
            "300.00",
            "2026-05-02",
            "credit",
            "in",
            "unknown",
            has_source="no",
            expect_strength="none",
            expect_outcome="satisfied",
        ),
        FixtureTxn(
            "TRANSFER INBOUND BRAVO",
            "310.00",
            "2026-05-03",
            "transfer",
            "in",
            "transfer_own",
            has_source="no",
            expect_strength="none",
            expect_outcome="satisfied",
        ),
        FixtureTxn(
            "ACH INBOUND CHARLIE",
            "320.00",
            "2026-05-04",
            "ach",
            "in",
            "unknown",
            has_source="no",
            expect_strength="none",
            expect_outcome="satisfied",
        ),
        FixtureTxn(
            "WIRE INBOUND DELTA",
            "330.00",
            "2026-05-05",
            "wire",
            "in",
            "transfer_own",
            has_source="no",
            expect_strength="none",
            expect_outcome="satisfied",
        ),
        FixtureTxn(
            "UNLABELLED INFLOW ECHO",
            "340.00",
            "2026-05-06",
            "",
            "in",
            "unknown",
            has_source="no",
            expect_strength="none",
            expect_outcome="satisfied",
        ),
        FixtureTxn(
            "DEBIT CARD PURCHASE FOXTROT", "55.00", "2026-05-07", "withdrawal", "out", "vendor"
        ),
    ),
)

_CASE_9 = EvalCase(
    case_id="9",
    title="TAG - strength=verified requires a real MATCHED debit (cited by content_id)",
    level="tag",
    no_false_fire=True,
    txns=(
        FixtureTxn(
            key="TRANSFER FROM BROKERAGE ACCT",
            amount="50000.00",
            date="2026-05-22",
            transaction_type="transfer",
            is_money_in="in",
            apparent_category="transfer_own",
            has_source="yes",
            cite_candidate=True,
            expect_strength="verified",
            expect_outcome="satisfied",
        ),
        FixtureTxn(
            key="WIRE TO BROKERAGE ACCT",
            amount="50000.00",
            date="2026-05-21",
            transaction_type="wire",
            is_money_in="out",
            apparent_category="transfer_own",
        ),
    ),
)

_CASE_10 = EvalCase(
    case_id="10",
    title="TAG - strength=self_asserted (claims a source, NO matching debit)",
    level="tag",
    txns=(
        FixtureTxn(
            key="TRANSFER FROM MY OTHER BANK",
            amount="50000.00",
            date="2026-05-24",
            transaction_type="transfer",
            is_money_in="in",
            apparent_category="transfer_own",
            has_source="yes",
            cite_candidate=False,  # no matching debit exists → description-only claim
            expect_strength="self_asserted",
            expect_outcome="needs_review",
        ),
    ),
)

_CASE_11 = EvalCase(
    case_id="11",
    title="TAG - has_identified_source=no for third-party Zelle (the $147 pattern), under threshold",
    level="tag",
    no_false_fire=True,
    txns=(
        FixtureTxn(
            key="ZELLE PAYMENT FROM THIRD PARTY",
            amount="147.00",
            date="2026-05-26",
            transaction_type="deposit",
            is_money_in="in",
            apparent_category="refund",
            has_source="no",  # unknown-origin third-party inflow - unsourced, not "unknown"
            expect_strength="none",
            expect_outcome="satisfied",  # small (under threshold) → not a fire; the point is the TAG
        ),
    ),
)

# --------------------------------------------------------------------------- #
# REAL-FILE case (12) - the frozen LF-6T3N tagged snapshot (no-false-fire on real data)
# --------------------------------------------------------------------------- #

_CASE_12 = EvalCase(
    case_id="12",
    title="REAL - LF-6T3N: 0 fired; large deposits verified/self_asserted per the actual trace",
    level="real",
    no_false_fire=True,
    income=None,
    fixture_snapshot="lf6t3n_tagged_snapshot.json",
    # The frozen trace (see the fixture doc): 0 fired is the no-false-fire GUARANTEE on real data;
    # the large deposits carry the sourcing DISTINCTION (a verified paper trail vs a self-asserted
    # claim) rather than a bare pass. Pinned loosely (>=1 each, exactly 0 fired) so a faithful
    # fixture regen doesn't churn the test on model-confidence wobble, while the fraud direction
    # (any FIRE) stays hard-pinned at zero.
    expect_real={"fired": 0, "min_verified": 1, "min_self_asserted": 1},
)


CASES: tuple[EvalCase, ...] = (
    _CASE_1,
    _CASE_2,
    _CASE_3,
    _CASE_4,
    _CASE_5,
    _CASE_6,
    _CASE_7,
    _CASE_8,
    _CASE_9,
    _CASE_10,
    _CASE_11,
    _CASE_12,
)


def crafted_cases() -> tuple[EvalCase, ...]:
    """The cases built from a labeled fixture (everything but the frozen real snapshot)."""
    return tuple(c for c in CASES if c.fixture_snapshot is None)
