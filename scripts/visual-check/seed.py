"""Build one Stage 3 screen's state on a SCRATCH database (LP-934). Dev only.

    DATABASE_URL=postgresql+asyncpg://…/mbai_visual_stage3 \\
        uv run --project backend python scripts/visual-check/seed.py S3-02

`run.sh` is the usual way in; it creates and migrates the scratch database first. This script prints
one JSON line on stdout — the page to open, the moment to freeze the clock at, and the clicks that
open the screen — and `shoot.mjs` reads it.

NEVER THE DEV DATABASE. The database name must start with `mbai_visual_`, and it must differ from the
name in `backend/.env`. Both are checked before anything is imported that could connect.

EVERYTHING HERE IS FICTIONAL (ADR-405): the file the Stage 3 screens draw — Alex Rivera, LF-R7QK,
United Wholesale Mortgage, $242,199, 100 Example Ln — and round 1 of the `uwm_round1` fixture, rendered
as a PDF and taken through the real parse and import. Timestamps are stamped afterwards so the page
reads the README's "Today" table.

A STATE A LATER TICKET BUILDS says so. Each Stage 3 ticket adds its screens' builders to `STATES`.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

_REPO = Path(__file__).resolve().parents[2]
_BACKEND = _REPO / "backend"
_PREFIX = "mbai_visual_"
ET = ZoneInfo("America/New_York")


def _database_name(url: str) -> str:
    return urlparse(url.replace("+asyncpg", "")).path.lstrip("/")


def _dev_database_name() -> str | None:
    env_file = _BACKEND / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            return _database_name(line.split("=", 1)[1].strip().strip("\"'"))
    return None


def _refuse_unless_scratch() -> str:
    url = os.environ.get("DATABASE_URL", "")
    name = _database_name(url)
    if not name.startswith(_PREFIX):
        sys.exit(
            f"refused: DATABASE_URL names {name!r}; a visual-check database starts {_PREFIX!r}"
        )
    if name == _dev_database_name():
        sys.exit(f"refused: {name!r} is the dev database named in backend/.env")
    return name


# Checked BEFORE `app` is imported: its settings would otherwise connect to whatever DATABASE_URL says.
SCRATCH_DB = _refuse_unless_scratch() if __name__ == "__main__" else ""
sys.path.insert(0, str(_BACKEND))

from app.core.database import async_session_maker  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import Company, User, UserRole  # noqa: E402
from app.models.activity_log import (  # noqa: E402
    ActivityLog,
    ActivityType,
)
from app.models.borrower import Borrower  # noqa: E402
from app.models.condition import Condition  # noqa: E402
from app.models.condition_event import ConditionEvent, ConditionEventKind  # noqa: E402
from app.models.condition_round import ConditionRound, ConditionSourceKind  # noqa: E402
from app.models.document import Document, DocumentStatus  # noqa: E402
from app.models.lender import Lender, LoanProgram  # noqa: E402
from app.models.loan_file import LoanFile, LoanFileStatus, LoanPurpose  # noqa: E402
from app.models.property import OccupancyType, Property, PropertyType  # noqa: E402
from app.models.stated_financials import StatedIncomeItem, StatedLiability  # noqa: E402
from app.schemas.dti import DtiOverrideInput  # noqa: E402
from app.scripts.seed_lender_codes import seed_lender_codes  # noqa: E402
from app.services.condition_import import import_round  # noqa: E402
from app.services.condition_rounds import SheetBytes, create_round_from_sheet  # noqa: E402
from app.services.dti import (  # noqa: E402
    HOUSING_HOA,
    HOUSING_INSURANCE,
    HOUSING_MORTGAGE_INSURANCE,
    HOUSING_TAXES,
    monthly_principal_interest,
    set_dti_override,
)
from app.services.loan_files import create_loan_file  # noqa: E402
from app.tasks.conditions import parse_round  # noqa: E402
from sqlalchemy import delete, select, update  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402
from tests.conditions.fixture_helpers import UWM_ROUND_1  # noqa: E402
from tests.conditions.uwm_pdf_fixture import render_uwm_pdf  # noqa: E402

# The seeded processor. Dev-only credentials on a scratch database; not a secret.
PROCESSOR_EMAIL = "priya.raman@northstar-visual.com"
PROCESSOR_PASSWORD = "visual-check-only"  # pragma: allowlist secret
DISPLAY_ID = "LF-R7QK"

# From the round-1 letter (fixture `uwm_round1_2026-08-28.txt`). Ratios: 32.51% / 40.36% of income.
MONTHLY_INCOME = Decimal("5741.32")
HOUSING_TOTAL = Decimal("1866.50")  # 32.51% x 5,741.32, rounded to the cent
OTHER_DEBTS = Decimal("450.70")  # 40.36% x 5,741.32 = 2,317.20, less housing
INSURANCE = Decimal("120.00")  # "In the file" on S3-09
MORTGAGE_INSURANCE = Decimal("88.00")


def et(month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=ET)


@dataclass
class Shot:
    """What `shoot.mjs` needs: where to go, when "now" is, and how to open the screen."""

    path: str
    now: datetime
    clicks: list[str] = field(default_factory=list)

    def as_json(self) -> str:
        return json.dumps(
            {
                "path": self.path,
                "now": self.now.isoformat(),
                "clicks": self.clicks,
                "email": PROCESSOR_EMAIL,
                "password": PROCESSOR_PASSWORD,
            }
        )


class NotBuiltYet(Exception):
    """This screen's state needs a Stage 3 ticket that has not landed."""


