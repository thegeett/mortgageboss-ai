"""Stage-1 end-to-end capstone (LP-210).

Runs the COMPLETE pipeline — build (LP-208) → persist (LP-209) → load — on a
seeded, LF-6T3N-shaped loan file (2 borrowers, documents with links, assets,
property, all four calculators) and asserts the cross-ticket invariants that only
surface when the whole thing runs together on real-ish data:

* lossless build + DB round-trip (loaded == built);
* all three sections present + populated + metadata;
* CROSS-SECTION match-hash: a borrower's SSN in MISMO and that same person's W-2
  ``employee_ssn`` hash IDENTICALLY (same raw value, same per-file salt);
* belongsTo resolves to the correct borrower(s) — single + joint — with the RAW
  asserted name preserved separately in ``fields``;
* confidence honesty: MISMO confidence is always null; document confidence is
  faithful/nullable; nothing is fabricated;
* absent ≠ empty survives build → JSON → DB → load;
* honest None calculations (never a fabricated 0.0);
* NO raw PII at rest in the persisted ``snapshot_json``.

Deterministic (seeded, test DB) so it is CI-safe; the real LF-6T3N artifact is the
separate ``app/scripts/stage1_artifact.py`` deliverable.
"""

import json
import re
from decimal import Decimal
from uuid import uuid4

from app.models import (
    Borrower,
    Company,
    Document,
    ExtractionStatus,
    SnapshotRecord,
    UploadSource,
)
from app.models.document_borrower_link import DocumentBorrowerLink, MatchMethod
from app.models.lender import LoanProgram
from app.models.loan_file import LoanFile, LoanPurpose
from app.models.property import Property
from app.models.stated_financials import StatedAsset, StatedIncomeItem, StatedLiability
from app.services.extractions import create_extraction_version
from app.services.loan_files import create_loan_file
from app.verification.snapshot.builder import build_snapshot
from app.verification.snapshot.persistence import load_snapshot, persist_snapshot
from app.verification.snapshot.pii import PiiField
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Akash's SSN — deliberately the SAME on his MISMO borrower record AND his W-2, so
# the cross-section match-hash proof has a real pair.
_AKASH_SSN = "123-45-6789"


def _f(value: object, confidence: float | None = None) -> dict[str, object]:
    return {"value": value, "source": None, "confidence": confidence}


