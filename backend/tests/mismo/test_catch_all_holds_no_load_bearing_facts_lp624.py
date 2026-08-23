"""LP-624 — the guard that would have caught this class, twice.

`catch_all` is where the tolerant parser puts every leaf the typed schema does not lift. Nothing is
lost, so there is no error, no warning and no dropped-field count — the import logs `warnings=0` while
the fact sits unreachable, because the snapshot reads only the typed sections.

That has now happened twice on the same real file:

  * LP-596 — the real-estate-owned schedule. Its own comment: "The parser has always retained these
    leaves, but only in `catch_all`, which this section does not read and the snapshot therefore never
    carried. So the rule engine could not see them and AS-4 / DT-6 / DT-8 reported they could not
    determine facts the application states outright."
  * LP-624 — the EMPLOYMENT record, one section over. Twenty leaves retained, none readable: IN-4
    abstained "the file does not establish the dates of employment" over three start dates in the file
    it had just imported, and the needs AI inferred self-employment on a file stating
    `SelfEmployedIndicator = false` three times.

A `couldnt_check` cannot tell the two kinds of missing apart — "the borrower did not state it" and "we
did not import what they stated" produce the identical sentence. So the check has to be here, on the
parse, where the difference is still visible.

NOT a ban on `catch_all`: most of what lands there genuinely is not load-bearing (contact phone
numbers, address lines, sequence labels). This flags the SHAPES that carry underwriting meaning — a
date, an indicator, an amount, a status — so a new one announces itself instead of waiting for a real
file to expose it.
"""

from __future__ import annotations

from pathlib import Path

from app.mismo.parser import parse_mismo

#: Leaf-name shapes that carry underwriting meaning. A leaf matching one of these, sitting in
#: `catch_all`, is a fact the rule engine cannot read.
_LOAD_BEARING = ("Indicator", "Date", "StatusType", "ClassificationType", "Amount", "Count")

#: WHAT IS STRANDED TODAY, pinned so a NEW one fails and the backlog is a number rather than a
#: surprise. This is DEBT ON THE RECORD, not approval: every name here is a fact the export states and
#: the rule engine cannot read. Several are precisely what a rule is currently abstaining over —
#: annotated, because "45 fields" is not actionable and "DT-6 wants this one" is.
#:
#: Removing a name here is the point. When one is lifted into the typed schema, this test fails until
#: it is deleted from the list, which is what keeps the inventory honest in both directions — and it
#: earned that on its first run: this list was generated while LP-624's own parser change shadowed the
#: borrower's XPath variable, which silently stopped BorrowerBirthDate, BorrowerClassificationType,
#: MaritalStatusType and DependentCount being consumed at all. They appeared here as "stranded", the
#: guard rejected the mismatch once the shadowing was fixed, and the four came back out.
_KNOWN_STRANDED: frozenset[str] = frozenset(
    {
        # --- Wanted by a rule that currently cannot answer -------------------------------------- #
        "LiabilityPaymentIncludesTaxesInsuranceIndicator",  # DT-6 asks exactly this of a statement
        "TotalMortgagedPropertiesCount",  # LP-597 DERIVES this from the REO schedule; it is stated
        "SellerPaidClosingCostsAmount",  # FR-3 (interested-party contributions)
        "ClosingAdjustmentItemAmount",  # FR-3
        "SpecialBorrowerSellerRelationshipIndicator",  # non-arm's-length; the FR family
        "CurrentRateSetDate",  # CL-1, which is waiting on a rate lock
        "PropertyMixedUsageIndicator",  # PR-3 (property eligibility)
        "HousingExpensePaymentAmount",  # the DTI housing side
        # --- Loan features (QM / ATR shape; DT-7's remit) ---------------------------------------- #
        "BalloonIndicator",
        "InterestOnlyIndicator",
        "NegativeAmortizationIndicator",
        "PrepaymentPenaltyIndicator",
        "ConstructionLoanIndicator",
        "BuydownTemporarySubsidyFundingIndicator",
        "BelowMarketSubordinateFinancingIndicator",
        "ConversionOfContractForDeedIndicator",
        "InitialFixedPeriodEffectiveMonthsCount",
        # --- 1003 declarations / borrower detail -------------------------------------------------- #
        "BorrowerResidencyDurationMonthsCount",
        "DependentAgeYearsCount",
        "CommunityPropertyStateIndicator",
        "CommunityPropertyStateResidentIndicator",
        "SelfDeclaredMilitaryServiceIndicator",
        "CounselingConfirmationIndicator",
        "PropertyPreviouslyOccupiedIndicator",
        "PropertyExistingCleanEnergyLienIndicator",
        "LicenseExpirationDate",  # the originator's licence, not the borrower's ID
        # --- Closing figures ---------------------------------------------------------------------- #
        "CashFromBorrowerAtClosingAmount",
        "EstimatedClosingCostsAmount",
        "PrepaidItemsEstimatedAmount",
        # --- Genuinely not load-bearing, kept out of _ACCEPTED because the shape match is
        #     incidental: these are geography and HMDA collection mechanics, not underwriting facts. - #
        "CountryCode",
        "CountryName",
        "CountyName",
        "FIPSCountyCode",
        "HMDAEthnicityCollectedBasedOnVisualObservationOrSurnameIndicator",
        "HMDAEthnicityRefusalIndicator",
        "HMDAGenderCollectedBasedOnVisualObservationOrNameIndicator",
        "HMDAGenderRefusalIndicator",
        "HMDARaceCollectedBasedOnVisualObservationOrSurnameIndicator",
        "HMDARaceRefusalIndicator",
    }
)