# --------------------------------------------------------------------------------------------- #
# The base: the file, round 1 imported at 08/28/2026 4:20 PM, nothing planned yet.
# --------------------------------------------------------------------------------------------- #


async def _company_and_processor(db: AsyncSession) -> tuple[Company, User]:
    company = Company(name="Northstar Home Loans", slug="northstar-visual", is_active=True)
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=PROCESSOR_EMAIL,
        hashed_password=hash_password(PROCESSOR_PASSWORD),
        first_name="Priya",
        last_name="Raman",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return company, user


async def _the_file(db: AsyncSession, company: Company) -> LoanFile:
    loan_file = await create_loan_file(db, company_id=company.id)
    loan_file.display_id = DISPLAY_ID
    lender = Lender(
        company_id=company.id,
        name="United Wholesale Mortgage",
        slug="uwm-visual",
        supported_programs=["conventional"],
    )
    lender.canonical_lender_key = "uwm"
    db.add(lender)
    await db.flush()
    loan_file.lender_id = lender.id
    loan_file.loan_program = LoanProgram.CONVENTIONAL
    loan_file.loan_purpose = LoanPurpose.PURCHASE
    loan_file.status = LoanFileStatus.IN_CONDITIONS
    loan_file.loan_amount = Decimal("242199.00")
    loan_file.note_rate_percent = Decimal("6.3740")
    loan_file.amortization_months = 360
    loan_file.loan_officer_name = "Sam Moreno"
    loan_file.loan_officer_email = "sam.moreno@northstar-visual.com"
    borrower = Borrower(
        loan_file_id=loan_file.id,
        first_name="Alex",
        last_name="Rivera",
        email="alex.rivera@example.com",
        is_primary=True,
        borrower_position=1,
    )
    db.add(borrower)
    db.add(
        Property(
            loan_file_id=loan_file.id,
            address_line="100 Example Ln",
            city="Columbia",
            state="SC",
            postal_code="29201",
            purchase_price=Decimal("269111.00"),
            estimated_value=Decimal("270000.00"),
            # The letter's "Primary Residence". Without it the DTI gates on the rental check (LP-621).
            occupancy_type=OccupancyType.PRIMARY_RESIDENCE,
            property_type=PropertyType.SINGLE_FAMILY,
        )
    )
    await db.flush()
    db.add(
        StatedIncomeItem(borrower_id=borrower.id, monthly_amount=MONTHLY_INCOME, income_type="Base")
    )
    db.add(
        StatedLiability(
            loan_file_id=loan_file.id,
            liability_type="Installment",
            monthly_payment=OTHER_DEBTS,
            holder_name="Example Auto Finance",
        )
    )
    await db.flush()
    await seed_lender_codes(db)
    return loan_file


