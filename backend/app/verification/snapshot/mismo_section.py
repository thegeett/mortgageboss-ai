"""MISMO section assembler (LP-205, ADR-242).

Reads the already-parsed, persisted 1003/MISMO data (``LoanFile`` terms,
``Property``, ``Borrower`` + stated income/employers, file-level stated
liabilities/assets) and reshapes it into the snapshot's flat ``mismo`` section —
a ``dict[str, Field | PiiField]`` keyed by a stable dotted convention. It does NOT
parse MISMO (the importer already did) and touches no other section.

## Key-flattening convention (stable dotted keys)

    loan.<field>                        e.g. loan.amount, loan.note_rate_percent
    property.<field>                    e.g. property.city, property.estimated_value
    borrower.<n>.<field>                e.g. borrower.1.first_name, borrower.1.ssn (PII)
    borrower.<n>.income.<m>.<field>     e.g. borrower.1.income.1.monthly_amount
    borrower.<n>.employer.<m>.<field>   e.g. borrower.1.employer.1.name
    borrower.<n>.declaration.<slug>     the 1003 declaration indicators
    liability.<k>.<field>               e.g. liability.3.monthly_payment
    asset.<k>.<field>                   e.g. asset.2.value

**Stable ordering (the indices).** Indices are 1-based and derive from a STABLE,
immutable ordering — never volatile list position — so the same fact lands at the
same key across runs: borrowers by ``borrower_position`` (tie-break on id); nested
(income/employer) and file-level (liability/asset) collections by ascending row
``id`` (immutable). The order is deterministic, not semantic (``income.1`` is the
lowest-id item, not "the base income").

## Absent ≠ empty

A value the MISMO did not carry (a ``NULL`` column, or a missing sub-entity) is
**absent — its key is simply omitted**. A non-``NULL`` value is present, even if it
is an empty string (present-but-empty). Nulls are never emitted as present fields,
and nothing is fabricated.

## PII

The borrower SSN is the only PII in the persisted typed MISMO on this branch — it
routes through ``PiiField.from_raw`` (masked display + per-file match-hash, raw
never stored). Stated assets/liabilities carry no account-number column here, so
there is no account PII to route (a documented completeness gap; see the ticket).
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.borrower import Borrower
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.models.property import Property
from app.models.stated_financials import StatedAsset, StatedLiability
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import SnapshotField
from app.verification.snapshot.pii import PiiField, PiiKind

_PARSED = FieldSource.PARSED


def _scalar(value: Any) -> str | int | float | bool | None:
    """Coerce a persisted value to a JSON scalar (Field.value rejects Decimal/date)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, Enum):  # StrEnum etc. — coerce its underlying value
        return _scalar(value.value)
    if isinstance(value, (int, float, str)):
        return value
    if isinstance(value, Decimal):
        return str(value)  # exact money as a string
    if isinstance(value, date):  # date or datetime
        return value.isoformat()
    return str(value)


def _slug(text: str) -> str:
    """A compact key fragment from a free-text declaration name."""
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text.strip().lower())).strip("_")


def _active(rows: list[Any]) -> list[Any]:
    """Non-soft-deleted rows from an already-loaded child collection."""
    return [r for r in rows if getattr(r, "deleted_at", None) is None]


