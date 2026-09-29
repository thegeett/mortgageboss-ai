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
from uuid import uuid4
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
from app.models.communication import Communication  # noqa: E402
from app.models.condition import Condition  # noqa: E402
from app.models.condition_event import ConditionEvent, ConditionEventKind  # noqa: E402
from app.models.condition_item import ConditionItem  # noqa: E402
from app.models.condition_round import ConditionRound, ConditionSourceKind  # noqa: E402
from app.models.condition_vocabulary import Performer  # noqa: E402
from app.models.document import Document, DocumentStatus  # noqa: E402
from app.models.lender import Lender, LoanProgram  # noqa: E402
from app.models.loan_file import LoanFile, LoanFileStatus, LoanPurpose  # noqa: E402
from app.models.property import OccupancyType, Property, PropertyType  # noqa: E402
from app.models.stated_financials import StatedIncomeItem, StatedLiability  # noqa: E402
from app.models.user import MailClient  # noqa: E402
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
        # She writes her email in Gmail (S3-04's "Copy & open Gmail"), a choice Phase 4 asks once.
        mail_client=MailClient.GMAIL,
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


async def _contacts(db: AsyncSession, loan_file: LoanFile) -> None:
    """LP-922: who the round's emails go to. Fictional (ADR-405); the underwriter is the letter's."""
    from app.models.lender_contact import LenderContact, LenderContactRole
    from app.models.loan_file_participant import LoanFileParticipant, ParticipantRole

    db.add(
        LoanFileParticipant(
            loan_file_id=loan_file.id,
            role=ParticipantRole.TITLE,
            name="Example Title & Escrow",
            email="closings@exampletitle.example",
        )
    )
    assert loan_file.lender_id is not None
    db.add(
        LenderContact(
            lender_id=loan_file.lender_id,
            name="Lena Brennan",
            email="underwriting@lender.example",
            role=LenderContactRole.UNDERWRITER,
            is_active=True,
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
    await _contacts(db, loan_file)
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
    """6637's detail sheet once the plan is confirmed: its items sit in drafts ("In borrower email ·
    draft", LP-922), the chips and the "Becomes …" line (LP-921), the reading (LP-919)."""
    return await _drafted(db, "6637")


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


async def confirm_plan(db: AsyncSession, loan_file: LoanFile, actor: User) -> None:
    """0132's reading confirmed as read, then the plan confirmed — at 4:40 PM, as S3-12's activity says."""
    from app.services.condition_plan import confirm_round_plan
    from app.services.condition_reading import ConfirmedItem, confirm_reading

    round_ = await db.scalar(
        select(ConditionRound).where(ConditionRound.loan_file_id == loan_file.id)
    )
    assert round_ is not None
    code_0132 = await db.scalar(
        select(Condition).where(
            Condition.loan_file_id == loan_file.id, Condition.lender_code == "0132"
        )
    )
    assert code_0132 is not None
    items = (
        await db.execute(
            select(ConditionItem)
            .where(ConditionItem.condition_id == code_0132.id, ConditionItem.deleted_at.is_(None))
            .order_by(ConditionItem.sequence)
        )
    ).scalars()
    await confirm_reading(
        db,
        condition=code_0132,
        items=[
            ConfirmedItem(
                name=item.name,
                performers=tuple(Performer(p) for p in item.performers) or (item.performer,),
                key=item.key,
            )
            for item in items
        ],
        actor_user_id=actor.id,
    )
    await confirm_round_plan(db, round_=round_, actor_user_id=actor.id)
    when = et(8, 28, 16, 40)
    round_.plan_confirmed_at = when
    await _stamp_events_since(db, loan_file, when, after=et(8, 28, 16, 22))
    await db.execute(
        update(ActivityLog)
        .where(
            ActivityLog.loan_file_id == loan_file.id,
            ActivityLog.activity_type == ActivityType.CONDITION_PLAN_CONFIRMED,
        )
        .values(created_at=when, updated_at=when)
    )


async def _stamp_events_since(
    db: AsyncSession, loan_file: LoanFile, when: datetime, *, after: datetime
) -> None:
    """Every condition event written by this seed after `after` (real time) is stamped `when`."""
    await db.flush()
    await db.execute(
        update(ConditionEvent)
        .where(ConditionEvent.loan_file_id == loan_file.id, ConditionEvent.occurred_at > after)
        .values(occurred_at=when)
    )


async def mark_round_sent(db: AsyncSession, loan_file: LoanFile, actor: User) -> None:
    """LP-922: the four drafts marked sent at 5:02 PM on 08/28 (borrower first, as S3-12 implies)."""
    from app.models.condition_draft import ConditionDraft
    from app.services.condition_drafts import mark_sent

    drafts = list(
        (
            await db.execute(
                select(ConditionDraft)
                .where(ConditionDraft.loan_file_id == loan_file.id)
                .order_by(ConditionDraft.created_at)
            )
        ).scalars()
    )
    order = ["borrower", "title_attorney", "lo", "underwriter"]
    for draft in sorted(drafts, key=lambda d: order.index(d.recipient.value)):
        await mark_sent(db, loan_file=loan_file, draft=draft, actor_user_id=actor.id)
    when = et(8, 28, 17, 2)
    await _stamp_events_since(db, loan_file, when, after=et(8, 28, 16, 41))
    await db.execute(
        update(Communication)
        .where(Communication.loan_file_id == loan_file.id, Communication.sent_at.is_not(None))
        .values(sent_at=when)
    )
    await db.execute(
        update(ActivityLog)
        .where(
            ActivityLog.loan_file_id == loan_file.id,
            ActivityLog.activity_type == ActivityType.COMMUNICATION_SENT,
        )
        .values(created_at=when, updated_at=when)
    )


async def statements_arrive(
    db: AsyncSession, loan_file: LoanFile, actor: User, *, complete: bool
) -> None:
    """LP-923: the borrower's statements arrive through the upload link on 09/02 at 9:14 AM.

    July has been in the file since 08/20 (a processor upload, before the plan — not re-checked).
    `complete=False` is S3-07 / S3-12's upload: August alone, pages 1-5 of 6 (LP-934 M1).
    `complete=True` is S3-08's: July and August together, 12 pages.
    """
    from app.services.condition_evidence import check_document
    from tests.conditions.statement_fixture import add_statement, august, july, july_and_august

    earlier = await add_statement(db, loan_file, july(), name="july.pdf", via_link=False)
    arrived = await add_statement(
        db,
        loan_file,
        july_and_august() if complete else august(pages_present=5),
        name="statements.pdf",
    )
    await db.execute(
        update(Document).where(Document.id == earlier.id).values(created_at=et(8, 20, 11, 5))
    )
    await db.execute(
        update(Document).where(Document.id == arrived.id).values(created_at=et(9, 2, 9, 14))
    )
    await check_document(db, document_id=arrived.id, today=date(2026, 9, 2))
    await _stamp_events_since(db, loan_file, et(9, 2, 9, 14), after=et(8, 28, 17, 3))


async def state_s3_07(db: AsyncSession) -> Shot:
    """6132's sheet on 09/02: the August statement arrived with page 6 missing."""
    loan_file, user = await base(db)
    await read(db, loan_file)
    await confirm_plan(db, loan_file, user)
    await mark_round_sent(db, loan_file, user)
    await statements_arrive(db, loan_file, user, complete=False)
    return Shot(path=_conditions_tab(), now=et(9, 2, 9, 30), clicks=["6132"])


async def state_s3_08(db: AsyncSession) -> Shot:
    """7086's sheet on 09/02: both months arrived, 12 pages, with the $4,000.00 mobile deposit."""
    loan_file, user = await base(db)
    await read(db, loan_file)
    await confirm_plan(db, loan_file, user)
    await mark_round_sent(db, loan_file, user)
    await statements_arrive(db, loan_file, user, complete=True)
    return Shot(path=_conditions_tab(), now=et(9, 2, 9, 30), clicks=["7086"])


async def state_s3_09(db: AsyncSession) -> Shot:
    """The figures check on 09/08: 7086's statements accepted (the deposit explained at 3:02 PM) and
    the new declarations page for the policy 6178 names in the file. Nothing applied yet."""
    from app.models.condition_evidence import ConditionEvidence
    from app.models.stated_financials import StatedAsset
    from app.services.condition_evidence import answer_finding
    from tests.conditions.statement_fixture import add_declarations

    loan_file, user = await base(db)
    # What the 1003 stated for the account: the letter's $11,062.18 verified.
    db.add(
        StatedAsset(
            loan_file_id=loan_file.id,
            asset_type="CheckingAccount",
            value=Decimal("11062.18"),
            holder_name="Alex Rivera",
        )
    )
    await read(db, loan_file)
    await confirm_plan(db, loan_file, user)
    await mark_round_sent(db, loan_file, user)
    await statements_arrive(db, loan_file, user, complete=True)
    seven = await db.scalar(
        select(Condition).where(
            Condition.loan_file_id == loan_file.id, Condition.lender_code == "7086"
        )
    )
    assert seven is not None
    for row in (
        await db.execute(
            select(ConditionEvidence).where(ConditionEvidence.condition_id == seven.id)
        )
    ).scalars():
        if row.findings:
            await answer_finding(
                db,
                condition=seven,
                evidence_id=row.id,
                index=0,
                answer="explained",
                reason="Gift from a relative; gift letter and transfer are in the file",
                actor_user_id=user.id,
            )
    await add_declarations(db, loan_file)
    await _stamp_events_since(db, loan_file, et(9, 8, 15, 2), after=et(9, 2, 9, 15))
    return Shot(path=_conditions_tab(), now=et(9, 8, 15, 10))


async def state_s3_12(db: AsyncSession) -> Shot:
    """The list on 09/02: the round's four emails sent 08/28, the 5-page August statement checked
    (6132, 7086 and 6637's clearance fail "All pages", D1/D2), and the deposit explanation asked."""
    from app.models.condition_evidence import ConditionEvidence
    from app.services.condition_evidence import answer_finding

    loan_file, user = await base(db)
    await read(db, loan_file)
    await confirm_plan(db, loan_file, user)
    await mark_round_sent(db, loan_file, user)
    await statements_arrive(db, loan_file, user, complete=False)
    seven = await db.scalar(
        select(Condition).where(
            Condition.loan_file_id == loan_file.id, Condition.lender_code == "7086"
        )
    )
    assert seven is not None
    rows = (
        await db.execute(
            select(ConditionEvidence).where(ConditionEvidence.condition_id == seven.id)
        )
    ).scalars()
    for row in rows:
        if row.findings:
            await answer_finding(
                db,
                condition=seven,
                evidence_id=row.id,
                index=0,
                answer="ask",
                reason=None,
                actor_user_id=user.id,
            )
    await _stamp_events_since(db, loan_file, et(9, 2, 9, 20), after=et(9, 2, 9, 15))
    return Shot(path=_conditions_tab(), now=et(9, 2, 9, 30))


def _pdf_bytes(name: str, pages: int) -> bytes:
    import pymupdf

    pdf = pymupdf.open()
    for number in range(pages):
        pdf.new_page().insert_text((72, 72), f"{name} page {number + 1}")
    content = bytes(pdf.tobytes())
    pdf.close()
    return content


async def _stored_document(
    db: AsyncSession,
    loan_file: LoanFile,
    name: str,
    document_type: str,
    pages: int,
    *,
    title: str | None = None,
) -> Document:
    """A completed PDF on the file with `pages` real pages, so the package counts and merges them."""
    from app.models.document import UploadSource
    from app.storage import get_storage_backend

    content = _pdf_bytes(name, pages)
    document = Document(
        id=uuid4(),
        loan_file_id=loan_file.id,
        original_filename=name,
        mime_type="application/pdf",
        file_size_bytes=len(content),
        storage_path="",
        document_type=document_type,
        document_name=title,
        status=DocumentStatus.COMPLETED,
        upload_source=UploadSource.USER_UPLOAD,
    )
    document.storage_path = await get_storage_backend().save(
        company_id=loan_file.company_id,
        file_id=loan_file.id,
        document_id=document.id,
        filename=name,
        content=content,
    )
    db.add(document)
    await db.flush()
    return document


async def state_s3_10(db: AsyncSession) -> Shot:
    """The package on 09/09 at 5:46 PM, 2 h 14 m before UWM's 8 PM ET cutoff: S3-09's state
    (figures not applied), and 7086, 6132, 6637, 0132, 6178 and 0006 Ready to send. 1228 (lender doing it) is still open.

    SEED SHORTCUTS, not product paths: 6637's receipt and 0132's three items are set done with their
    documents directly: the seed's receipt and disclosure are bare PDFs with no extraction, and nothing
    checks a signed disclosure. (Since the LP-938 follow-up a real `earnest_money_receipt` IS checked,
    by its own amount; the seed does not build one.) The notes come from a stand-in model that writes
    one line per condition.
    """
    import json
    from types import SimpleNamespace

    from app.ai import client
    from app.models.condition import ConditionPrepStatus
    from app.models.condition_item import ConditionItemStatus
    from app.schemas.condition import PrepStatusRequest
    from app.services import condition_package, figures_check
    from app.services.condition_plan import remove_item
    from app.services.condition_status import move_prep_status
    from app.storage import get_storage_backend

    shot = await state_s3_09(db)
    loan_file = await db.scalar(select(LoanFile).where(LoanFile.display_id == DISPLAY_ID))
    user = await db.scalar(select(User).where(User.email == PROCESSOR_EMAIL))
    assert loan_file is not None and user is not None
    conditions = {
        c.lender_code: c
        for c in (
            await db.execute(select(Condition).where(Condition.loan_file_id == loan_file.id))
        ).scalars()
    }

    async def items(code: str) -> dict[str, ConditionItem]:
        return {
            i.key: i
            for i in (
                await db.execute(
                    select(ConditionItem).where(
                        ConditionItem.condition_id == conditions[code].id,
                        ConditionItem.deleted_at.is_(None),
                    )
                )
            ).scalars()
        }

    # The base's credit invoice is a record with no bytes; the package counts and merges real pages.
    invoice = await db.scalar(
        select(Document).where(
            Document.loan_file_id == loan_file.id, Document.document_type == "service_invoice"
        )
    )
    assert invoice is not None
    invoice.storage_path = await get_storage_backend().save(
        company_id=loan_file.company_id,
        file_id=loan_file.id,
        document_id=invoice.id,
        filename=invoice.original_filename,
        content=_pdf_bytes("Credit invoice", 1),
    )
    seven = await items("7086")
    if "other_accounts" in seven:
        await remove_item(
            db, condition=conditions["7086"], item=seven["other_accounts"], actor_user_id=user.id
        )
    receipt = await _stored_document(
        db, loan_file, "EMD receipt.pdf", "other", 1, title="Earnest money receipt"
    )
    earnest = await items("6637")
    earnest["receipt"].document_id = receipt.id
    for item in earnest.values():
        item.status = ConditionItemStatus.DONE
    disclosure = await _stored_document(
        db, loan_file, "SC attorney disclosure.pdf", "other", 3, title="SC attorney disclosure"
    )
    wire = await _stored_document(
        db, loan_file, "Wire instructions.pdf", "other", 2, title="Wire instructions"
    )
    attorney = await items("0132")
    attorney["disclosure"].document_id = disclosure.id
    attorney["wire_instructions"].document_id = wire.id
    for item in attorney.values():
        item.status = ConditionItemStatus.DONE
    await db.flush()
    # 7086 was Waiting on Borrower and the plan moves only from To do, so removing its last owed item
    # leaves it Waiting (Stage 3A's rule); she moves it herself, as she does 6178.
    for code in ("7086", "6637", "0132", "6178"):
        condition = conditions[code]
        await db.refresh(condition)
        if condition.prep_status is not ConditionPrepStatus.READY:
            await move_prep_status(
                db,
                condition=condition,
                payload=PrepStatusRequest(to=ConditionPrepStatus.READY),
                actor_user_id=user.id,
            )

    notes = {
        "7086": "Capital One ··9912 July and August statements, all 12 pages; $41,914.42 verified "
        "against $38,210.40 required. The 08/21 deposit is sourced.",
        "6132": "Same Capital One ··9912 statements, all pages present; balance after closing "
        "costs covers the reserves required.",
        "6637": "Earnest money $2,850.00: title's receipt, and the check cleared on the August "
        "statement.",
        "0132": "SC attorney disclosure re-signed with the approved attorney; wire instructions "
        "match that attorney.",
        "0006": "Credit report invoice, already in the file.",
    }

    async def notes_model(**kwargs: Any) -> Any:
        return SimpleNamespace(text=json.dumps({"notes": notes}))

    # S3-10 follows S3-09 with the two figures applied (the design shows no figures check).
    check = await figures_check.figures_check(db, loan_file=loan_file)
    await figures_check.apply(
        db,
        loan_file=loan_file,
        expected=[
            {
                "key": c.key,
                "in_file": None if c.in_file is None else str(c.in_file),
                "from_evidence": str(c.from_evidence),
            }
            for c in check.changes
        ],
        actor_user_id=user.id,
    )
    client.complete = notes_model  # type: ignore[assignment]
    await condition_package.build(db, loan_file=loan_file, actor_user_id=user.id)
    await _stamp_events_since(db, loan_file, et(9, 9, 17, 40), after=et(9, 8, 15, 5))
    built = et(9, 9, 17, 46)
    await db.execute(
        update(ActivityLog)
        .where(ActivityLog.loan_file_id == loan_file.id, ActivityLog.created_at > et(9, 8, 15, 5))
        .values(created_at=built, updated_at=built)
    )
    return Shot(path=shot.path, now=built)


async def state_s3_11(db: AsyncSession) -> Shot:
    """Administration → Lenders → United Wholesale Mortgage, any day. The processor here is the
    company's admin (a seed choice; the screen is admin-only). 7812 is mapped to CR-05; 6521 waits."""
    from app.models.lender_condition_code import LenderCodeStatus, LenderConditionCode

    loan_file, user = await base(db)
    user.role = UserRole.ADMIN
    now = et(9, 9, 10, 0)
    for code, label, status, type_id, seen in (
        (
            "7812",
            "Provide signed and dated letter of explanation for the credit inquiry",
            LenderCodeStatus.MAPPED,
            "CR-05",
            3,
        ),
        (
            "6521",
            "Provide most recent paystub covering 30 days with year-to-date earnings.",
            LenderCodeStatus.OBSERVED_UNMAPPED,
            None,
            1,
        ),
    ):
        db.add(
            LenderConditionCode(
                lender_id=loan_file.lender_id,
                code=code,
                label=label,
                status=status,
                canonical_type_id=type_id,
                times_seen=seen,
                first_seen_at=now,
                last_seen_at=now,
            )
        )
    await db.flush()
    return Shot(path=f"/admin/lenders/{loan_file.lender_id}", now=now)


async def _drafted(db: AsyncSession, click: str) -> Shot:
    """Round 1 confirmed at 4:40 PM with its drafts made, and one draft opened."""
    loan_file, user = await base(db)
    await read(db, loan_file)
    await confirm_plan(db, loan_file, user)
    return Shot(path=_conditions_tab(), now=et(8, 28, 16, 41), clicks=[click])


async def state_s3_04(db: AsyncSession) -> Shot:
    return await _drafted(db, "Borrower · draft")


async def state_s3_05(db: AsyncSession) -> Shot:
    return await _drafted(db, "Title/attorney · draft")


async def state_s3_06(db: AsyncSession) -> Shot:
    return await _drafted(db, "Question 6178 · draft")


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
    "S3-04": state_s3_04,
    "S3-05": state_s3_05,
    "S3-06": state_s3_06,
    "S3-07": state_s3_07,
    "S3-08": state_s3_08,
    "S3-09": state_s3_09,
    "S3-10": state_s3_10,
    "S3-11": state_s3_11,
    "S3-12": state_s3_12,
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