async def _housing(db: AsyncSession, loan_file: LoanFile, actor: User) -> None:
    """Pin the proposed housing payment to the letter's 32.51%: P&I is computed, the rest pinned."""
    pi = monthly_principal_interest(
        loan_file.loan_amount, loan_file.note_rate_percent, loan_file.amortization_months
    )
    assert pi is not None
    taxes = HOUSING_TOTAL - pi - INSURANCE - MORTGAGE_INSURANCE
    for key, amount in (
        (HOUSING_TAXES, taxes),
        (HOUSING_INSURANCE, INSURANCE),
        (HOUSING_MORTGAGE_INSURANCE, MORTGAGE_INSURANCE),
        (HOUSING_HOA, Decimal("0.00")),
    ):
        await set_dti_override(
            db,
            loan_file=loan_file,
            field_key=key,
            data=DtiOverrideInput(
                amount=amount.quantize(Decimal("0.01")), note="visual-check seed"
            ),
            actor_user_id=actor.id,
        )
    # Seed plumbing, not the file's story: keep the overrides' audit lines out of Recent activity.
    await db.execute(
        delete(ActivityLog).where(
            ActivityLog.loan_file_id == loan_file.id,
            ActivityLog.activity_type == ActivityType.DTI_OVERRIDDEN,
        )
    )


async def _credit_invoice(db: AsyncSession, loan_file: LoanFile) -> None:
    """The credit report invoice from 07/15 the file already holds, so 0006 is "Already in the file"
    (S3-02's "Found: Credit invoice 07/15, page 1"). A record only; fictional, no bytes stored."""
    db.add(
        Document(
            loan_file_id=loan_file.id,
            original_filename="credit-invoice.pdf",
            mime_type="application/pdf",
            file_size_bytes=1024,
            storage_path=f"{loan_file.company_id}/{loan_file.id}/credit-invoice.pdf",
            document_type="service_invoice",
            document_name="Credit invoice 07/15",
            status=DocumentStatus.COMPLETED,
            upload_source="user_upload",
        )
    )
    await db.flush()


async def _round_1(db: AsyncSession, loan_file: LoanFile, actor: User) -> ConditionRound:
    round_ = await create_round_from_sheet(
        db,
        loan_file=loan_file,
        sheet=SheetBytes(
            content=render_uwm_pdf(UWM_ROUND_1), source_kind=ConditionSourceKind.PDF_UPLOAD
        ),
        actor_user_id=actor.id,
    )
    await db.flush()
    await parse_round(db, round_.id)
    await db.refresh(round_)
    await import_round(db, round_=round_, actor_user_id=actor.id)
    return round_


async def _stamp(db: AsyncSession, loan_file: LoanFile, when: datetime) -> None:
    """Move everything written so far to the moment round 1 was imported."""
    for model in (ConditionRound, Condition, ActivityLog):
        await db.execute(
            update(model)
            .where(model.loan_file_id == loan_file.id)  # type: ignore[attr-defined]
            .values(created_at=when, updated_at=when)
        )
    condition_ids = select(Condition.id).where(Condition.loan_file_id == loan_file.id)
    await db.execute(
        update(ConditionEvent)
        .where(ConditionEvent.condition_id.in_(condition_ids))
        .values(occurred_at=when)
    )


async def base(db: AsyncSession) -> tuple[LoanFile, User]:
    """The file with round 1 imported (08/28/2026, 4:20 PM ET) and nothing planned."""
    company, user = await _company_and_processor(db)
    loan_file = await _the_file(db, company)
    await _housing(db, loan_file, user)
    await _credit_invoice(db, loan_file)
    await _round_1(db, loan_file, user)
    await _stamp(db, loan_file, et(8, 28, 16, 20))
    return loan_file, user


def _conditions_tab() -> str:
    return f"/loan-files/{DISPLAY_ID}/conditions"


async def state_base(db: AsyncSession) -> Shot:
    await base(db)
    return Shot(path=_conditions_tab(), now=et(8, 28, 16, 21))


