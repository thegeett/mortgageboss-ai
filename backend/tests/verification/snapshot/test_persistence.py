"""Snapshot persistence (LP-209) — immutable per-run round-trip through the DB.

Covers: lossless persist→load (PII masked, confidence-null, source tags, absent≠empty
preserved through JSONB), write-once immutability (dup run_id raises, original row
unchanged), append-only history (two runs → two rows, both loadable), and the
PII-clean-at-rest write guard (raw PII rejected, not stored).
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.models import Company, SnapshotRecord
from app.services.loan_files import create_loan_file
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    CalcBreakdownLine,
    CalculationEntry,
    CalculationsSection,
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
)
from app.verification.snapshot.persistence import (
    RawPiiAtRestError,
    SnapshotAlreadyPersisted,
    load_snapshot,
    load_snapshots_for_loan_file,
    persist_snapshot,
)
from app.verification.snapshot.pii import PiiField, PiiKind
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _loan_file_id(db: AsyncSession):
    company = Company(name="Acme", slug=f"acme-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    lf = await create_loan_file(db, company_id=company.id)
    return lf.id


def _snapshot(loan_file_id, run_id):
    return Snapshot(
        loan_file_id=loan_file_id,
        run_id=run_id,
        created_at=datetime(2026, 7, 10, 12, 0, tzinfo=UTC),
        mismo=MismoSection.present(
            {
                "borrower.1.ssn": PiiField.from_raw(
                    "123-45-6789",
                    kind=PiiKind.SSN,
                    loan_file_id=loan_file_id,
                    source=FieldSource.PARSED,
                ),
                "loan.amount": Field.present("1160000.00", source=FieldSource.PARSED),
                "property.county": Field.missing(),  # absent
                "property.hoa_dues": Field.present(
                    None, source=FieldSource.PARSED
                ),  # present-empty
            }
        ),
        documents=DocumentsSection.present(
            [
                DocumentEntry(
                    content_id="docpaystub0000000",
                    document_type="pay_stub",
                    fields={
                        "gross_pay": Field.present(
                            "5700.00", source=FieldSource.EXTRACTED, confidence=0.94
                        )
                    },
                )
            ]
        ),
        calculations=CalculationsSection.present(
            dti=CalculationEntry(
                value={"back_end_dti": "43.10"},
                breakdown=[
                    CalcBreakdownLine(key="income.1", label="Base", amount="6000", source="stated")
                ],
            )
        ),
    )


async def test_persist_load_round_trips_losslessly(db_session: AsyncSession) -> None:
    lf_id = await _loan_file_id(db_session)
    run_id = uuid4()
    original = _snapshot(lf_id, run_id)

    await persist_snapshot(db_session, original)
    loaded = await load_snapshot(db_session, run_id)

    assert loaded == original  # full fidelity through the DB
    # spot-check the load-bearing bits survived JSONB
    ssn = loaded.mismo.facts["borrower.1.ssn"]
    assert isinstance(ssn, PiiField) and ssn.display == "***-**-6789"
    assert loaded.mismo.facts["property.county"].absent is True  # absent, not null
    assert loaded.mismo.facts["property.hoa_dues"].value is None  # present-empty
    assert loaded.documents.entries[0].fields["gross_pay"].confidence == 0.94
    assert loaded.calculations.dti.breakdown[0].source == "stated"


async def test_no_raw_pii_in_stored_json(db_session: AsyncSession) -> None:
    lf_id = await _loan_file_id(db_session)
    run_id = uuid4()
    await persist_snapshot(db_session, _snapshot(lf_id, run_id))
    row = await db_session.scalar(select(SnapshotRecord).where(SnapshotRecord.run_id == run_id))
    assert row is not None
    blob = str(row.snapshot_json)
    assert "123456789" not in blob
    assert "123-45-6789" not in blob


async def test_write_once_duplicate_run_raises_and_row_unchanged(db_session: AsyncSession) -> None:
    lf_id = await _loan_file_id(db_session)
    run_id = uuid4()
    await persist_snapshot(db_session, _snapshot(lf_id, run_id))

    # A second persist for the same run must not overwrite.
    with pytest.raises(SnapshotAlreadyPersisted):
        await persist_snapshot(db_session, _snapshot(lf_id, run_id))

    # Exactly one row for the run; the original is untouched.
    rows = (
        (await db_session.execute(select(SnapshotRecord).where(SnapshotRecord.run_id == run_id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1


async def test_append_only_history_two_runs_two_rows(db_session: AsyncSession) -> None:
    lf_id = await _loan_file_id(db_session)
    run_a, run_b = uuid4(), uuid4()
    await persist_snapshot(db_session, _snapshot(lf_id, run_a))
    await persist_snapshot(db_session, _snapshot(lf_id, run_b))

    # Both runs are independently loadable — the jump-back-to-a-previous-run guarantee.
    assert await load_snapshot(db_session, run_a) is not None
    assert await load_snapshot(db_session, run_b) is not None
    history = await load_snapshots_for_loan_file(db_session, lf_id)
    assert {s.run_id for s in history} == {run_a, run_b}


async def test_load_missing_run_returns_none(db_session: AsyncSession) -> None:
    assert await load_snapshot(db_session, uuid4()) is None


async def test_raw_pii_snapshot_is_rejected_not_stored(db_session: AsyncSession) -> None:
    """A snapshot carrying a RAW SSN (simulated assembler bug) must be refused."""
    lf_id = await _loan_file_id(db_session)
    run_id = uuid4()
    leaking = Snapshot(
        loan_file_id=lf_id,
        run_id=run_id,
        created_at=datetime(2026, 7, 10, 12, 0, tzinfo=UTC),
        # A raw SSN smuggled into an ordinary Field (what the guard must catch).
        mismo=MismoSection.present(
            {"borrower.1.ssn_leak": Field.present("123-45-6789", source=FieldSource.PARSED)}
        ),
    )
    with pytest.raises(RawPiiAtRestError):
        await persist_snapshot(db_session, leaking)
    # Nothing was stored.
    assert await load_snapshot(db_session, run_id) is None


async def test_raw_account_number_run_is_rejected(db_session: AsyncSession) -> None:
    lf_id = await _loan_file_id(db_session)
    run_id = uuid4()
    leaking = Snapshot(
        loan_file_id=lf_id,
        run_id=run_id,
        created_at=datetime(2026, 7, 10, 12, 0, tzinfo=UTC),
        mismo=MismoSection.present(
            {"asset.1.account_leak": Field.present("000123456789", source=FieldSource.PARSED)}
        ),
    )
    with pytest.raises(RawPiiAtRestError):
        await persist_snapshot(db_session, leaking)


def test_guard_allows_large_decimal_money_but_still_catches_bare_ids() -> None:
    """A large money amount ('123456789.00') must NOT trip the guard; a bare id must.

    Finding (c): a 9+-integer-digit amount was aborting the whole snapshot persist. The
    guard now excludes the integer part of a decimal number (money) while still flagging a
    bare-integer run (an unmasked account/SSN-without-dashes).
    """
    from app.verification.snapshot.persistence import _assert_no_raw_pii

    # $123M+ amount serialized as a JSON string — money, not an id → allowed.
    _assert_no_raw_pii('{"loan.amount": "123456789.00"}')
    _assert_no_raw_pii('{"amount": "1234567890.55"}')  # 10-int-digit money → allowed
    # A bare-integer id (no decimal) is still caught.
    with pytest.raises(RawPiiAtRestError):
        _assert_no_raw_pii('{"asset.account": "123456789"}')
    # A dashed SSN is still caught (unrelated alternative).
    with pytest.raises(RawPiiAtRestError):
        _assert_no_raw_pii('{"ssn": "123-45-6789"}')


async def test_build_persist_load_end_to_end(db_session: AsyncSession) -> None:
    """The durable Stage-1 artifact: LP-208 build → persist → load == built (incl. a masked SSN)."""
    from decimal import Decimal

    from app.models import Borrower
    from app.models.lender import LoanProgram
    from app.models.loan_file import LoanFile, LoanPurpose
    from app.models.property import Property
    from app.models.stated_financials import StatedAsset, StatedIncomeItem, StatedLiability
    from app.verification.snapshot.builder import build_snapshot

    company = Company(name="Acme", slug=f"acme-{uuid4().hex[:6]}")
    db_session.add(company)
    await db_session.flush()
    lf: LoanFile = await create_loan_file(db_session, company_id=company.id)
    lf.loan_program = LoanProgram.CONVENTIONAL
    lf.loan_purpose = LoanPurpose.PURCHASE
    lf.loan_amount = Decimal("400000.00")
    lf.note_amount = Decimal("400000.00")
    lf.note_rate_percent = Decimal("6.5000")
    lf.amortization_months = 360
    borrower = Borrower(
        loan_file_id=lf.id,
        first_name="Akash",
        last_name="Patel",
        ssn="123-45-6789",
        is_primary=True,
        borrower_position=1,
    )
    db_session.add(borrower)
    await db_session.flush()
    db_session.add(
        StatedIncomeItem(
            borrower_id=borrower.id, monthly_amount=Decimal("9000.00"), income_type="Base"
        )
    )
    db_session.add(
        StatedLiability(
            loan_file_id=lf.id, liability_type="Installment", monthly_payment=Decimal("500.00")
        )
    )
    db_session.add(
        StatedAsset(loan_file_id=lf.id, asset_type="CheckingAccount", value=Decimal("60000.00"))
    )
    db_session.add(
        Property(
            loan_file_id=lf.id,
            purchase_price=Decimal("500000.00"),
            estimated_value=Decimal("500000.00"),
        )
    )
    await db_session.flush()

    run_id = uuid4()
    built = await build_snapshot(
        db_session, loan_file_id=lf.id, run_id=run_id, company_id=company.id
    )
    # The built snapshot has a MASKED SSN — the guard must let it through, then round-trip.
    assert isinstance(built.mismo.facts["borrower.1.ssn"], PiiField)

    await persist_snapshot(db_session, built)
    loaded = await load_snapshot(db_session, run_id)
    assert loaded == built
