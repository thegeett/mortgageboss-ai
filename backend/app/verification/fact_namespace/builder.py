"""The fact-builder (LP-118.6) — assemble the typed fact namespace from its scattered homes.

``assemble_fact_namespace(db, loan_file)`` gathers the THREE kinds of fact (ADR-239):

* **ENUM facts** — read directly from ``LoanFile`` / ``Property`` typed enum columns (no transform).
* **STATED-entity facts** — query the real rows (``Borrower`` + income/employers, ``StatedLiability``,
  ``StatedAsset``, ``Property``) and shape them into the graph (reusing the cross-source loading
  pattern — the same ``selectinload`` + ``only_active`` + ordering).
* **MATERIALIZED facts** — the documented side buried in extraction JSON: bank-statement
  ``transactions[]`` and documented employers, lifted into addressable facts (the LP-116 fact-wiring
  gap). Data with no schema yet (credit tradelines) or dropped at import (current address, county)
  is marked **ABSENT**, distinct from empty.

Raw category strings are canonicalized at build time (frozen into the snapshot). The derived
LTV/DTI/MI/reserves are computed **once** via the existing calculators. Nothing here executes a
verification rule.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.borrower import Borrower
from app.models.document import Document
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.models.property import Property
from app.models.stated_financials import StatedAsset, StatedLiability
from app.services.dti import build_dti_calculation
from app.services.ltv import build_ltv_calculation
from app.services.mi import compute_loan_mi
from app.verification.confidence import DEFAULT_CONFIDENCE_CUTOFF
from app.verification.fact_namespace.canonicalize import Canonicalizer
from app.verification.fact_namespace.snapshot import (
    AssetFacts,
    BorrowerFacts,
    ComputedFacts,
    DocumentedFacts,
    DocumentRef,
    EmployerFacts,
    Fact,
    FactNamespace,
    FactSource,
    FileFacts,
    IncomeItemFacts,
    LiabilityFacts,
    PropertyFacts,
    TransactionFacts,
)

# Document typed-field keys carrying an employer name (matches the legacy cross-source builder).
_EMPLOYER_KEYS = ("employer_name", "employer")


def _scalar(value: Any, *, source: FactSource) -> Fact[Any]:
    """A present fact if ``value`` is set, else an EMPTY fact (value None, not absent)."""
    if value is None:
        return Fact(value=None, source=None)
    return Fact.present(value, source=source)


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _field_value(extracted_data: dict[str, Any], key: str) -> str | None:
    """One typed-core extraction field's value (the ``{value, source}`` shape), or None."""
    node = extracted_data.get(key)
    if not isinstance(node, dict):
        return None
    value = node.get("value")
    return str(value) if value not in (None, "") else None


def _typed_field_values(extracted_data: dict[str, Any]) -> dict[str, str]:
    """The value-only typed-core fields of an extraction (skips the catch-all + nested lists) —
    mirrors ``services/cross_source._typed_fields`` but keeps just the value."""
    out: dict[str, str] = {}
    for key, node in extracted_data.items():
        if not isinstance(node, dict) or "value" not in node:
            continue
        value = node.get("value")
        if value not in (None, ""):
            out[key] = str(value)
    return out


# --------------------------------------------------------------------------- #
# Section builders
# --------------------------------------------------------------------------- #


def _build_file(loan_file: LoanFile) -> FileFacts:
    e = FactSource.ENUM
    return FileFacts(
        program=_scalar(loan_file.loan_program.value if loan_file.loan_program else None, source=e),
        loan_purpose=_scalar(
            loan_file.loan_purpose.value if loan_file.loan_purpose else None, source=e
        ),
        refinance_type=_scalar(
            loan_file.refinance_type.value if loan_file.refinance_type else None, source=e
        ),
        loan_amount=_scalar(loan_file.loan_amount, source=FactSource.STATED),
        note_amount=_scalar(loan_file.note_amount, source=FactSource.STATED),
        note_rate_percent=_scalar(loan_file.note_rate_percent, source=FactSource.STATED),
    )


