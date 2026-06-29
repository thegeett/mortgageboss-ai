"""Deterministic cross-source rules (LP-86) — the graduation.

THE GRADUATION (the heart of LP-86). The AI cross-source layer (LP-78) is a DISCOVERY
ENGINE — it catches novel, unenumerable discrepancies, at the cost of non-determinism
(recall variance: a genuine finding appears on one run, not the next). The diagnostic
signal during the cross-source debugging was the "driver's-license-address-equals-
subject-property" finding FLICKERING between runs — because it is actually DETERMINISTIC
LOGIC the AI merely *thought* to apply (compare two addresses), not open-ended
perception. The structural answer (the plan's §3.8): **known, enumerable cross-checks
GRADUATE from the AI layer into DETERMINISTIC rules** — run every time, identically,
with fixed (templated) wording — while the AI narrows to genuinely NOVEL discovery.

This module is that graduation. Each :class:`CrossSourceRule` is a uniform structured
record like the single-source rules (LP-82..85), but it is a DISTINCT category: it reads
MULTIPLE fields ACROSS sources (not one threshold against one field), it emits with
``origin=deterministic`` and TEMPLATED wording (identical every run — the consistency
win), and it OWNS a canonical finding type so the AI layer can defer on it (no
double-reporting — see :data:`OWNED_CANONICAL_TYPES`).

The "research" for these rules was INTERNAL (unlike LP-82..85's external guides): the
promotion candidates are the canonical finding TYPES the AI cross-source layer already
emits (``app.services.cross_source._TYPE_CATEGORY`` / the prompt), the reliable findings
it has surfaced, and the over-flagging decisions (keep the missing-document checks). The
external mortgage-QC cross-check set is the completeness checklist; these ~18 are the
reliable + enumerable subset.

Every rule is ``starter=True`` — the comparison logic is real + tested, but the
thresholds (the income-variance %), normalization, and which checks are reliable enough
to promote remain a validate-with-Priya item.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal

from app.models.finding import FindingCategory
from app.models.lender import LoanProgram
from app.verification.cross_source.facts import CrossSourceFacts, ObligationRef, SourcedValue
from app.verification.rules.schema import Condition, Operator, RuleSeverity

# --------------------------------------------------------------------------- #
# Match + rule structure
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CrossSourceMatch:
    """One discrepancy a check found — the data to fill the rule's templated wording.

    ``subject_key`` distinguishes multiple findings from one rule (e.g. two undisclosed
    debts), so de-duplication / stable identity can tell them apart. ``fields`` fills the
    template; ``stated_value`` / ``document_value`` carry onto the finding details (and
    feed the APPLY→recompute spec for the undisclosed-debt rule).
    """

    subject_key: str
    fields: dict[str, str]
    stated_value: str | None = None
    document_value: str | None = None


CheckFn = Callable[[CrossSourceFacts, "Condition | None"], list[CrossSourceMatch]]


@dataclass(frozen=True)
class CrossSourceRule:
    """One deterministic cross-source rule — a DISTINCT category (LP-86).

    Carries a stable ``rule_id`` (``xsrc.*``), the ``canonical_type`` it OWNS (the
    de-dup key the AI layer defers on), the finding ``category`` + ``severity``, a
    TEMPLATED ``template`` (fixed wording, identical every run), and the pure ``check``
    that reads :class:`CrossSourceFacts` across sources and returns the matches. The
    optional ``threshold`` is threshold-as-data (e.g. the income-variance %), overlay-
    overrideable by ``rule_id``. ``program`` is ``None`` for the program-agnostic checks
    (most cross-source checks apply to both Conventional and FHA).
    """

    rule_id: str
    canonical_type: str
    category: FindingCategory
    severity: RuleSeverity
    template: str
    check: CheckFn
    threshold: Condition | None = None
    program: LoanProgram | None = None  # None → program-agnostic (both programs)
    starter: bool = True
    notes: str = ""

    def with_threshold(self, threshold: Condition) -> CrossSourceRule:
        """Return a copy with the threshold replaced (identity/logic unchanged) — overlays."""
        return replace(self, threshold=threshold)


# --------------------------------------------------------------------------- #
# Normalization helpers (pure)
# --------------------------------------------------------------------------- #


def _norm(value: str) -> str:
    """Lowercase, strip, collapse internal whitespace — the consistency comparison key."""
    return re.sub(r"\s+", " ", value.strip().lower())


def _distinct(values: tuple[SourcedValue, ...]) -> list[str]:
    """The distinct normalized values present (order-stable by first appearance)."""
    seen: dict[str, None] = {}
    for sv in values:
        if sv.value:
            seen.setdefault(_norm(sv.value), None)
    return list(seen)


def _render_sources(values: tuple[SourcedValue, ...]) -> str:
    """A stable ``value (source)`` join for templated wording — sorted for determinism."""
    return "; ".join(sorted(f"{sv.value} ({sv.source})" for sv in values if sv.value))


# --------------------------------------------------------------------------- #
# The checks (pure) — each reads facts across sources and returns matches
# --------------------------------------------------------------------------- #


def _consistency_check(attr: str, label: str) -> CheckFn:
    """Build a check that fires when an identity attribute disagrees across sources."""

    def check(facts: CrossSourceFacts, _threshold: Condition | None) -> list[CrossSourceMatch]:
        values: tuple[SourcedValue, ...] = getattr(facts, attr)
        if len(_distinct(values)) <= 1:
            return []
        return [
            CrossSourceMatch(
                subject_key=label,
                fields={"values": _render_sources(values)},
                document_value=_render_sources(values),
            )
        ]

    return check


def _check_dl_equals_subject(
    facts: CrossSourceFacts, _threshold: Condition | None
) -> list[CrossSourceMatch]:
    if facts.dl_address is None or facts.subject_property_address is None:
        return []
    if _norm(facts.dl_address.value) != _norm(facts.subject_property_address):
        return []
    return [
        CrossSourceMatch(
            subject_key="dl_equals_subject",
            fields={"address": facts.subject_property_address},
            stated_value=facts.subject_property_address,
            document_value=f"{facts.dl_address.value} ({facts.dl_address.source})",
        )
    ]


def _check_employer_equals_subject(
    facts: CrossSourceFacts, _threshold: Condition | None
) -> list[CrossSourceMatch]:
    if facts.subject_property_address is None:
        return []
    subject = _norm(facts.subject_property_address)
    out: list[CrossSourceMatch] = []
    for emp in facts.employer_addresses:
        if emp.value and _norm(emp.value) == subject:
            out.append(
                CrossSourceMatch(
                    subject_key=f"employer:{emp.source}",
                    fields={"address": facts.subject_property_address, "source": emp.source},
                    document_value=f"{emp.value} ({emp.source})",
                )
            )
    return out


def _check_income_variance(
    facts: CrossSourceFacts, threshold: Condition | None
) -> list[CrossSourceMatch]:
    stated, documented = facts.stated_income_monthly, facts.documented_income_monthly
    if stated is None or documented is None or documented <= 0:
        return []
    limit = threshold.value if threshold is not None else Decimal("10")
    variance = (abs(stated - documented) / documented * Decimal(100)).quantize(Decimal("0.1"))
    if variance <= limit:
        return []
    return [
        CrossSourceMatch(
            subject_key="income_variance",
            fields={
                "stated": str(stated),
                "documented": str(documented),
                "variance": str(variance),
                "threshold": str(limit),
            },
            stated_value=str(stated),
            document_value=str(documented),
        )
    ]


def _check_employer_name_consistency(
    facts: CrossSourceFacts, _threshold: Condition | None
) -> list[CrossSourceMatch]:
    if not facts.stated_employers or not facts.documented_employers:
        return []
    stated = {_norm(e) for e in facts.stated_employers if e}
    out: list[CrossSourceMatch] = []
    for emp in facts.documented_employers:
        if emp and _norm(emp) not in stated:
            out.append(
                CrossSourceMatch(
                    subject_key=f"employer_name:{_norm(emp)}",
                    fields={"employer": emp},
                    document_value=emp,
                )
            )
    return out


def _check_employer_count(
    facts: CrossSourceFacts, _threshold: Condition | None
) -> list[CrossSourceMatch]:
    if facts.stated_employer_count is None or facts.income_item_count is None:
        return []
    if facts.stated_employer_count == facts.income_item_count:
        return []
    return [
        CrossSourceMatch(
            subject_key="employer_count",
            fields={
                "employers": str(facts.stated_employer_count),
                "items": str(facts.income_item_count),
            },
        )
    ]


def _obligation_diff(
    left: tuple[ObligationRef, ...], right: tuple[ObligationRef, ...]
) -> list[ObligationRef]:
    """Items in ``left`` whose normalized key is not in ``right`` (set difference)."""
    right_keys = {_norm(o.key) for o in right if o.key}
    return [o for o in left if o.key and _norm(o.key) not in right_keys]


def _check_undisclosed_debt(
    facts: CrossSourceFacts, _threshold: Condition | None
) -> list[CrossSourceMatch]:
    out: list[CrossSourceMatch] = []
    for obl in _obligation_diff(facts.credit_report_liabilities, facts.stated_liabilities):
        amount = str(obl.amount) if obl.amount is not None else "unknown"
        out.append(
            CrossSourceMatch(
                subject_key=f"undisclosed:{_norm(obl.key)}",
                fields={"holder": obl.key, "amount": amount},
                document_value=amount,  # feeds the APPLY→recompute add_liability spec
            )
        )
    return out


def _check_stated_not_on_report(
    facts: CrossSourceFacts, _threshold: Condition | None
) -> list[CrossSourceMatch]:
    # Only meaningful when a credit report is actually present: with no report loaded the
    # set-difference would flag EVERY stated liability (a false positive, not a discrepancy).
    if not facts.credit_report_liabilities:
        return []
    out: list[CrossSourceMatch] = []
    for obl in _obligation_diff(facts.stated_liabilities, facts.credit_report_liabilities):
        out.append(
            CrossSourceMatch(
                subject_key=f"stated_only:{_norm(obl.key)}", fields={"holder": obl.key}
            )
        )
    return out


def _check_stated_asset_missing_doc(
    facts: CrossSourceFacts, _threshold: Condition | None
) -> list[CrossSourceMatch]:
    return [
        CrossSourceMatch(subject_key=f"asset:{_norm(label)}", fields={"asset": label})
        for label in facts.stated_assets_missing_doc
        if label
    ]


def _check_large_deposit_unsourced(
    facts: CrossSourceFacts, _threshold: Condition | None
) -> list[CrossSourceMatch]:
    return [
        CrossSourceMatch(
            subject_key=f"deposit:{amount}",
            fields={"amount": str(amount)},
            document_value=str(amount),
        )
        for amount in facts.unsourced_large_deposits
    ]


def _check_gift_without_letter(
    facts: CrossSourceFacts, _threshold: Condition | None
) -> list[CrossSourceMatch]:
    if (
        facts.gift_amount is None
        or facts.gift_amount <= 0
        or facts.gift_letter_present is not False
    ):
        return []
    return [
        CrossSourceMatch(
            subject_key="gift_without_letter",
            fields={"amount": str(facts.gift_amount)},
            stated_value=str(facts.gift_amount),
        )
    ]


def _amount_mismatch(
    subject: str, stated: Decimal | None, documented: Decimal | None
) -> list[CrossSourceMatch]:
    if stated is None or documented is None or stated == documented:
        return []
    return [
        CrossSourceMatch(
            subject_key=subject,
            fields={"stated": str(stated), "documented": str(documented)},
            stated_value=str(stated),
            document_value=str(documented),
        )
    ]


def _check_price_vs_contract(
    facts: CrossSourceFacts, _threshold: Condition | None
) -> list[CrossSourceMatch]:
    return _amount_mismatch("price", facts.stated_purchase_price, facts.contract_purchase_price)


def _check_loan_vs_documented(
    facts: CrossSourceFacts, _threshold: Condition | None
) -> list[CrossSourceMatch]:
    return _amount_mismatch("loan", facts.stated_loan_amount, facts.documented_loan_amount)


def _check_subject_address_consistency(
    facts: CrossSourceFacts, _threshold: Condition | None
) -> list[CrossSourceMatch]:
    if len(_distinct(facts.subject_addresses_across_docs)) <= 1:
        return []
    return [
        CrossSourceMatch(
            subject_key="subject_address",
            fields={"values": _render_sources(facts.subject_addresses_across_docs)},
            document_value=_render_sources(facts.subject_addresses_across_docs),
        )
    ]


def _check_occupancy_vs_evidence(
    facts: CrossSourceFacts, _threshold: Condition | None
) -> list[CrossSourceMatch]:
    if facts.stated_occupancy is None or facts.occupancy_evidence is None:
        return []
    if _norm(facts.stated_occupancy) == _norm(facts.occupancy_evidence):
        return []
    return [
        CrossSourceMatch(
            subject_key="occupancy",
            fields={"stated": facts.stated_occupancy, "evidence": facts.occupancy_evidence},
            stated_value=facts.stated_occupancy,
            document_value=facts.occupancy_evidence,
        )
    ]


# --------------------------------------------------------------------------- #
# The ~18 deterministic cross-source rules
# --------------------------------------------------------------------------- #

_VARIANCE_10 = Condition(op=Operator.LE, value=Decimal("10"), unit="percent")

# IDENTITY / CONSISTENCY ----------------------------------------------------- #
XSRC_IDENTITY_NAME = CrossSourceRule(
    rule_id="xsrc.identity.name_consistency",
    canonical_type="identity_discrepancy",
    category=FindingCategory.CROSS_SOURCE,
    severity=RuleSeverity.YELLOW,
    template="Borrower name differs across sources: {values}.",
    check=_consistency_check("names", "name"),
    notes="STARTER — name normalization (suffix/middle-name) is a validate-with-Priya item.",
)
XSRC_IDENTITY_SSN = CrossSourceRule(
    rule_id="xsrc.identity.ssn_consistency",
    canonical_type="identity_discrepancy",
    category=FindingCategory.CROSS_SOURCE,
    severity=RuleSeverity.RED,
    template="SSN differs across documents: {values}.",
    check=_consistency_check("ssns", "ssn"),
    notes="STARTER — an SSN mismatch is a serious identity/fraud red flag (RED).",
)
XSRC_IDENTITY_DOB = CrossSourceRule(
    rule_id="xsrc.identity.dob_consistency",
    canonical_type="identity_discrepancy",
    category=FindingCategory.CROSS_SOURCE,
    severity=RuleSeverity.YELLOW,
    template="Date of birth differs across documents: {values}.",
    check=_consistency_check("dobs", "dob"),
    notes="STARTER — date-format normalization to verify.",
)

# ADDRESS / RED-FLAG --------------------------------------------------------- #
XSRC_ADDRESS_DL_EQUALS_SUBJECT = CrossSourceRule(
    rule_id="xsrc.address.dl_equals_subject",
    canonical_type="property_address_discrepancy",
    category=FindingCategory.PROPERTY,
    severity=RuleSeverity.YELLOW,
    template="Driver's license address equals the subject property ({address}) — occupancy/identity red flag.",
    check=_check_dl_equals_subject,
    notes=(
        "STARTER — THE GRADUATE: this is the driver's-license finding that FLICKERED as an AI 'other' "
        "finding (LP-78 non-determinism). It is deterministic logic (compare two addresses) — now a rule "
        "that fires every run, identically. The AI defers on property_address_discrepancy when this fires."
    ),
)
XSRC_ADDRESS_EMPLOYER_EQUALS_SUBJECT = CrossSourceRule(
    rule_id="xsrc.address.employer_equals_subject",
    canonical_type="property_address_discrepancy",
    category=FindingCategory.INCOME,
    severity=RuleSeverity.YELLOW,
    template="Employer address ({source}) equals the subject property ({address}) — employment red flag.",
    check=_check_employer_equals_subject,
    notes="STARTER — an employer address equal to the subject (or a PO box) is an employment red flag.",
)
XSRC_ADDRESS_CURRENT_CONSISTENCY = CrossSourceRule(
    rule_id="xsrc.address.current_address_consistency",
    canonical_type="identity_discrepancy",
    category=FindingCategory.CROSS_SOURCE,
    severity=RuleSeverity.YELLOW,
    template="Current/mailing address differs across documents: {values}.",
    check=_consistency_check("current_addresses", "current_address"),
    notes="STARTER — a recent move can explain this; surfaced for review, not a block.",
)

# INCOME / EMPLOYMENT -------------------------------------------------------- #
XSRC_INCOME_STATED_VS_DOCUMENTED = CrossSourceRule(
    rule_id="xsrc.income.stated_vs_documented",
    canonical_type="income_variance",
    category=FindingCategory.INCOME,
    severity=RuleSeverity.YELLOW,
    template="Stated income ({stated}) differs from documented income ({documented}) by {variance}% (> {threshold}%).",
    check=_check_income_variance,
    threshold=_VARIANCE_10,
    notes=(
        "STARTER — threshold-as-data (the 10% variance is overlay-overrideable by rule_id, LP-80). "
        "CONSUMES the stated + documented income; feeds the APPLY→recompute correct_income path (LP-76)."
    ),
)
XSRC_INCOME_EMPLOYER_NAME = CrossSourceRule(
    rule_id="xsrc.income.employer_name_consistency",
    canonical_type="employer_mismatch",
    category=FindingCategory.INCOME,
    severity=RuleSeverity.YELLOW,
    template="Documented employer not among the stated employers: {employer}.",
    check=_check_employer_name_consistency,
    notes="STARTER — employer-name normalization (DBA/legal name) to verify.",
)
XSRC_INCOME_EMPLOYER_COUNT = CrossSourceRule(
    rule_id="xsrc.income.employer_count_matches_items",
    canonical_type="employer_mismatch",
    category=FindingCategory.INCOME,
    severity=RuleSeverity.YELLOW,
    template="Stated employer count ({employers}) does not match the income-item count ({items}).",
    check=_check_employer_count,
    notes="STARTER — each stated employer should map to a supporting income item, and vice versa.",
)

# LIABILITY / DEBT (the undisclosed-debt graduate) --------------------------- #
XSRC_LIABILITY_UNDISCLOSED = CrossSourceRule(
    rule_id="xsrc.liability.undisclosed_debt",
    canonical_type="liability_discrepancy",
    category=FindingCategory.CREDIT,
    severity=RuleSeverity.YELLOW,
    template="Liability on the credit report not disclosed on the application: {holder} ({amount}).",
    check=_check_undisclosed_debt,
    notes=(
        "STARTER — the undisclosed-debt graduate: the DETERMINISTIC detection counterpart to LP-78's "
        "AI undisclosed-obligation finding + LP-83's conv.dti.reunderwrite_undisclosed_debt rule. Applying "
        "it adds the liability (APPLY→recompute) → the DTI recomputes higher (LP-75/76)."
    ),
)
XSRC_LIABILITY_STATED_NOT_ON_REPORT = CrossSourceRule(
    rule_id="xsrc.liability.stated_not_on_report",
    canonical_type="liability_discrepancy",
    category=FindingCategory.CREDIT,
    severity=RuleSeverity.YELLOW,
    template="Stated liability not found on the credit report: {holder}.",
    check=_check_stated_not_on_report,
    notes="STARTER — the reverse check (a stated debt the report doesn't show); review, often benign.",
)

# ASSET / DEPOSIT ------------------------------------------------------------ #
XSRC_ASSET_MISSING_DOC = CrossSourceRule(
    rule_id="xsrc.asset.stated_missing_document",
    canonical_type="missing_documentation",
    category=FindingCategory.DOCUMENTATION,
    severity=RuleSeverity.YELLOW,
    template="Stated asset lacks a supporting document: {asset}.",
    check=_check_stated_asset_missing_doc,
    notes=(
        "STARTER — KEPT per the over-flagging decision (duplicates beat omissions); the needs list also "
        "surfaces these — that redundancy is intentional + safe. Cross-link: the needs list."
    ),
)
XSRC_ASSET_LARGE_DEPOSIT = CrossSourceRule(
    rule_id="xsrc.asset.large_deposit_unsourced",
    canonical_type="asset_discrepancy",
    category=FindingCategory.ASSETS,
    severity=RuleSeverity.YELLOW,
    template="Large deposit not reflected / unsourced: {amount}.",
    check=_check_large_deposit_unsourced,
    notes="STARTER — cross-links LP-82's single-source large-deposit rule (this compares across sources).",
)
XSRC_ASSET_GIFT_WITHOUT_LETTER = CrossSourceRule(
    rule_id="xsrc.asset.gift_without_letter",
    canonical_type="gift_discrepancy",
    category=FindingCategory.ASSETS,
    severity=RuleSeverity.YELLOW,
    template="A gift of {amount} is stated but no gift letter / transfer documentation is present.",
    check=_check_gift_without_letter,
    notes="STARTER — cross-links LP-82's single-source gift rule (this compares stated gift vs the doc).",
)

# TERMS / PROPERTY ----------------------------------------------------------- #
XSRC_TERMS_PRICE_VS_CONTRACT = CrossSourceRule(
    rule_id="xsrc.terms.price_vs_contract",
    canonical_type="terms_discrepancy",
    category=FindingCategory.PROPERTY,
    severity=RuleSeverity.YELLOW,
    template="Stated purchase price ({stated}) differs from the contract price ({documented}).",
    check=_check_price_vs_contract,
    notes="STARTER — owns the terms_discrepancy canonical type (added to the AI taxonomy for de-dup).",
)
XSRC_TERMS_LOAN_VS_DOCUMENTED = CrossSourceRule(
    rule_id="xsrc.terms.loan_vs_documented",
    canonical_type="terms_discrepancy",
    category=FindingCategory.PROPERTY,
    severity=RuleSeverity.YELLOW,
    template="Stated loan amount ({stated}) differs from the documented loan terms ({documented}).",
    check=_check_loan_vs_documented,
    notes="STARTER — terms_discrepancy; the loan amount vs the documented note/terms.",
)
XSRC_PROPERTY_SUBJECT_ADDRESS = CrossSourceRule(
    rule_id="xsrc.property.subject_address_consistency",
    canonical_type="property_address_discrepancy",
    category=FindingCategory.PROPERTY,
    severity=RuleSeverity.YELLOW,
    template="Subject-property address differs across documents: {values}.",
    check=_check_subject_address_consistency,
    notes="STARTER — application vs appraisal vs contract; owns property_address_discrepancy.",
)
XSRC_PROPERTY_OCCUPANCY = CrossSourceRule(
    rule_id="xsrc.property.occupancy_vs_evidence",
    canonical_type="occupancy_discrepancy",
    category=FindingCategory.PROPERTY,
    severity=RuleSeverity.YELLOW,
    template="Stated occupancy ({stated}) conflicts with the evidence ({evidence}).",
    check=_check_occupancy_vs_evidence,
    notes="STARTER — owns occupancy_discrepancy; e.g. investment stated but the ID is at the subject.",
)


CROSS_SOURCE_RULES: tuple[CrossSourceRule, ...] = (
    XSRC_IDENTITY_NAME,
    XSRC_IDENTITY_SSN,
    XSRC_IDENTITY_DOB,
    XSRC_ADDRESS_DL_EQUALS_SUBJECT,
    XSRC_ADDRESS_EMPLOYER_EQUALS_SUBJECT,
    XSRC_ADDRESS_CURRENT_CONSISTENCY,
    XSRC_INCOME_STATED_VS_DOCUMENTED,
    XSRC_INCOME_EMPLOYER_NAME,
    XSRC_INCOME_EMPLOYER_COUNT,
    XSRC_LIABILITY_UNDISCLOSED,
    XSRC_LIABILITY_STATED_NOT_ON_REPORT,
    XSRC_ASSET_MISSING_DOC,
    XSRC_ASSET_LARGE_DEPOSIT,
    XSRC_ASSET_GIFT_WITHOUT_LETTER,
    XSRC_TERMS_PRICE_VS_CONTRACT,
    XSRC_TERMS_LOAN_VS_DOCUMENTED,
    XSRC_PROPERTY_SUBJECT_ADDRESS,
    XSRC_PROPERTY_OCCUPANCY,
)

# The canonical finding types the deterministic rules OWN. The AI cross-source layer
# DEFERS on a type when the deterministic pass emitted a finding of that type this run
# (run-scoped de-dup: no double-reporting a fired discrepancy, while the AI still surfaces
# a type the deterministic pass was silent on — e.g. when its Tier-2 facts aren't present).
# The AI keeps "other" (novel) + "co_borrower_discrepancy" (not yet graduated).
OWNED_CANONICAL_TYPES: frozenset[str] = frozenset(r.canonical_type for r in CROSS_SOURCE_RULES)


def apply_cross_source_overlay(
    rules: tuple[CrossSourceRule, ...], overrides: dict[str, Condition]
) -> tuple[CrossSourceRule, ...]:
    """Patch cross-source rule thresholds by ``rule_id`` (the overlay diff, LP-80).

    Mirrors :func:`app.verification.registry.apply_overlay` for the cross-source rules:
    a threshold override (e.g. the income-variance %) replaces the rule's
    :class:`Condition` by ``rule_id``; the identity + check logic are unchanged.
    """
    return tuple(
        rule.with_threshold(overrides[rule.rule_id]) if rule.rule_id in overrides else rule
        for rule in rules
    )
