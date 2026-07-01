"""Deterministic cross-source service (LP-86) — build facts, evaluate, emit, de-dup.

The DB-facing half of the deterministic cross-source layer (the pure engine is
:mod:`app.verification.cross_source`). It:

1. **Builds the cross-source facts** from the SAME assembled stated-vs-verified context
   the AI pass reads (:func:`app.services.cross_source.assemble_cross_source_context`) —
   so the deterministic checks and the AI see the same data.
2. **Evaluates** the deterministic cross-source rules (pure, no AI) and **emits** their
   findings into LP-75's shared Finding model with ``origin=deterministic_rule``,
   ``confidence=DETERMINISTIC_CONFIDENCE``, and TEMPLATED wording (identical every run).
3. Returns the **fired canonical types** so the AI layer can DEFER on them (run-scoped
   de-duplication — no double-reporting a discrepancy a deterministic rule already owns).

THE GRADUATION: the checks here used to flicker as AI findings (the driver's-license
example); now they are deterministic and stable. Many facts are still Tier-2 / promotion-
pending (credit-report liabilities, contract price, documented income) — those checks
simply produce nothing until the fact is populated (graceful), exactly like LP-83..85.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.finding import (
    Finding,
    FindingOrigin,
    FindingResolutionStatus,
    FindingStatus,
)
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.models.property import Property
from app.models.verification import Verification
from app.services.finding_identity import existing_identities, finding_identity
from app.verification.confidence import DETERMINISTIC_CONFIDENCE
from app.verification.cross_source import (
    CrossSourceFacts,
    CrossSourceFinding,
    ObligationRef,
    SourcedValue,
    evaluate_cross_source,
)
from app.verification.rules.schema import RuleSeverity

_SEVERITY_TO_STATUS = {
    RuleSeverity.RED: FindingStatus.RED,
    RuleSeverity.YELLOW: FindingStatus.YELLOW,
}

# Document-field keys that carry a person name / an address (Tier-2 typed-core fields).
_NAME_KEYS = ("full_name", "employee_name", "borrower_name", "name")
_ADDRESS_KEYS = ("address", "current_address", "residence_address")
_EMPLOYER_KEYS = ("employer_name", "employer")


async def run_cross_source_deterministic(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    run: Verification,
    facts: CrossSourceFacts,
) -> tuple[int, int, frozenset[str]]:
    """Evaluate the deterministic cross-source rules and emit their findings.

    Supersedes the file's prior OPEN deterministic cross-source findings (``xsrc.*``,
    scoped so the single-source ``conv.*``/``fha.*`` findings are untouched), then emits
    the fresh set attached to ``run``. Returns ``(red, yellow, fired_canonical_types)`` —
    the counts and the set of canonical types that fired (so the AI layer defers on them).
    ``flush`` only; the caller owns the transaction.
    """
    await _supersede_open_deterministic_findings(db, loan_file.id)

    # Normalized-substance dedup (LP-93): the same discrepancy worded two ways (case /
    # dash / quote / whitespace) is ONE finding. Seed from the file's live findings so a
    # re-detected RESOLVED finding is skipped (its resolution preserved), not re-emitted.
    seen = await existing_identities(db, loan_file.id)

    results = evaluate_cross_source(facts, program=loan_file.loan_program)
    red = yellow = 0
    fired: set[str] = set()
    for result in results:
        # The rule fired → the AI defers on its canonical type regardless of persist-dedup.
        fired.add(result.rule.canonical_type)
        finding = _to_finding(result, loan_file_id=loan_file.id, run_id=run.id)
        identity = finding_identity(finding)
        if identity in seen:
            continue  # same normalized substance already present (this run, or a resolved one)
        seen.add(identity)
        db.add(finding)
        if finding.status is FindingStatus.RED:
            red += 1
        else:
            yellow += 1
    await db.flush()
    return red, yellow, frozenset(fired)


async def _supersede_open_deterministic_findings(db: AsyncSession, loan_file_id: UUID) -> int:
    """Soft-delete the file's OPEN deterministic cross-source findings (a re-run replaces them).

    Scoped to ``xsrc.*`` rule ids so the single-source engine's ``conv.*``/``fha.*``
    findings are left intact. Resolved (applied / overridden) findings are preserved.
    """
    result = await db.execute(
        update(Finding)
        .where(
            Finding.loan_file_id == loan_file_id,
            Finding.origin == FindingOrigin.DETERMINISTIC_RULE,
            Finding.rule_id.like("xsrc.%"),
            Finding.resolution_status == FindingResolutionStatus.OPEN,
            Finding.deleted_at.is_(None),
        )
        .values(deleted_at=utcnow())
    )
    await db.flush()
    return getattr(result, "rowcount", 0) or 0


def _to_finding(result: CrossSourceFinding, *, loan_file_id: UUID, run_id: UUID) -> Finding:
    """Map a deterministic cross-source result onto a Finding (origin=deterministic_rule).

    Deterministic findings are **certain** (the comparison is exact) — confidence is
    :data:`DETERMINISTIC_CONFIDENCE`. The message is the rule's TEMPLATED wording (fixed
    every run). The undisclosed-debt rule carries an ``apply`` spec so applying it adds the
    liability → the DTI recomputes (the APPLY→recompute loop, cross-linked to LP-76/83).
    """
    rule = result.rule
    details: dict[str, Any] = {
        "type": rule.canonical_type,
        "rule_id": rule.rule_id,
        "subject_key": result.subject_key,
        "stated_value": result.stated_value,
        "document_value": result.document_value,
        "reasoning": result.message,
        "starter": rule.starter,
    }
    apply_spec = _build_apply_spec(result)
    if apply_spec is not None:
        details["apply"] = apply_spec

    return Finding(
        loan_file_id=loan_file_id,
        verification_id=run_id,
        rule_id=rule.rule_id,
        origin=FindingOrigin.DETERMINISTIC_RULE,
        confidence=DETERMINISTIC_CONFIDENCE,
        status=_SEVERITY_TO_STATUS[rule.severity],
        category=rule.category,
        message=result.message,
        details=details,
    )


def _build_apply_spec(result: CrossSourceFinding) -> dict[str, Any] | None:
    """The undisclosed-debt rule's APPLY→recompute spec (add the credit-report obligation).

    Mirrors the AI layer's ``add_liability`` spec so the same human-applies→DTI-recomputes
    interlock fires (LP-75/76). Only the undisclosed-debt rule has a deterministic
    remediation; the rest are surfaced for human review.
    """
    if result.rule.rule_id != "xsrc.liability.undisclosed_debt":
        return None
    if result.document_value is None or result.document_value == "unknown":
        return None
    holder = result.subject_key.removeprefix("undisclosed:")
    return {
        "action": "add_liability",
        "liability_type": "Installment",
        "monthly_payment": result.document_value,
        "holder_name": holder,
    }


# --------------------------------------------------------------------------- #
# Build the cross-source facts from the assembled stated-vs-verified context
# --------------------------------------------------------------------------- #


async def build_cross_source_facts(
    db: AsyncSession, *, loan_file: LoanFile, context: dict[str, Any]
) -> CrossSourceFacts:
    """Build the :class:`CrossSourceFacts` from the assembled context + the subject property.

    Populates the facts the typed data readily supports today — names across sources, the
    driver's-license address vs the subject property, stated income, stated employers + the
    income-item count, documented employers, stated liabilities, and a stated gift's letter
    presence. The Tier-2 / not-yet-promoted facts (credit-report liabilities, contract price,
    documented income amount, occupancy evidence) are left empty — their checks then produce
    nothing (graceful), honestly pending promotion, exactly like LP-83..85.
    """
    stated = context.get("stated", {})
    borrowers: list[dict[str, Any]] = stated.get("borrowers", [])
    documents: list[dict[str, Any]] = context.get("verified_documents", [])

    subject_address = await _subject_property_address(db, loan_file.id)

    # Names across sources: each borrower (application) + name-like document fields.
    names: list[SourcedValue] = [
        SourcedValue(b["name"], "application") for b in borrowers if b.get("name")
    ]
    dl_address: SourcedValue | None = None
    documented_employers: list[str] = []
    for doc in documents:
        doc_type = doc.get("document_type") or "document"
        fields: dict[str, Any] = doc.get("fields", {})
        for key in _NAME_KEYS:
            value = _field_value(fields, key)
            if value is not None:
                names.append(SourcedValue(value, doc_type))
                break
        if doc_type == "drivers_license":
            for key in _ADDRESS_KEYS:
                value = _field_value(fields, key)
                if value is not None:
                    dl_address = SourcedValue(value, doc_type)
                    break
        for key in _EMPLOYER_KEYS:
            value = _field_value(fields, key)
            if value is not None:
                documented_employers.append(value)
                break

    # Stated income + employers (employment items only).
    stated_income = Decimal(0)
    income_item_count = 0
    stated_employers: list[str] = []
    for b in borrowers:
        for item in b.get("income_items", []):
            if item.get("employment_income"):
                income_item_count += 1
                amount = _to_decimal(item.get("monthly_amount"))
                if amount is not None:
                    stated_income += amount
        stated_employers.extend(e["name"] for e in b.get("employers", []) if e.get("name"))

    stated_liabilities = tuple(
        ObligationRef(
            key=(liability.get("holder_name") or liability.get("liability_type") or ""),
            amount=_to_decimal(liability.get("monthly_payment")),
            source="application",
        )
        for liability in stated.get("liabilities", [])
        if (liability.get("holder_name") or liability.get("liability_type"))
    )

    gift_amount, gift_letter_present = _gift_facts(stated.get("assets", []), documents)

    return CrossSourceFacts(
        names=tuple(names),
        subject_property_address=subject_address,
        dl_address=dl_address,
        stated_income_monthly=stated_income if income_item_count else None,
        stated_employers=tuple(stated_employers),
        documented_employers=tuple(documented_employers),
        stated_employer_count=len(stated_employers) or None,
        income_item_count=income_item_count or None,
        stated_liabilities=stated_liabilities,
        gift_amount=gift_amount,
        gift_letter_present=gift_letter_present,
    )


def _gift_facts(
    assets: list[dict[str, Any]], documents: list[dict[str, Any]]
) -> tuple[Decimal | None, bool | None]:
    """A stated gift's total + whether a gift-letter document is present (else ``None``)."""
    gift_total = Decimal(0)
    for asset in assets:
        asset_type = (asset.get("asset_type") or "").lower()
        if "gift" in asset_type:
            amount = _to_decimal(asset.get("value"))
            if amount is not None:
                gift_total += amount
    if gift_total <= 0:
        return None, None
    has_letter = any(
        (doc.get("document_type") or "") in ("gift_letter", "gift_funds") for doc in documents
    )
    return gift_total, has_letter


async def _subject_property_address(db: AsyncSession, loan_file_id: UUID) -> str | None:
    stmt = only_active(select(Property).where(Property.loan_file_id == loan_file_id), Property)
    prop = (await db.execute(stmt)).scalars().first()
    if prop is None:
        return None
    parts = [prop.address_line, prop.city, prop.state, prop.postal_code]
    joined = ", ".join(p for p in parts if p)
    return joined or None


def _field_value(fields: dict[str, Any], key: str) -> str | None:
    node = fields.get(key)
    if not isinstance(node, dict):
        return None
    value = node.get("value")
    return str(value) if value not in (None, "") else None


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError):
        return None