async def read(db: AsyncSession, loan_file: LoanFile) -> None:
    """LP-919: read round 1 with the MOCKED model the tests use (`tests/conditions/reading_fixture`).

    Stamped to 4:21 PM, the moment S3-02's activity says the plan was ready.
    """
    from app.services import condition_reading
    from tests.conditions.reading_fixture import fake_complete

    round_ = await db.scalar(
        select(ConditionRound).where(ConditionRound.loan_file_id == loan_file.id)
    )
    assert round_ is not None
    condition_reading.complete = fake_complete()  # type: ignore[assignment]
    await condition_reading.read_round(db, round_id=round_.id)
    # LP-920: the plan is built straight from the reading, as the task does.
    from app.services.condition_plan import build_plan

    await build_plan(db, round_id=round_.id, today=date(2026, 8, 28))
    when = et(8, 28, 16, 21)
    condition_ids = select(Condition.id).where(Condition.loan_file_id == loan_file.id)
    await db.execute(
        update(ConditionEvent)
        .where(
            ConditionEvent.condition_id.in_(condition_ids),
            ConditionEvent.kind.in_(
                [ConditionEventKind.CONDITION_READ, ConditionEventKind.CONDITION_PLANNED]
            ),
        )
        .values(occurred_at=when)
    )
    await db.execute(
        update(ActivityLog)
        .where(
            ActivityLog.loan_file_id == loan_file.id,
            ActivityLog.activity_type == ActivityType.CONDITION_PLAN_READY,
        )
        .values(created_at=when, updated_at=when)
    )
    await db.execute(
        update(ConditionRound)
        .where(ConditionRound.loan_file_id == loan_file.id)
        .values(plan_ready_at=when)
    )


async def state_s3_01(db: AsyncSession) -> Shot:
    """6637's detail sheet: the reading, its three items and who acts (LP-919's part of S3-01)."""
    loan_file, _ = await base(db)
    await read(db, loan_file)
    return Shot(path=_conditions_tab(), now=et(8, 28, 16, 21), clicks=["6637"])


async def state_s3_02(db: AsyncSession) -> Shot:
    """The plan for round 1, before confirming, at 4:21 PM (0132 needs confirming)."""
    loan_file, _ = await base(db)
    await read(db, loan_file)
    return Shot(path=_conditions_tab(), now=et(8, 28, 16, 21))


async def state_s3_03(db: AsyncSession) -> Shot:
    """0132's reading below the bar, with S3-03's dialog open from its detail sheet."""
    loan_file, _ = await base(db)
    await read(db, loan_file)
    return Shot(
        path=_conditions_tab(), now=et(8, 28, 16, 21), clicks=["0132", "Confirm the reading"]
    )


def _later(ticket: str) -> Callable[[AsyncSession], Awaitable[Shot]]:
    async def build(db: AsyncSession) -> Shot:
        raise NotBuiltYet(f"this screen's state is built by {ticket}")

    return build


#: Screen → state builder. A ticket replaces its screens' `_later(...)` with a real builder.
STATES: dict[str, Callable[[AsyncSession], Awaitable[Shot]]] = {
    "base": state_base,
    "S3-01": state_s3_01,
    "S3-02": state_s3_02,
    "S3-03": state_s3_03,
    "S3-04": _later("LP-922"),
    "S3-05": _later("LP-922"),
    "S3-06": _later("LP-922"),
    "S3-07": _later("LP-923"),
    "S3-08": _later("LP-923"),
    "S3-09": _later("LP-924"),
    "S3-10": _later("LP-925"),
    "S3-11": _later("LP-925"),
    "S3-12": _later("LP-921"),
}


async def main(name: str) -> None:
    builder = STATES.get(name)
    if builder is None:
        sys.exit(f"unknown state {name!r}; known: {', '.join(STATES)}")
    async with async_session_maker() as db:
        try:
            shot = await builder(db)
        except NotBuiltYet as exc:
            sys.exit(f"{name}: {exc}")
        await db.commit()
    print(shot.as_json())


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: seed.py <state>   e.g. seed.py base, seed.py S3-02")
    asyncio.run(main(sys.argv[1]))


__all__: list[Any] = []