#: Load-bearing shapes deliberately never lifted, with the reason. Distinct from `_KNOWN_STRANDED`:
#: that is a backlog to work through, this is a decision that needs no further thought.
_ACCEPTED: dict[str, str] = {
    "ForeignIncomeIndicator": "DU extension; no rule reads it and none is planned",
    "SeasonalIncomeIndicator": "DU extension; no rule reads it and none is planned",
}


#: The same real export the parser suite reads elsewhere (LP-596's fixture), so the guard runs against
#: a genuine lender file rather than a synthetic one shaped to pass it.
_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/mismo/MISMO16940192.xml"


def _catch_all_leaf_names(raw: bytes) -> set[str]:
    parsed = parse_mismo(raw)
    names: set[str] = set()
    for section in parsed.catch_all:
        for leaf in section.fields:
            label = getattr(leaf, "label", None)
            if isinstance(label, str):
                names.add(label)
    return names


def test_no_employment_fact_is_stranded_in_catch_all() -> None:
    """THE REGRESSION THIS TICKET FIXES. Every EMPLOYMENT leaf the parser now lifts must stop appearing
    in `catch_all` — if one reappears, the typed lift has been broken and the fact is unreadable again
    while the import still reports no warnings."""
    raw = _FIXTURE.read_bytes()
    stranded = {
        name
        for name in _catch_all_leaf_names(raw)
        if name.startswith("Employment") and name not in _ACCEPTED
    }

    assert not stranded, (
        "these EMPLOYMENT facts are in the file but unreachable to the rule engine: "
        f"{sorted(stranded)}"
    )


def test_no_new_load_bearing_shape_is_stranded() -> None:
    """THE SWEEP, so the next instance announces itself. LP-596 fixed this mechanism for one section
    and nobody asked where else it applied; employment was sitting right beside it for months, and a
    real file had to expose it.

    Pinned as an EQUALITY rather than an emptiness: the backlog is real and is not this ticket's to
    clear, but a NEW stranded fact fails immediately, and lifting one fails too — which is what forces
    the list to be maintained instead of quietly growing."""
    stranded = {
        name
        for name in _catch_all_leaf_names(_FIXTURE.read_bytes())
        if any(shape in name for shape in _LOAD_BEARING) and name not in _ACCEPTED
    }

    appeared = sorted(stranded - _KNOWN_STRANDED)
    assert not appeared, (
        "NEW load-bearing facts are stranded in catch_all, unreadable to the rule engine — lift them "
        "into the typed schema, or record them:\n  " + "\n  ".join(appeared)
    )

    lifted = sorted(_KNOWN_STRANDED - stranded)
    assert not lifted, (
        "these are no longer stranded — delete them from _KNOWN_STRANDED so the backlog stays "
        "honest:\n  " + "\n  ".join(lifted)
    )