async def _seed_complete_file(db: AsyncSession) -> tuple[LoanFile, dict[str, Borrower]]:
    company = Company(name="Acme", slug=f"acme-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    lf = await create_loan_file(db, company_id=company.id)
    lf.loan_program = LoanProgram.CONVENTIONAL
    lf.loan_purpose = LoanPurpose.PURCHASE
    lf.loan_amount = Decimal("400000.00")
    lf.note_amount = Decimal("400000.00")
    lf.note_rate_percent = Decimal("6.5000")
    lf.amortization_months = 360

    akash = Borrower(
        loan_file_id=lf.id,
        first_name="Akash",
        last_name="Patel",
        ssn=_AKASH_SSN,
        is_primary=True,
        borrower_position=1,
    )
    priya = Borrower(
        loan_file_id=lf.id,
        first_name="Priya",
        last_name="Patel",
        ssn="987-65-4321",
        borrower_position=2,
    )
    db.add_all([akash, priya])
    await db.flush()
    db.add(
        StatedIncomeItem(
            borrower_id=akash.id, monthly_amount=Decimal("9000.00"), income_type="Base"
        )
    )
    db.add(
        StatedLiability(
            loan_file_id=lf.id, liability_type="Installment", monthly_payment=Decimal("500.00")
        )
    )
    db.add(StatedAsset(loan_file_id=lf.id, asset_type="CheckingAccount", value=Decimal("60000.00")))
    db.add(
        Property(
            loan_file_id=lf.id,
            purchase_price=Decimal("500000.00"),
            estimated_value=Decimal("500000.00"),
        )
    )

    async def _doc(slug: str, extracted: dict[str, object]) -> Document:
        d = Document(
            loan_file_id=lf.id,
            original_filename=f"{slug}.pdf",
            mime_type="application/pdf",
            file_size_bytes=1,
            storage_path=f"lf/{slug}.pdf",
            upload_source=UploadSource.USER_UPLOAD,
            document_type=slug,
        )
        db.add(d)
        await db.flush()
        await create_extraction_version(
            db,
            document_id=d.id,
            extracted_data=extracted,
            extraction_status=ExtractionStatus.SUCCEEDED,
        )
        return d

    pay = await _doc(
        "pay_stub", {"employee_name": _f("Akash Patel", 0.98), "gross_pay": _f("9000.00", 0.94)}
    )
    bank = await _doc(
        "bank_statement",
        {
            "account_holder_name": _f("Akash Patel and Priya Patel", 0.96),
            "account_number_masked": _f("****3312", 0.99),
        },
    )
    # W-2 carries Akash's RAW SSN (same value as his MISMO record) → cross-section hash.
    await _doc(
        "w2", {"employee_name": _f("Akash Patel", 0.9), "employee_ssn": _f(_AKASH_SSN, 0.95)}
    )
    await _doc(
        "appraisal", {"appraised_value": _f("500000.00", 0.96)}
    )  # no borrower → belongs_to None

    db.add_all(
        [
            DocumentBorrowerLink(
                document_id=pay.id, borrower_id=akash.id, confidence=1.0, method=MatchMethod.EXACT
            ),
            DocumentBorrowerLink(
                document_id=bank.id,
                borrower_id=akash.id,
                confidence=0.97,
                method=MatchMethod.NORMALIZED,
            ),
            DocumentBorrowerLink(
                document_id=bank.id,
                borrower_id=priya.id,
                confidence=0.97,
                method=MatchMethod.NORMALIZED,
            ),
        ]
    )
    await db.flush()
    return lf, {"akash": akash, "priya": priya}


async def test_stage1_end_to_end_build_persist_load(db_session: AsyncSession) -> None:
    lf, borrowers = await _seed_complete_file(db_session)
    run_id = uuid4()

    # --- The full chain -----------------------------------------------------
    built = await build_snapshot(
        db_session, loan_file_id=lf.id, run_id=run_id, company_id=lf.company_id
    )
    await persist_snapshot(db_session, built)
    loaded = await load_snapshot(db_session, run_id)

    # Lossless through build + DB.
    assert loaded == built

    # All three sections present + populated + metadata.
    assert loaded.loan_file_id == lf.id and loaded.run_id == run_id
    assert loaded.created_at.tzinfo is not None and loaded.snapshot_version == 1
    assert loaded.mismo.is_present and loaded.mismo.facts
    assert loaded.documents.is_present and loaded.documents.entries
    assert loaded.calculations.is_present

    # --- CROSS-SECTION match-hash: MISMO borrower SSN == W-2 employee_ssn ----
    ssn_mismo = loaded.mismo.facts["borrower.1.ssn"]
    w2 = next(e for e in loaded.documents.entries if e.document_type == "w2")
    ssn_doc = w2.fields["employee_ssn"]
    assert isinstance(ssn_mismo, PiiField) and isinstance(ssn_doc, PiiField)
    assert ssn_mismo.match_hash is not None
    assert ssn_mismo.match_hash == ssn_doc.match_hash  # same raw SSN → same hash (cross-source)
    assert ssn_mismo.display == ssn_doc.display == "***-**-6789"

    # --- belongsTo resolution (single + joint) + raw asserted name distinct --
    pay = next(e for e in loaded.documents.entries if e.document_type == "pay_stub")
    assert pay.belongs_to is not None and [r.borrower_id for r in pay.belongs_to] == [
        borrowers["akash"].id
    ]
    assert pay.fields["asserted_name"].value == "Akash Patel"  # raw name kept separately
    bank = next(e for e in loaded.documents.entries if e.document_type == "bank_statement")
    assert bank.belongs_to is not None and len(bank.belongs_to) == 2
    assert {r.name for r in bank.belongs_to} == {"Akash Patel", "Priya Patel"}
    appraisal = next(e for e in loaded.documents.entries if e.document_type == "appraisal")
    assert appraisal.belongs_to is None  # honest: no borrower resolved, not forced

    # --- Confidence honesty end-to-end -------------------------------------
    assert all(f.confidence is None for f in loaded.mismo.facts.values())  # MISMO: never fabricated
    assert pay.fields["gross_pay"].confidence == 0.94  # document: faithful
    assert pay.fields["employee_name"].confidence == 0.98

    # --- Absent ≠ empty survives the round trip ----------------------------
    # borrower.2 has no income items → those keys are absent (omitted), not present-null.
    assert not any(k.startswith("borrower.2.income") for k in loaded.mismo.facts)

    # --- Honest None calculations (never a fabricated 0.0) -----------------
    mi = loaded.calculations.mi
    assert mi is not None and mi.value["required"] is False
    assert mi.value["monthly_premium"] is None  # not required → honest null, not 0

    # --- NO raw PII at rest -------------------------------------------------
    row = await db_session.scalar(select(SnapshotRecord).where(SnapshotRecord.run_id == run_id))
    assert row is not None
    blob = json.dumps(row.snapshot_json)
    assert "123456789" not in blob and _AKASH_SSN not in blob
    assert not re.search(r"\d{3}-\d{2}-\d{4}|\b\d{9,}\b", blob)  # no SSN-shaped or long bare run