def _build_borrowers(borrowers: list[Borrower], canon: Canonicalizer) -> list[BorrowerFacts]:
    s = FactSource.STATED
    out: list[BorrowerFacts] = []
    for b in borrowers:
        income_items = [
            IncomeItemFacts(
                monthly_amount=_scalar(item.monthly_amount, source=s),
                income_type_raw=item.income_type,
                income_type_canonical=canon.canonicalize("income_type", item.income_type),
                employment_income=item.employment_income,
            )
            for item in b.stated_income_items
            if item.deleted_at is None
        ]
        employers = [
            EmployerFacts(name=e.employer_name, is_current=e.is_current)
            for e in b.stated_employers
            if e.deleted_at is None
        ]
        out.append(
            BorrowerFacts(
                borrower_id=str(b.id),
                position=b.borrower_position,
                is_primary=b.is_primary,
                first_name=b.first_name,
                last_name=b.last_name,
                full_name=f"{b.first_name} {b.last_name}".strip() or None,
                # MASKED only — full SSN is never persisted (PII).
                ssn_masked=_scalar(b.masked_ssn, source=s),
                date_of_birth=_scalar(b.date_of_birth, source=s),
                # Parsed at MISMO import but not persisted (LP-118.7 store-everything).
                current_address=Fact.missing(source=FactSource.ABSENT_NOT_PERSISTED),
                income_items=income_items,
                employers=employers,
                documents=[],  # shaped for borrowers[].documents[]; linking is LP-118.8
            )
        )
    return out


def _build_property(prop: Property | None) -> PropertyFacts | None:
    if prop is None:
        return None
    s = FactSource.STATED
    parts = [prop.address_line, prop.city, prop.state, prop.postal_code]
    address = ", ".join(p for p in parts if p) or None
    return PropertyFacts(
        address=_scalar(address, source=s),
        county=Fact.missing(source=FactSource.ABSENT_NOT_PERSISTED),  # LP-118.7
        occupancy=_scalar(prop.occupancy_type.value if prop.occupancy_type else None, source=s),
        property_type=_scalar(
            prop.property_type.value if prop.property_type else None, source=FactSource.ENUM
        ),
        estimated_value=_scalar(prop.estimated_value, source=s),
        purchase_price=_scalar(prop.purchase_price, source=s),
        valuation_amount=_scalar(prop.valuation_amount, source=s),
    )


def _build_liabilities(rows: list[StatedLiability], canon: Canonicalizer) -> list[LiabilityFacts]:
    s = FactSource.STATED
    return [
        LiabilityFacts(
            liability_type_raw=r.liability_type,
            liability_type_canonical=canon.canonicalize("liability_type", r.liability_type),
            monthly_payment=_scalar(r.monthly_payment, source=s),
            unpaid_balance=_scalar(r.unpaid_balance, source=s),
            holder_name=r.holder_name,
        )
        for r in rows
    ]


def _build_assets(rows: list[StatedAsset], canon: Canonicalizer) -> list[AssetFacts]:
    s = FactSource.STATED
    return [
        AssetFacts(
            asset_type_raw=r.asset_type,
            asset_type_canonical=canon.canonicalize("asset_type", r.asset_type),
            # Legacy-parity gift detection (substring), so the CrossSourceFacts projection is
            # identical to today's ``_gift_facts``; the canonical value is for future rules.
            is_gift="gift" in (r.asset_type or "").lower(),
            value=_scalar(r.value, source=s),
            holder_name=r.holder_name,
        )
        for r in rows
    ]


