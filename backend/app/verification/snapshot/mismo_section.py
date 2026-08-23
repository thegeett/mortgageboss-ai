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

**Deterministic ordering (the indices).** Indices are 1-based over a deterministic
ordering: borrowers by ``borrower_position`` (tie-break on id); nested
(income/employer) and file-level (liability/asset) collections by ascending row
``id``. The same input rows always produce the same keys — deterministic *within* a
run. The indices are **NOT stable across a change to the underlying rows**: soft-
deleting or adding a lower-ordered sibling shifts every subsequent index
(``income.3`` becomes ``income.2``), so a positional key is not a durable
identifier for a row across runs. The order is deterministic, not semantic
(``income.1`` is the lowest-id item, not "the base income").

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
from app.models.stated_financials import (
    StatedAsset,
    StatedLiability,
    StatedOwnedProperty,
)
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import SnapshotField
from app.verification.snapshot.pii import PiiField, PiiKind

_PARSED = FieldSource.PARSED


def _scalar(value: Any) -> str | int | float | bool | None:
    """Coerce a persisted value to a JSON scalar (Field.value rejects Decimal/date).

    An unhandled type **raises** rather than being stringified into a Python repr —
    a lossy ``str()`` catch-all would defeat ``Field.value``'s loud-fail guard and
    fabricate a value MISMO never carried. A new column of an unanticipated shape
    should surface here, not silently corrupt the snapshot.
    """
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
    raise TypeError(f"MISMO assembler cannot coerce {type(value).__name__} to a JSON scalar")


def _slug(text: str) -> str:
    """A compact key fragment from a free-text declaration name."""
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text.strip().lower())).strip("_")


def _active(rows: list[Any]) -> list[Any]:
    """Non-soft-deleted rows from an already-loaded collection (``SoftDeleteMixin``)."""
    return [r for r in rows if not r.is_deleted]


