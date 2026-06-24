"""LP-71.5 regression tests — the floor flush-timing fix + the AI-needs visibility.

FIX 1 (the proving test): a MISMO import whose stated data has employment income +
assets must produce the FULL deterministic floor (pay stubs + W-2 + bank statements
+ purchase agreement) on import — NOT just "Purchase agreement". The bug: the stated
rows were ``db.add``-ed but not flushed before ``seed_floor_needs``, and the session
runs ``autoflush=False``, so the floor's SELECTs couldn't see them. The fix flushes
first (inside ``seed_floor_needs``).

FIX 2 (visibility): the import marks ``ai_needs_status = PENDING`` (the async LP-69
reasoning is enqueued); a swallowed AI failure records ``FAILED``; a successful run
records ``COMPLETED``. The import + the floor succeed regardless (graceful).
"""

from decimal import Decimal
from pathlib import Path

import pytest
from app.core.config import settings
from app.mismo.import_service import create_loan_file_from_mismo
from app.mismo.schema import (
    ParsedAsset,
    ParsedBorrower,
    ParsedIncomeItem,
    ParsedLiability,
    ParsedLoan,
    ParsedMismo,
)
from app.models import Company
from app.models.loan_file import AiNeedsStatus
from app.models.needs_item import NeedsItem, NeedsItemOrigin
from app.storage import get_storage_backend
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture(autouse=True)
def storage_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the storage backend at an isolated temp dir (never real ./storage)."""
    monkeypatch.setattr(settings, "storage_local_path", str(tmp_path / "storage"))
    get_storage_backend.cache_clear()
    yield
    get_storage_backend.cache_clear()


async def _company(db: AsyncSession, slug: str = "acme") -> Company:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    return company


def _parsed_self_employed_purchase() -> ParsedMismo:
    """A Conventional Purchase with employment income + assets — the diagnostic's shape."""
    return ParsedMismo(
        loan=ParsedLoan(
            base_loan_amount=Decimal("400000"),
            loan_purpose="Purchase",
            mortgage_type="Conventional",
        ),
        borrowers=[
            ParsedBorrower(
                first_name="Mahesh",
                last_name="Chhotala",
                classification="Primary",
                income_items=[
                    ParsedIncomeItem(
                        monthly_amount=Decimal("7000"),
                        income_type="Base",
                        employment_income=True,
                    ),
                    ParsedIncomeItem(
                        monthly_amount=Decimal("9400"),
                        income_type="Base",
                        employment_income=True,
                    ),
                ],
                employers=["Chhotala Realty LLC"],
            )
        ],
        assets=[
            ParsedAsset(asset_type="GiftOfCash", value=Decimal("56000")),
            ParsedAsset(asset_type="RetirementFund", value=Decimal("120000")),
            ParsedAsset(asset_type="CheckingAccount", value=Decimal("18000")),
        ],
        liabilities=[
            ParsedLiability(liability_type="MortgageLoan", monthly_payment=Decimal("2100"))
        ],
    )


async def _floor_types(db: AsyncSession, loan_file_id) -> list[str]:
    rows = (
        await db.scalars(
            select(NeedsItem).where(
                NeedsItem.loan_file_id == loan_file_id,
                NeedsItem.origin == NeedsItemOrigin.FLOOR,
            )
        )
    ).all()
    return sorted(n.needs_type for n in rows if n.needs_type)


# --------------------------------------------------------------------------- #
# FIX 1 — the proving test
# --------------------------------------------------------------------------- #


async def test_floor_fires_employment_and_asset_rules_on_import(db_session: AsyncSession) -> None:
    """The bug fix: the floor sees the just-added stated rows → the full floor seeds."""
    company = await _company(db_session)
    lf = await create_loan_file_from_mismo(
        db_session,
        parsed=_parsed_self_employed_purchase(),
        company_id=company.id,
        raw_content=b"<MISMO/>",
    )

    floor = await _floor_types(db_session, lf.id)
    # Before the fix this was just ["purchase_agreement"]; now the employment +
    # asset rules fire because their SELECTs see the flushed rows.
    assert "pay_stub" in floor  # employment income → pay stubs
    assert "w2" in floor  # employment income → W-2
    assert "bank_statement" in floor  # stated assets → bank statements
    assert "purchase_agreement" in floor  # the purchase rule still fires
    assert "drivers_license" in floor  # universal: a Government ID for the borrower (LP-71.6)
    assert set(floor) == {
        "pay_stub",
        "w2",
        "bank_statement",
        "purchase_agreement",
        "drivers_license",
    }


async def test_floor_seeds_once_no_duplicates(db_session: AsyncSession) -> None:
    """The flush doesn't cause double-seeding — the floor is idempotent."""
    company = await _company(db_session)
    lf = await create_loan_file_from_mismo(
        db_session,
        parsed=_parsed_self_employed_purchase(),
        company_id=company.id,
        raw_content=b"<MISMO/>",
    )
    floor = await _floor_types(db_session, lf.id)
    assert len(floor) == len(set(floor))  # no duplicate needs_types
    # 4 conditional (pay_stub, w2, bank_statement, purchase_agreement) + 1 universal ID
    # (single borrower) = 5.
    assert len(floor) == 5


# --------------------------------------------------------------------------- #
# FIX 2 — the AI-needs visibility signal
# --------------------------------------------------------------------------- #


async def test_import_marks_ai_needs_pending(db_session: AsyncSession) -> None:
    """The import enqueues async reasoning → the file shows AI needs PENDING."""
    company = await _company(db_session)
    lf = await create_loan_file_from_mismo(
        db_session,
        parsed=_parsed_self_employed_purchase(),
        company_id=company.id,
        raw_content=b"<MISMO/>",
    )
    assert lf.ai_needs_status is AiNeedsStatus.PENDING