def _build_documents_and_transactions(
    documents: list[Document],
) -> tuple[list[DocumentRef], list[TransactionFacts], list[str]]:
    """Document refs (file-level), materialized bank-statement transactions, and the documented
    employer names (for the documented-side facts)."""
    doc_refs: list[DocumentRef] = []
    transactions: list[TransactionFacts] = []
    documented_employers: list[str] = []

    for doc in documents:
        extraction = doc.current_extraction
        data = extraction.extracted_data if extraction is not None else {}
        doc_refs.append(
            DocumentRef(
                document_id=str(doc.id),
                document_type=doc.document_type,
                present=extraction is not None,
                current_extraction_id=str(extraction.id) if extraction is not None else None,
                fields=_typed_field_values(data),
            )
        )
        if extraction is None:
            continue

        for key in _EMPLOYER_KEYS:
            emp = _field_value(data, key)
            if emp is not None:
                documented_employers.append(emp)
                break

        if doc.document_type == "bank_statement":
            raw_txns = data.get("transactions")
            if isinstance(raw_txns, list):
                for txn in raw_txns:
                    if not isinstance(txn, dict):
                        continue
                    transactions.append(
                        TransactionFacts(
                            source_document_id=str(doc.id),
                            date=_scalar(
                                _parse_iso_date(txn.get("date")), source=FactSource.EXTRACTION
                            ),
                            amount=_scalar(
                                _to_decimal(txn.get("amount")), source=FactSource.EXTRACTION
                            ),
                            description=txn.get("description"),
                            transaction_type=txn.get("transaction_type"),
                        )
                    )
    return doc_refs, transactions, documented_employers


def _parse_iso_date(value: Any) -> Any:
    from datetime import date

    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _build_documented(documented_employers: list[str]) -> DocumentedFacts:
    """Materialized documented-side facts + the known-ABSENT markers (extractor gaps, LP-116)."""
    emp_fact: Fact[list[str]] = (
        Fact.present(documented_employers, source=FactSource.EXTRACTION)
        if documented_employers
        else Fact(value=[], source=FactSource.EXTRACTION)  # source exists, empty (not absent)
    )
    return DocumentedFacts(
        documented_employers=emp_fact,
        # Needs a YTD/period → monthly derivation (fact-builder gap + compute) — deferred to LP-120.
        documented_income_monthly=Fact.missing(source=FactSource.ABSENT_UNCOMPUTABLE),
        credit_tradelines=Fact.missing(
            source=FactSource.ABSENT_NO_SCHEMA
        ),  # credit_report: no schema
        documented_loan_amount=Fact.missing(
            source=FactSource.ABSENT_NO_SCHEMA
        ),  # note/CD: not extracted
        occupancy_evidence=Fact.missing(
            source=FactSource.ABSENT_NO_SCHEMA
        ),  # appraisal/lease: not extracted
    )


async def _build_computed(db: AsyncSession, loan_file: LoanFile, cutoff: float) -> ComputedFacts:
    """Compute-once: call the existing calculators ONCE and freeze their results. Uncomputable
    (missing inputs) → ABSENT, never zero."""
    c = FactSource.COMPUTED
    u = FactSource.ABSENT_UNCOMPUTABLE

    ltv_calc = await build_ltv_calculation(db, loan_file=loan_file, confidence_cutoff=cutoff)
    dti_calc = await build_dti_calculation(db, loan_file=loan_file, confidence_cutoff=cutoff)
    mi_calc = await compute_loan_mi(db, loan_file=loan_file, confidence_cutoff=cutoff)
    reserves_months = await _reserves_months(db, loan_file, cutoff)

    def ratio(value: Decimal | None) -> Fact[Decimal]:
        return Fact.present(value, source=c) if value is not None else Fact.missing(source=u)

    # MI: the calculator always runs. A None premium means "MI not required" (a real answer,
    # EMPTY not absent); a Decimal means the monthly premium.
    mi_premium = mi_calc.result.monthly_premium
    mi_fact = (
        Fact.present(mi_premium, source=c) if mi_premium is not None else Fact(value=None, source=c)
    )

    return ComputedFacts(
        ltv=ratio(ltv_calc.ltv),
        cltv=ratio(ltv_calc.cltv),
        hcltv=ratio(ltv_calc.hcltv),
        front_end_dti=ratio(dti_calc.front_end_dti),
        back_end_dti=ratio(dti_calc.back_end_dti),
        mi_monthly=mi_fact,
        reserves_months=reserves_months,
    )


