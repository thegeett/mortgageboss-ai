"""MISMO → models mapping + file-creation service (LP-53).

The single seam that knows both the MISMO parser (LP-51 ``ParsedMismo``) and the
domain models (LP-52): it maps a parsed MISMO into a fully-populated
:class:`~app.models.loan_file.LoanFile` and the stated-financials rows. The
parser and the models stay ignorant of each other.

Design:
- **Converges with manual creation** — reuses Epic 4's ``create_loan_file`` and
  ``create_property`` so a MISMO file is the *same* ``LoanFile`` (same model, same
  downstream) as a manually-created one. Borrowers are constructed directly only
  because they carry MISMO-only fields and need tolerant (non-``EmailStr``)
  handling + multi-borrower positioning; the resulting model is identical.
- **Import-directly / tolerant** — a partial parse still creates the file with
  what's present (missing → ``None``); ``parse_warnings`` are stored on the
  ``MismoImport`` record and surfaced later (LP-55/56). A defined **floor**: if
  there is *no* borrower **and** no loan at all, raise :class:`MismoImportError`.
- **Transactional** — this service ``flush``es; the caller (the LP-54 endpoint)
  ``commit``s, so the whole creation is one all-or-nothing transaction (a
  mid-creation failure rolls the whole thing back — no half-created file).
- **Exact** — money/rates are mapped as the parsed ``Decimal``s (no float drift);
  the stated data is the source-of-truth baseline.
- **PII-safe** — the SSN is stored only through the existing encrypted Borrower
  column and is **never logged**; logging is metadata-only (ids + counts); the
  raw MISMO file is stored access-controlled (tenant-scoped) and never logged.

Known gap: the MISMO *borrower* address has no typed column on ``Borrower`` (the
model carries only the subject-property address); it is parsed but not persisted
to a typed field. Adding a borrower address is a later model change.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.mismo.schema import ParsedBorrower, ParsedMismo
from app.models.activity_log import ActivityType
from app.models.borrower import Borrower, MaritalStatus
from app.models.lender import LoanProgram
from app.models.loan_file import AiNeedsStatus, LoanFile, LoanPurpose
from app.models.mismo_import import MismoImport, MismoImportStatus
from app.models.property import OccupancyType
from app.models.stated_financials import (
    StatedAsset,
    StatedEmployer,
    StatedIncomeItem,
    StatedLiability,
)
from app.schemas.property import PropertyCreate
from app.services.activity_log import log_activity
from app.services.loan_files import create_loan_file
from app.services.needs_engine import seed_floor_needs
from app.services.properties import create_property
from app.storage import get_storage_backend

logger = structlog.get_logger(__name__)

# MISMO category strings → our (small, stable) domain enums. Unknown → None
# (the file is still created; the field is just empty). MISMO category sets that
# are large/evolving (income/liability/asset types) stay flexible strings (LP-52).
_MARITAL: dict[str, MaritalStatus] = {
    "Married": MaritalStatus.MARRIED,
    "Unmarried": MaritalStatus.UNMARRIED,
    "Separated": MaritalStatus.SEPARATED,
}
_PROGRAM: dict[str, LoanProgram] = {
    "Conventional": LoanProgram.CONVENTIONAL,
    "FHA": LoanProgram.FHA,
}
_PURPOSE: dict[str, LoanPurpose] = {
    "Purchase": LoanPurpose.PURCHASE,
    "Refinance": LoanPurpose.REFINANCE,
}
_OCCUPANCY: dict[str, OccupancyType] = {
    "PrimaryResidence": OccupancyType.PRIMARY_RESIDENCE,
    "SecondHome": OccupancyType.SECOND_HOME,
    "Investment": OccupancyType.INVESTMENT,
}

_RAW_FILENAME = "mismo.xml"


class MismoImportError(Exception):
    """A parsed MISMO had nothing usable to create a file. Safe message only."""


async def create_loan_file_from_mismo(
    db: AsyncSession,
    *,
    parsed: ParsedMismo,
    company_id: UUID,
    raw_content: bytes,
    source_format: str | None = None,
    actor_user_id: UUID | None = None,
) -> LoanFile:
    """Map a :class:`ParsedMismo` into a populated, transactionally-created file.

    ``flush``es only — the caller commits (one atomic transaction). Raises
    :class:`MismoImportError` if there's essentially nothing usable (no borrower
    and no loan).
    """
    if not parsed.borrowers and parsed.loan is None:
        raise MismoImportError("MISMO file has no usable borrower or loan data.")

    loan = parsed.loan

    # 1) The LoanFile — reuse Epic 4's creation core (converges with manual).
    loan_file = await create_loan_file(
        db,
        company_id=company_id,
        loan_program=_PROGRAM.get(loan.mortgage_type) if loan and loan.mortgage_type else None,
        loan_purpose=_PURPOSE.get(loan.loan_purpose) if loan and loan.loan_purpose else None,
    )
    if loan is not None:
        loan_file.loan_amount = loan.base_loan_amount
        loan_file.note_amount = loan.note_amount
        loan_file.note_rate_percent = loan.note_rate_percent
        loan_file.lien_priority = loan.lien_priority
        loan_file.amortization_type = loan.amortization_type
        loan_file.amortization_months = loan.amortization_months
        loan_file.application_received_date = loan.application_received_date
    await db.flush()

    # 2) The subject property — reuse Epic 4's create_property, then the MISMO-only fields.
    prop_in = parsed.property
    if prop_in is not None:
        prop = await create_property(
            db,
            loan_file_id=loan_file.id,
            data=PropertyCreate(
                address_line=prop_in.address_line,
                city=prop_in.city,
                state=prop_in.state,
                postal_code=prop_in.postal_code,
                occupancy_type=(_OCCUPANCY.get(prop_in.usage_type) if prop_in.usage_type else None),
                estimated_value=prop_in.estimated_value,
                purchase_price=prop_in.sales_contract_amount,
            ),
        )
        prop.valuation_amount = prop_in.valuation_amount
        prop.attachment_type = prop_in.attachment_type
        prop.construction_method = prop_in.construction_method
        prop.financed_unit_count = prop_in.financed_unit_count

    # 3) Borrowers + their stated income / employers.
    for index, pb in enumerate(parsed.borrowers):
        borrower = _build_borrower(loan_file.id, pb, index)
        db.add(borrower)
        await db.flush()  # assign borrower.id for the child FKs
        for inc in pb.income_items:
            db.add(
                StatedIncomeItem(
                    borrower_id=borrower.id,
                    monthly_amount=inc.monthly_amount,
                    income_type=inc.income_type,
                    employment_income=inc.employment_income,
                )
            )
        for employer_name in pb.employers:
            db.add(StatedEmployer(borrower_id=borrower.id, employer_name=employer_name))

    # 4) File-level stated financials (liabilities/assets — deal-level, LP-52).
    for liab in parsed.liabilities:
        db.add(
            StatedLiability(
                loan_file_id=loan_file.id,
                liability_type=liab.liability_type,
                monthly_payment=liab.monthly_payment,
                unpaid_balance=liab.unpaid_balance,
                holder_name=liab.holder_name,
            )
        )
    for asset in parsed.assets:
        db.add(
            StatedAsset(
                loan_file_id=loan_file.id,
                asset_type=asset.asset_type,
                value=asset.value,
                holder_name=asset.holder_name,
            )
        )

    # 5) Catch-all + raw file (audit) + import record.
    raw_path = await get_storage_backend().save(
        company_id=company_id,
        file_id=loan_file.id,
        document_id=uuid4(),
        filename=_RAW_FILENAME,
        content=raw_content,
    )
    fmt = source_format or parsed.source_format
    db.add(
        MismoImport(
            loan_file_id=loan_file.id,
            source_format=fmt,
            status=(
                MismoImportStatus.PARTIAL if parsed.parse_warnings else MismoImportStatus.COMPLETED
            ),
            parse_warnings=parsed.parse_warnings or None,
            catch_all=[section.model_dump() for section in parsed.catch_all] or None,
            raw_file_path=raw_path,
        )
    )

    # The thin deterministic needs floor (LP-68) — near-certain needs seeded from
    # the stated MISMO data just persisted (employment → pay stubs + W-2; a purchase
    # → purchase agreement; stated assets → a bank statement). ``seed_floor_needs``
    # flushes first so it sees the rows added above (LP-71.5). LP-69 augments this.
    await seed_floor_needs(db, loan_file)

    # The import enqueues LP-69's async AI reasoning (the endpoint dispatches it after
    # commit). Mark it PENDING so a floor-only list isn't silently shown as complete —
    # the task flips it to COMPLETED / FAILED when it settles (LP-71.5). Informational,
    # never blocking: the floor above is independent of the AI.
    loan_file.ai_needs_status = AiNeedsStatus.PENDING

    # Audit activity (metadata only — converges with a manually-created file).
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.FILE_CREATED,
        summary="Loan file created from MISMO import",
        actor_user_id=actor_user_id,
        detail={
            "source": "mismo_import",
            "source_format": fmt,
            "borrowers": len(parsed.borrowers),
            "liabilities": len(parsed.liabilities),
            "assets": len(parsed.assets),
            "warnings": len(parsed.parse_warnings),
        },
    )

    await db.flush()

    # Metadata-only logging — NEVER the SSN, names, amounts, or raw content.
    logger.info(
        "mismo_import_created",
        loan_file_id=str(loan_file.id),
        borrowers=len(parsed.borrowers),
        liabilities=len(parsed.liabilities),
        assets=len(parsed.assets),
        source_format=fmt,
        warnings=len(parsed.parse_warnings),
    )
    return loan_file


def _build_borrower(loan_file_id: UUID, pb: ParsedBorrower, index: int) -> Borrower:
    """Construct a Borrower from a parsed borrower (SSN via the encrypted column).

    Built directly (not via ``create_borrower``) so it can carry the MISMO-only
    fields, tolerate a non-validating email, and position multiple borrowers; the
    resulting model is identical to a manually-created Borrower.
    """
    # classification "Primary"/"Secondary" → is_primary; default: first is primary.
    is_primary = pb.classification == "Primary" if pb.classification else index == 0
    return Borrower(
        loan_file_id=loan_file_id,
        first_name=pb.first_name or "",
        last_name=pb.last_name or "",
        ssn=pb.ssn,  # EncryptedString column → stored encrypted (Fernet)
        date_of_birth=pb.birth_date,
        email=pb.email,
        phone=pb.phone,
        marital_status=_MARITAL.get(pb.marital_status) if pb.marital_status else None,
        is_primary=is_primary,
        borrower_position=index + 1,
        dependent_count=pb.dependent_count,
        citizenship=pb.citizenship,
        declarations=pb.declarations or None,
    )