def build_mismo_section(
    *,
    loan_file: LoanFile,
    borrowers: list[Borrower],
    property_: Property | None,
    liabilities: list[StatedLiability],
    assets: list[StatedAsset],
) -> dict[str, SnapshotField]:
    """Reshape already-loaded MISMO ORM rows into the flat snapshot ``mismo`` map.

    Pure (no DB, no mutation). ``NULL`` values are omitted (absent); the SSN routes
    through ``PiiField``; every other value becomes a parsed ``Field`` with a null
    confidence (a deterministic parse carries no per-field confidence — the
    ``source=parsed`` conveys certainty, and confidence is never fabricated).
    """
    out: dict[str, SnapshotField] = {}

    def put(key: str, value: Any) -> None:
        scalar = _scalar(value)
        if scalar is None:  # absent — omit the key
            return
        out[key] = Field.present(scalar, source=_PARSED)

    # --- Loan terms -------------------------------------------------------
    put("loan.program", loan_file.loan_program)
    put("loan.purpose", loan_file.loan_purpose)
    put("loan.refinance_type", loan_file.refinance_type)
    put("loan.amount", loan_file.loan_amount)
    put("loan.note_amount", loan_file.note_amount)
    put("loan.note_rate_percent", loan_file.note_rate_percent)
    put("loan.amortization_type", loan_file.amortization_type)
    put("loan.amortization_months", loan_file.amortization_months)

    # --- Property ---------------------------------------------------------
    if property_ is not None:
        put("property.address_line", property_.address_line)
        put("property.address_line_2", property_.address_line_2)
        put("property.city", property_.city)
        put("property.state", property_.state)
        put("property.postal_code", property_.postal_code)
        put("property.type", property_.property_type)
        put("property.occupancy", property_.occupancy_type)
        put("property.estimated_value", property_.estimated_value)
        put("property.purchase_price", property_.purchase_price)
        put("property.valuation_amount", property_.valuation_amount)
        put("property.attachment_type", property_.attachment_type)
        put("property.construction_method", property_.construction_method)
        put("property.financed_unit_count", property_.financed_unit_count)

    # --- Borrowers (stable order: position, then id) ----------------------
    for n, borrower in enumerate(
        sorted(borrowers, key=lambda b: (b.borrower_position, str(b.id))), start=1
    ):
        base = f"borrower.{n}"
        put(f"{base}.first_name", borrower.first_name)
        put(f"{base}.middle_name", borrower.middle_name)
        put(f"{base}.last_name", borrower.last_name)
        put(f"{base}.date_of_birth", borrower.date_of_birth)
        put(f"{base}.marital_status", borrower.marital_status)
        put(f"{base}.is_primary", borrower.is_primary)
        put(f"{base}.dependent_count", borrower.dependent_count)
        put(f"{base}.citizenship", borrower.citizenship)

        # SSN — the only MISMO PII: masked display + per-file match-hash, raw never stored.
        if borrower.ssn:
            out[f"{base}.ssn"] = PiiField.from_raw(
                borrower.ssn, kind=PiiKind.SSN, loan_file_id=loan_file.id, source=_PARSED
            )

        for m, income in enumerate(
            sorted(_active(borrower.stated_income_items), key=lambda i: str(i.id)), start=1
        ):
            ikey = f"{base}.income.{m}"
            put(f"{ikey}.monthly_amount", income.monthly_amount)
            put(f"{ikey}.income_type", income.income_type)
            put(f"{ikey}.employment_income", income.employment_income)

        for m, employer in enumerate(
            sorted(_active(borrower.stated_employers), key=lambda e: str(e.id)), start=1
        ):
            ekey = f"{base}.employer.{m}"
            put(f"{ekey}.name", employer.employer_name)
            put(f"{ekey}.is_current", employer.is_current)

        for name, value in sorted((borrower.declarations or {}).items()):
            put(f"{base}.declaration.{_slug(name)}", value)

    # --- File-level liabilities / assets (stable order: id) ---------------
    for k, liability in enumerate(sorted(liabilities, key=lambda x: str(x.id)), start=1):
        lkey = f"liability.{k}"
        put(f"{lkey}.type", liability.liability_type)
        put(f"{lkey}.monthly_payment", liability.monthly_payment)
        put(f"{lkey}.unpaid_balance", liability.unpaid_balance)
        put(f"{lkey}.holder_name", liability.holder_name)

    for k, asset in enumerate(sorted(assets, key=lambda x: str(x.id)), start=1):
        akey = f"asset.{k}"
        put(f"{akey}.type", asset.asset_type)
        put(f"{akey}.value", asset.value)
        put(f"{akey}.holder_name", asset.holder_name)

    return out


async def load_mismo_section(db: AsyncSession, loan_file: LoanFile) -> dict[str, SnapshotField]:
    """Load the persisted MISMO rows for a loan file and assemble the ``mismo`` section."""
    borrowers = (
        (
            await db.execute(
                only_active(
                    select(Borrower).where(Borrower.loan_file_id == loan_file.id), Borrower
                ).options(
                    selectinload(Borrower.stated_income_items),
                    selectinload(Borrower.stated_employers),
                )
            )
        )
        .scalars()
        .all()
    )
    property_ = (
        await db.execute(
            only_active(select(Property).where(Property.loan_file_id == loan_file.id), Property)
        )
    ).scalar_one_or_none()
    liabilities = (
        (
            await db.execute(
                only_active(
                    select(StatedLiability).where(StatedLiability.loan_file_id == loan_file.id),
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
                    select(StatedAsset).where(StatedAsset.loan_file_id == loan_file.id),
                    StatedAsset,
                )
            )
        )
        .scalars()
        .all()
    )
    return build_mismo_section(
        loan_file=loan_file,
        borrowers=list(borrowers),
        property_=property_,
        liabilities=list(liabilities),
        assets=list(assets),
    )