def build_mismo_section(
    *,
    loan_file: LoanFile,
    borrowers: list[Borrower],
    property_: Property | None,
    liabilities: list[StatedLiability],
    assets: list[StatedAsset],
    owned_properties: list[StatedOwnedProperty],
) -> dict[str, SnapshotField]:
    """Reshape already-loaded MISMO ORM rows into the flat snapshot ``mismo`` map.

    Pure (no DB, no mutation). ``NULL`` values are omitted (absent); the SSN routes
    through ``PiiField``; every other value becomes a parsed ``Field`` with a null
    confidence (a deterministic parse carries no per-field confidence — the
    ``source=parsed`` conveys certainty, and confidence is never fabricated).
    """
    out: dict[str, SnapshotField] = {}

    def put(key: str, value: Any, *, pii: PiiKind | None = None) -> None:
        """Emit one fact. ``pii`` routes sensitive values through ``PiiField`` (masked
        display + match-hash, raw never stored); everything else is a plain ``Field``.

        Absent (``NULL``) is omitted either way; a present-but-empty value is kept —
        for PII as a masked placeholder (``value is None`` is the absent test, never
        truthiness, so a blank SSN stays present-but-empty and doesn't masquerade as
        absent). Declaring PII per key means a new sensitive column can't be routed as
        a plain ``Field`` by accident.
        """
        if pii is not None:
            if value is None:  # absent — omit
                return
            out[key] = PiiField.from_raw(value, kind=pii, loan_file_id=loan_file.id, source=_PARSED)
            return
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
    # LP-494 — the loan APPLICATION date. CO-4's reserve floor is DATE-KEYED (Fannie LL-2026-03 raises
    # the minimum from 10% to 15% for applications dated on or after 2027-01-04), so the rule needs the
    # date the application was taken, not today's date. The column has always existed and populates on 22
    # of the 28 stored files; nothing emitted it, so no tag and no rule could see it. Keys here are free
    # strings by design ("so new facts never need a schema change"), so SNAPSHOT_VERSION is unaffected.
    put("loan.application_received_date", loan_file.application_received_date)

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
        # LP-509-B1 — the project indicators, which decide property.type when the export states
        # none. `in_project` is the decisive condo signal; attachment_type is not (detached
        # condominiums exist). Null → the fact is ABSENT, so the derivation abstains.
        put("property.in_project", property_.in_project)
        put("property.is_pud", property_.is_pud)

    # --- Borrowers (deterministic order: position, then id) ---------------
    for n, borrower in enumerate(
        sorted(_active(borrowers), key=lambda b: (b.borrower_position, str(b.id))), start=1
    ):
        base = f"borrower.{n}"
        # LP-332: the borrower_id ↔ MISMO-index link. `borrower.{n}` is a re-derived SORT POSITION
        # (not durable), so borrower-keyed materialization needs a snapshot-internal map from a
        # `belongs_to` UUID back to this index. Emitting the id here is that map — deterministic, PII-safe
        # (a UUID, not identity data), and the ONLY non-name-matching resolution (BorrowerRef rejects
        # name-matching). A borrower group with no id → the borrower subject cannot key it → couldnt_check.
        put(f"{base}.borrower_id", str(borrower.id))
        put(f"{base}.first_name", borrower.first_name)
        put(f"{base}.middle_name", borrower.middle_name)
        put(f"{base}.last_name", borrower.last_name)
        put(f"{base}.date_of_birth", borrower.date_of_birth)
        put(f"{base}.marital_status", borrower.marital_status)
        put(f"{base}.is_primary", borrower.is_primary)
        put(f"{base}.dependent_count", borrower.dependent_count)
        put(f"{base}.citizenship", borrower.citizenship)

        # SSN — the only MISMO PII: routed through put's PII path (masked display +
        # per-file match-hash, raw never stored). A NULL SSN is absent (omitted); a
        # present blank stays present-but-empty (a masked placeholder), not absent.
        put(f"{base}.ssn", borrower.ssn, pii=PiiKind.SSN)

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
            # LP-624 — the rest of the record. `is_current` was published from a column nothing wrote,
            # so this loop has been emitting one real field and one permanent null. The dates are what
            # an employment-gap check needs, the position is what a same-line-of-work judgment compares,
            # and `self_employed` is what decides whether tax returns are the right ask at all.
            put(f"{ekey}.self_employed", employer.self_employed)
            put(f"{ekey}.classification", employer.classification)
            put(f"{ekey}.position", employer.position)
            put(f"{ekey}.start_date", employer.start_date)
            put(f"{ekey}.end_date", employer.end_date)
            put(f"{ekey}.monthly_income", employer.monthly_income)
            put(f"{ekey}.special_relationship", employer.special_relationship)

        # declarations is a JSON column typed dict[str, str], but JSON can hold any
        # shape — guard against a non-dict value so a malformed row degrades to "no
        # declarations", never an AttributeError that fails the whole section.
        declarations = borrower.declarations
        if isinstance(declarations, dict):
            seen_slugs: dict[str, int] = {}
            for name, value in sorted(declarations.items()):
                # A declaration VALUE can also be non-scalar (JSON holds any shape). A
                # list/dict here must degrade to "skipped", not raise out of _scalar and
                # fail the whole MISMO section — same tolerance as the non-dict guard.
                if value is not None and not isinstance(value, (str, int, float, bool)):
                    continue
                # Two distinct declaration names can slug to the same key (they differ
                # only in punctuation/spacing); disambiguate deterministically so neither
                # indicator is silently overwritten (`x`, then `x.2`, `x.3`, …).
                slug = _slug(name)
                count = seen_slugs.get(slug, 0) + 1
                seen_slugs[slug] = count
                key = slug if count == 1 else f"{slug}.{count}"
                put(f"{base}.declaration.{key}", value)

    # --- File-level liabilities / assets (deterministic order: id) --------
    for k, liability in enumerate(sorted(_active(liabilities), key=lambda x: str(x.id)), start=1):
        lkey = f"liability.{k}"
        put(f"{lkey}.type", liability.liability_type)
        put(f"{lkey}.monthly_payment", liability.monthly_payment)
        put(f"{lkey}.unpaid_balance", liability.unpaid_balance)
        put(f"{lkey}.holder_name", liability.holder_name)
        # LP-572 — whether this obligation survives closing (LP-568). Projected so a rule can see
        # that a debt has ALREADY been excluded and stop asking. Deliberately NOT part of the
        # liability subject's identity hash: see `_MISMO_LIABILITY_ID_FIELDS` in enumerators.py —
        # flagging a payoff must not re-key the subject and orphan its existing findings.
        put(f"{lkey}.paid_off_at_closing", liability.paid_off_at_closing)

    for k, asset in enumerate(sorted(_active(assets), key=lambda x: str(x.id)), start=1):
        akey = f"asset.{k}"
        put(f"{akey}.type", asset.asset_type)
        put(f"{akey}.value", asset.value)
        put(f"{akey}.holder_name", asset.holder_name)

    # --- The real-estate-owned schedule (LP-596) --------------------------
    # THE POINT OF THE TICKET IS THIS LOOP. The parser has always retained these leaves, but only in
    # `catch_all`, which this section does not read and the snapshot therefore never carried. So the
    # rule engine could not see them and AS-4 / DT-6 / DT-8 reported they could not determine facts
    # the application states outright. Projecting them here is what makes them evaluable.
    #
    # No address: `_parse_owned_properties` deliberately does not read the nested PROPERTY/ADDRESS,
    # so there is no PII to route — every field below is a status, a count or an amount.
    for k, owned in enumerate(sorted(_active(owned_properties), key=lambda x: str(x.id)), start=1):
        okey = f"owned_property.{k}"
        put(f"{okey}.is_subject", owned.is_subject)
        put(f"{okey}.disposition_status", owned.disposition_status)
        put(f"{okey}.lien_upb", owned.lien_upb)
        put(f"{okey}.unit_count", owned.unit_count)
        put(f"{okey}.rental_income_gross", owned.rental_income_gross)
        put(f"{okey}.rental_income_net", owned.rental_income_net)
        put(f"{okey}.current_usage_type", owned.current_usage_type)
        put(f"{okey}.usage_type", owned.usage_type)
        put(f"{okey}.estimated_value", owned.estimated_value)

    return out


