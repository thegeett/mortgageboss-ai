"""LP-421 — surface a tax return's nested Schedule C / Schedule E into the snapshot (the ADR-061 typed path).

The extractor already produces the schedules as TYPED CORE, but ``build_document_fields`` dropped them
(``_scalar`` returns None for a nested structure). These pin: the reshape surfaces Schedule C (self-employment,
IN-12) and the TWO-LEVEL Schedule E (rental + properties, IN-13) as typed ``Field``s; absent≠empty (no schedule
→ None, never a fabricated empty record); ``build_document_fields`` is UNCHANGED (still drops nested — the schedules
arrive via the separate path), so every other document maps byte-identically; the DB path surfaces them end to
end; and no rule/producer/activation moved.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.models.company import Company
from app.models.document import Document, UploadSource
from app.models.extraction import ExtractionStatus
from app.services.extractions import create_extraction_version
from app.services.loan_files import create_loan_file
from app.verification.eval.fire_path_scenarios import (
    build_self_employed_no_history_snapshot,
    build_tax_return_with_schedules_snapshot,
)
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.snapshot.documents_section import (
    build_document_fields,
    build_documents_section,
    build_schedule_c,
    build_schedule_e,
)
from sqlalchemy.ext.asyncio import AsyncSession
from tests.expected_active import EXPECTED_ACTIVE_RULE_COUNT

# DB tests run under pytest-asyncio auto mode (session-scoped db_session) — no pytest.mark.anyio (which would
# pull the module-scoped anyio_backend and clash with the session-scoped fixture, the ScopeMismatch).

_LF = UUID("00000000-0000-4000-8000-000000000abc")


def _tf(value: str | None, confidence: float | None = None) -> dict[str, Any]:
    """One extraction TypedField ({value, source, confidence}) as the stored dump carries it."""
    return {"value": value, "source": None, "confidence": confidence}


def _tax_return_extraction(*, with_schedules: bool = True) -> dict[str, Any]:
    core: dict[str, Any] = {"tax_year": _tf("2025"), "filing_status": _tf("single")}
    if not with_schedules:
        return core
    return {
        **core,
        "schedule_c": [
            {
                "business_name": _tf("Enterline Woodworks", 0.9),
                "gross_receipts": _tf("140000.00"),
                "total_expenses": _tf("58000.00"),
                "net_profit": _tf("82000.00", 0.9),
            }
        ],
        "schedule_e": {
            "total_net_rental_income": _tf("21000.00"),
            "depreciation": _tf("6600.00"),
            "properties": [
                {
                    "address": _tf("12 Oak St"),
                    "rents_received": _tf("18000.00"),
                    "total_expenses": _tf("7200.00"),
                    "net_income": _tf("10800.00"),
                },
                {
                    "address": _tf("9 Elm Ave"),
                    "rents_received": _tf("9600.00"),
                    "total_expenses": _tf("3400.00"),
                    "net_income": _tf("6200.00"),
                },
            ],
        },
        "k1s": [{"entity_name": _tf("Some LLC"), "ordinary_income": _tf("5000")}],
    }


# ======================================================================= #
# The reshape — Schedule C (self-employment) + the two-level Schedule E (rental)
# ======================================================================= #
def test_schedule_c_reaches_the_snapshot_typed() -> None:
    (rec,) = build_schedule_c(_tax_return_extraction(), "tax_return")
    assert rec.net_profit.value == "82000.00"  # the self-employment heart (IN-12)
    assert rec.net_profit.confidence == 0.9  # per-field confidence carried faithfully
    assert rec.business_name.value == "Enterline Woodworks"
    assert not rec.net_profit.absent


def test_schedule_e_two_level_structure_survives() -> None:
    se = build_schedule_e(_tax_return_extraction(), "tax_return")
    assert se is not None
    assert se.total_net_rental_income.value == "21000.00"
    assert len(se.properties) == 2  # the nested list — the shape most likely to be flattened
    assert se.properties[0].rents_received.value == "18000.00"  # the rental signal (IN-13)
    assert se.properties[1].address.value == "9 Elm Ave"


# ======================================================================= #
# Absent ≠ empty — no schedules → None, never a fabricated empty record
# ======================================================================= #
def test_no_schedules_is_absent_not_a_fabricated_empty() -> None:
    extraction = _tax_return_extraction(with_schedules=False)
    assert build_schedule_c(extraction, "tax_return") is None
    assert build_schedule_e(extraction, "tax_return") is None


def test_non_tax_return_document_has_no_schedules() -> None:
    # A schedule_c key on a NON-tax-return extraction must not surface (gated on document_type).
    assert build_schedule_c(_tax_return_extraction(), "pay_stub") is None
    assert build_schedule_e(_tax_return_extraction(), "w2") is None


def test_schedule_e_with_totals_but_no_properties_keeps_an_empty_property_tuple() -> None:
    # present-empty at the inner level (a Schedule E read, but no per-property detail) is DISTINCT from the whole
    # schedule being absent — the record exists with properties=(), not None.
    extraction = {"schedule_e": {"total_net_rental_income": _tf("21000.00"), "properties": []}}
    se = build_schedule_e(extraction, "tax_return")
    assert se is not None and se.properties == ()
    assert se.total_net_rental_income.value == "21000.00"


# ======================================================================= #
# D6 — build_document_fields is UNCHANGED (the every-document equivalence gate)
# ======================================================================= #
def test_build_document_fields_still_drops_schedules_flat_core_unchanged() -> None:
    # The shared function every document flows through must not gain the schedules (they arrive via the separate
    # path). Its output for a tax return is the flat 1040 core ONLY — no schedule_c / schedule_e / k1s keys.
    fields = build_document_fields(_tax_return_extraction(), "tax_return", loan_file_id=_LF)
    assert set(fields) == {"tax_year", "filing_status"}  # flat core only
    assert "schedule_c" not in fields and "schedule_e" not in fields and "k1s" not in fields
    assert fields["tax_year"].value == "2025"


# ======================================================================= #
# The DB path surfaces the schedules end to end; other documents are additive-None
# ======================================================================= #
async def _seed_and_build(db: AsyncSession, slug: str, extracted: dict[str, Any]):
    company = Company(name="Acme", slug="acme-lp421")
    db.add(company)
    await db.flush()
    lf = await create_loan_file(db, company_id=company.id)
    doc = Document(
        loan_file_id=lf.id,
        original_filename=f"{slug}.pdf",
        mime_type="application/pdf",
        file_size_bytes=1,
        storage_path=f"lf/{slug}.pdf",
        upload_source=UploadSource.USER_UPLOAD,
        document_type=slug,
    )
    db.add(doc)
    await db.flush()
    await create_extraction_version(
        db,
        document_id=doc.id,
        extracted_data=extracted,
        extraction_status=ExtractionStatus.SUCCEEDED,
    )
    from app.models.loan_file import LoanFile
    from sqlalchemy import select

    loan_file = (await db.execute(select(LoanFile).where(LoanFile.id == lf.id))).scalar_one()
    return await build_documents_section(db, loan_file)


async def test_db_path_surfaces_schedules_on_a_tax_return(db_session: AsyncSession) -> None:
    (entry,) = await _seed_and_build(db_session, "tax_return", _tax_return_extraction())
    assert entry.document_type == "tax_return"
    assert entry.schedule_c is not None and entry.schedule_c[0].net_profit.value == "82000.00"
    assert entry.schedule_e is not None and len(entry.schedule_e.properties) == 2
    # the flat core still surfaces as ordinary fields, unchanged
    assert entry.fields["tax_year"].value == "2025"


async def test_db_path_leaves_other_document_types_additive_none(db_session: AsyncSession) -> None:
    (entry,) = await _seed_and_build(
        db_session,
        "pay_stub",
        {"employee_name": _tf("Akash Patel", 0.9), "gross_pay": _tf("5700.00")},
    )
    assert (
        entry.schedule_c is None and entry.schedule_e is None
    )  # additive — non-tax-returns unaffected
    assert entry.fields["gross_pay"].value == "5700.00"  # its own fields byte-identical


# ======================================================================= #
# The fixture (D5) + LP-419's stub disposition
# ======================================================================= #
def test_fixture_carries_real_nested_schedules() -> None:
    snap = build_tax_return_with_schedules_snapshot()
    (tax_doc,) = snap.documents.entries
    assert tax_doc.document_type == "tax_return"
    assert tax_doc.schedule_c is not None and tax_doc.schedule_c[0].net_profit.value == "82000.00"
    assert tax_doc.schedule_e is not None and len(tax_doc.schedule_e.properties) == 2
    # what a producer (the NEXT ticket) reads: document-level schedule_c / schedule_e off the DocumentEntry
    assert tax_doc.schedule_e.properties[0].rents_received.value == "18000.00"


def test_lp419_stub_is_superseded_not_broken() -> None:
    # LP-419's self-employed fixture baked FLAT fields and no schedules (it materializes income.type via a stub
    # reasoner). It still builds; its tax_return carries schedule_c=None (a flat stub) — left alone, superseded by
    # the LP-421 fixture for the real-schedule path.
    snap = build_self_employed_no_history_snapshot()
    tax = next(e for e in snap.documents.entries if e.document_type == "tax_return")
    assert tax.schedule_c is None and tax.schedule_e is None


def test_no_rule_activation_changed() -> None:
    assert len(ACTIVE_RULE_IDS) == EXPECTED_ACTIVE_RULE_COUNT  # plumbing activates nothing
