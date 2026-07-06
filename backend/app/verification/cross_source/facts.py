"""Cross-source facts (LP-86) — the multi-source typed snapshot the deterministic
cross-source engine reads.

Where the single-source engine (:mod:`app.verification.facts`) reads ONE typed field
and compares it to ONE threshold, a CROSS-SOURCE check compares fields *across*
sources — borrower name on the application vs the W-2 vs the ID; the stated income vs
the documented income; the credit-report liabilities vs the stated liabilities. So the
cross-source snapshot is shaped differently: it carries **observed values tagged with
their source** and the small structured lists the checks diff.

Keeping this a plain, pure data structure (no DB, no AI) is deliberate — exactly as
:class:`app.verification.facts.FileFacts` is: the engine
(:mod:`app.verification.cross_source.engine`) stays pure and trivially testable (a test
constructs :class:`CrossSourceFacts` directly), while *how* the facts are gathered from
the assembled stated-vs-verified context lives in the service layer
(:mod:`app.services.cross_source_deterministic`). A field that isn't populated yet
(Tier-2 / promotion-pending) is left at its empty default — the rule that reads it
simply produces no finding (graceful absence), never a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class SourcedValue:
    """One observed value tagged with the source it came from (the audit anchor).

    ``source`` is a short label — ``"application"`` / ``"w2"`` / ``"drivers_license"`` /
    ``"bank_statement"`` — so a consistency finding can name *where* the values diverged.
    """

    value: str
    source: str


@dataclass(frozen=True)
class ObligationRef:
    """A liability/asset reference used for cross-source set-difference checks.

    ``key`` is the normalized match key (e.g. the holder/creditor name); ``amount`` is
    the monthly payment / balance when known; ``source`` labels where it was seen.
    """

    key: str
    amount: Decimal | None
    source: str


@dataclass(frozen=True)
class CrossSourceFacts:
    """The per-file cross-source snapshot — values across sources + the diff lists.

    Every field defaults empty: the cross-source checks are enumerable but each depends
    on data that may be Tier-2 (appraiser/credit-report observed) or not-yet-promoted.
    A check whose inputs are absent yields no finding (the engine never invents one).
    """

    # --- Identity / consistency (values observed per source) ------------------
    names: tuple[SourcedValue, ...] = ()
    ssns: tuple[SourcedValue, ...] = ()
    dobs: tuple[SourcedValue, ...] = ()
    current_addresses: tuple[SourcedValue, ...] = ()

    # --- Address / red-flag ---------------------------------------------------
    subject_property_address: str | None = None
    dl_address: SourcedValue | None = None
    employer_addresses: tuple[SourcedValue, ...] = ()

    # --- Income / employment --------------------------------------------------
    stated_income_monthly: Decimal | None = None
    documented_income_monthly: Decimal | None = None
    stated_employers: tuple[str, ...] = ()
    documented_employers: tuple[str, ...] = ()
    stated_employer_count: int | None = None
    income_item_count: int | None = None

    # --- Liability / debt -----------------------------------------------------
    credit_report_liabilities: tuple[ObligationRef, ...] = ()
    stated_liabilities: tuple[ObligationRef, ...] = ()

    # --- Asset / deposit ------------------------------------------------------
    stated_assets_missing_doc: tuple[str, ...] = ()
    unsourced_large_deposits: tuple[Decimal, ...] = ()
    gift_amount: Decimal | None = None
    gift_letter_present: bool | None = None

    # --- Terms / property -----------------------------------------------------
    stated_purchase_price: Decimal | None = None
    contract_purchase_price: Decimal | None = None
    stated_loan_amount: Decimal | None = None
    documented_loan_amount: Decimal | None = None
    subject_addresses_across_docs: tuple[SourcedValue, ...] = field(default_factory=tuple)
    stated_occupancy: str | None = None
    occupancy_evidence: str | None = None