async def _reserves_months(db: AsyncSession, loan_file: LoanFile, cutoff: float) -> Fact[Decimal]:
    """Reserves months via the public reserves view (reused, not re-derived). The view's numeric
    ``months_available`` is surfaced only in its formatted headline (``"<n> months"`` / ``"—"``),
    so we parse it back; ``"—"`` (uncomputable) → ABSENT."""
    from app.services.calculators import build_reserves_view

    view = await build_reserves_view(db, loan_file=loan_file, cutoff=cutoff)
    headline = view.headline or "—"
    token = headline.split(" ")[0]
    months = _to_decimal(token)
    if months is None:
        return Fact.missing(source=FactSource.ABSENT_UNCOMPUTABLE)
    return Fact.present(months, source=FactSource.COMPUTED)


# --------------------------------------------------------------------------- #
# The entry point
# --------------------------------------------------------------------------- #


async def assemble_fact_namespace(
    db: AsyncSession,
    loan_file: LoanFile,
    *,
    canonicalizer: Canonicalizer | None = None,
    confidence_cutoff: float = DEFAULT_CONFIDENCE_CUTOFF,
) -> FactNamespace:
    """Assemble the immutable, typed, entity-addressable fact namespace for one run (LP-118.6).

    Reads only — it does not execute a rule. Pass a ``canonicalizer`` to supply an AI fallback
    seam (LP-120); the default maps deterministically and records misses as ``UNMAPPED``.
    """
    canon = canonicalizer or Canonicalizer()

    borrowers = (
        (
            await db.execute(
                only_active(
                    select(Borrower)
                    .where(Borrower.loan_file_id == loan_file.id)
                    .options(
                        selectinload(Borrower.stated_income_items),
                        selectinload(Borrower.stated_employers),
                    )
                    .order_by(Borrower.borrower_position),
                    Borrower,
                )
            )
        )
        .scalars()
        .all()
    )
    prop = (
        (
            await db.execute(
                only_active(select(Property).where(Property.loan_file_id == loan_file.id), Property)
            )
        )
        .scalars()
        .first()
    )
    liabilities = (
        (
            await db.execute(
                only_active(
                    select(StatedLiability)
                    .where(StatedLiability.loan_file_id == loan_file.id)
                    .order_by(StatedLiability.created_at, StatedLiability.id),
                    StatedLiability,
                )
            )
        )
        .scalars()
        .all()
    )
    assets = (
        (
            await db.execute(
                only_active(
                    select(StatedAsset)
                    .where(StatedAsset.loan_file_id == loan_file.id)
                    .order_by(StatedAsset.created_at, StatedAsset.id),
                    StatedAsset,
                )
            )
        )
        .scalars()
        .all()
    )
    documents = (
        (
            await db.execute(
                only_active(
                    select(Document)
                    .where(Document.loan_file_id == loan_file.id)
                    .options(selectinload(Document.extractions))
                    .order_by(Document.created_at, Document.id),
                    Document,
                )
            )
        )
        .scalars()
        .all()
    )

    doc_refs, transactions, documented_employers = _build_documents_and_transactions(
        list(documents)
    )

    return FactNamespace(
        loan_file_id=str(loan_file.id),
        file=_build_file(loan_file),
        borrowers=_build_borrowers(list(borrowers), canon),
        property=_build_property(prop),
        liabilities=_build_liabilities(list(liabilities), canon),
        assets=_build_assets(list(assets), canon),
        documents=doc_refs,
        transactions=transactions,
        computed=await _build_computed(db, loan_file, confidence_cutoff),
        documented=_build_documented(documented_employers),
    )