async def load_mismo_section(db: AsyncSession, loan_file: LoanFile) -> dict[str, SnapshotField]:
    """Load the persisted MISMO rows for a loan file and assemble the ``mismo`` section.

    The caller must pass a **company-scoped** ``loan_file`` (resolved through the
    tenant boundary): these queries scope only by ``loan_file_id`` (transitive
    company scope, ADR-052) and do no company check of their own.
    """

    async def _by_loan_file(model: type[Any], *options: Any) -> list[Any]:
        stmt = only_active(select(model).where(model.loan_file_id == loan_file.id), model)
        if options:
            stmt = stmt.options(*options)
        return list((await db.execute(stmt)).scalars().all())

    borrowers = await _by_loan_file(
        Borrower,
        selectinload(Borrower.stated_income_items),
        selectinload(Borrower.stated_employers),
    )
    property_ = (
        await db.execute(
            only_active(select(Property).where(Property.loan_file_id == loan_file.id), Property)
        )
    ).scalar_one_or_none()
    liabilities = await _by_loan_file(StatedLiability)
    assets = await _by_loan_file(StatedAsset)
    owned_properties = await _by_loan_file(StatedOwnedProperty)
    return build_mismo_section(
        loan_file=loan_file,
        borrowers=borrowers,
        property_=property_,
        liabilities=liabilities,
        assets=assets,
        owned_properties=owned_properties,
    )
