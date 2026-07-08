"""Tests for the fact namespace (LP-118.6) — assembly, absent-vs-empty, canonicalization,
snapshot round-trip, and the CrossSourceFacts projection regression.

Scope: fact ASSEMBLY only. No test executes a verification rule (there is nothing to execute yet).
The projection test proves the namespace reproduces today's CrossSourceFacts byte-for-byte, so the
5 live rules would behave identically — the live path itself is untouched this ticket.
"""

from decimal import Decimal

from app.models.loan_file import LoanFile, LoanPurpose
from app.models.property import OccupancyType, PropertyType
from app.models.stated_financials import (
    StatedAsset,
    StatedEmployer,
    StatedIncomeItem,
    StatedLiability,
)
from app.models.verification import Verification, VerificationTrigger
from app.services.cross_source import assemble_cross_source_context
from app.services.cross_source_deterministic import build_cross_source_facts
from app.verification.fact_namespace import (
    Canonicalizer,
    assemble_fact_namespace,
    load_fact_snapshot,
    project_cross_source_facts,
    save_fact_snapshot,
)
from app.verification.fact_namespace.canonicalize import FallbackAnswer
from app.verification.fact_namespace.snapshot import FactSource
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.factories import (
    make_borrower,
    make_company,
    make_document,
    make_extraction,
    make_loan_file,
    make_property,
)


def _field(value: str) -> dict[str, object]:
    return {"value": value, "source": {"page": 1, "snippet": value}}


async def _build_full_file(db: AsyncSession) -> LoanFile:
    """A loan file with borrowers/income/employers, property, file-level liabilities + a gift asset,
    a W-2 + bank statement + gift letter (each extracted), and loan terms so LTV/DTI compute."""
    company = await make_company(db, slug="fnst")
    loan_file = await make_loan_file(db, company=company)
    loan_file.loan_program = None  # program unset → enum fact is empty/None (first-class)
    loan_file.loan_purpose = LoanPurpose.PURCHASE
    loan_file.loan_amount = Decimal("300000")
    loan_file.note_amount = Decimal("300000")
    loan_file.note_rate_percent = Decimal("6.5")
    loan_file.amortization_months = 360

    borrower = await make_borrower(
        db, loan_file=loan_file, ssn="123-45-6789", first_name="Robert", last_name="Smith"
    )
    from datetime import date

    borrower.date_of_birth = date(1985, 5, 1)
    db.add_all(
        [
            StatedIncomeItem(
                borrower_id=borrower.id,
                monthly_amount=Decimal("8000"),
                income_type="Base Pay",  # → maps to "employment"
                employment_income=True,
            ),
            StatedIncomeItem(
                borrower_id=borrower.id,
                monthly_amount=Decimal("500"),
                income_type="Moonlighting gig",  # → NOT in the map → UNMAPPED seam
                employment_income=False,
            ),
            StatedEmployer(borrower_id=borrower.id, employer_name="Novant", is_current=True),
        ]
    )

    prop = await make_property(db, loan_file=loan_file)
    prop.occupancy_type = OccupancyType.PRIMARY_RESIDENCE
    prop.property_type = PropertyType.SINGLE_FAMILY
    prop.purchase_price = Decimal("400000")
    prop.valuation_amount = Decimal("400000")
    prop.estimated_value = Decimal("400000")

    db.add_all(
        [
            StatedLiability(
                loan_file_id=loan_file.id,
                liability_type="Auto Loan",
                monthly_payment=Decimal("400"),
                holder_name="Big Bank",
            ),
            StatedAsset(
                loan_file_id=loan_file.id,
                asset_type="Gift of Cash",
                value=Decimal("10000"),
                holder_name="Mom",
            ),
            StatedAsset(
                loan_file_id=loan_file.id,
                asset_type="Checking",
                value=Decimal("25000"),
                holder_name="Robert Smith",
            ),
        ]
    )

    w2 = await make_document(db, loan_file=loan_file, company=company, document_type="w2")
    await make_extraction(
        db,
        document=w2,
        data={"employer_name": _field("Novant Health"), "employee_name": _field("Robert Smith")},
    )
    bank = await make_document(
        db, loan_file=loan_file, company=company, document_type="bank_statement"
    )
    await make_extraction(
        db,
        document=bank,
        data={
            "account_holder_name": _field("Robert Smith"),
            "transactions": [
                {
                    "date": "2026-01-15",
                    "amount": "5000",
                    "description": "Payroll",
                    "transaction_type": "deposit",
                },
                {
                    "date": "2026-01-20",
                    "amount": "1200",
                    "description": "Transfer",
                    "transaction_type": "deposit",
                },
            ],
        },
    )
    gift = await make_document(
        db, loan_file=loan_file, company=company, document_type="gift_letter"
    )
    await make_extraction(db, document=gift, data={"donor_name": _field("Mom")})

    await db.flush()
    return loan_file


async def test_assembles_typed_entity_graph(db_session: AsyncSession) -> None:
    loan_file = await _build_full_file(db_session)
    ns = await assemble_fact_namespace(db_session, loan_file)

    # Enum facts: purpose present, program unset (first-class None → empty, not absent).
    assert ns.file.loan_purpose.value == "purchase"
    assert ns.file.program.value is None and not ns.file.program.absent
    assert ns.file.loan_amount.value == Decimal("300000")

    # Per-borrower income + employers; file-level liabilities + assets.
    assert len(ns.borrowers) == 1
    b = ns.borrowers[0]
    assert b.date_of_birth.value == __import__("datetime").date(1985, 5, 1)
    assert b.ssn_masked.value and b.ssn_masked.value.endswith("6789")  # MASKED, last-4
    assert len(b.income_items) == 2
    assert [e.name for e in b.employers] == ["Novant"]
    assert b.documents == []  # shaped but unlinked (LP-118.8)
    assert len(ns.liabilities) == 1 and ns.liabilities[0].holder_name == "Big Bank"
    assert len(ns.assets) == 2
    assert any(a.is_gift for a in ns.assets)

    # Single property.
    assert ns.property is not None
    assert ns.property.occupancy.value == "primary_residence"

    # Materialized transactions from the bank statement JSON (buried → addressable).
    assert len(ns.transactions) == 2
    assert ns.transactions[0].amount.value == Decimal("5000")
    assert ns.transactions[0].date.value == __import__("datetime").date(2026, 1, 15)

    # Compute-once: LTV + DTI frozen as Decimals (inputs present → computable).
    assert ns.computed.ltv.value is not None and ns.computed.ltv.is_present
    assert ns.computed.back_end_dti.value is not None and ns.computed.back_end_dti.is_present


async def test_absent_is_distinct_from_empty(db_session: AsyncSession) -> None:
    loan_file = await _build_full_file(db_session)
    ns = await assemble_fact_namespace(db_session, loan_file)

    # ABSENT — no data source yet / dropped at import (never empty, never zero).
    assert ns.documented.credit_tradelines.absent
    assert ns.documented.credit_tradelines.source == FactSource.ABSENT_NO_SCHEMA
    assert ns.borrowers[0].current_address.absent
    assert ns.borrowers[0].current_address.source == FactSource.ABSENT_NOT_PERSISTED
    assert ns.property is not None and ns.property.county.absent

    # EMPTY (source exists, no rows) — documented employers present as a list, not absent.
    assert not ns.documented.documented_employers.absent
    assert ns.documented.documented_employers.value == ["Novant Health"]


async def test_uncomputable_computed_marked_absent(db_session: AsyncSession) -> None:
    # A file with NO property → LTV has no value basis → uncomputable → ABSENT (never 0).
    company = await make_company(db_session, slug="noprop")
    loan_file = await make_loan_file(db_session, company=company)
    loan_file.loan_amount = Decimal("200000")
    await db_session.flush()

    ns = await assemble_fact_namespace(db_session, loan_file)
    assert ns.computed.ltv.absent
    assert ns.computed.ltv.source == FactSource.ABSENT_UNCOMPUTABLE
    assert ns.computed.ltv.value is None  # absent, not zero


async def test_canonicalization_map_and_unmapped_seam(db_session: AsyncSession) -> None:
    loan_file = await _build_full_file(db_session)
    canon = Canonicalizer()
    ns = await assemble_fact_namespace(db_session, loan_file, canonicalizer=canon)

    items = {i.income_type_raw: i.income_type_canonical for i in ns.borrowers[0].income_items}
    # Mapped deterministically.
    assert items["Base Pay"].value == "employment"
    assert items["Base Pay"].source == FactSource.CANONICAL_MAP
    # Miss → UNMAPPED (never silently ignored); recorded for the eval set.
    assert items["Moonlighting gig"].value is None
    assert items["Moonlighting gig"].source == FactSource.UNMAPPED
    assert ("income_type", "Moonlighting gig") in canon.misses


async def test_canonicalization_ai_fallback_seam_is_deterministic(db_session: AsyncSession) -> None:
    # A stub fallback (LP-120 supplies the real AI one). The answer is learned + frozen.
    class StubFallback:
        def __init__(self) -> None:
            self.calls = 0

        def classify(self, field: str, raw: str, vocab: list[str]) -> FallbackAnswer | None:
            self.calls += 1
            return FallbackAnswer(canonical="other", confidence=0.6)

    stub = StubFallback()
    canon = Canonicalizer(fallback=stub)
    a = canon.canonicalize("income_type", "Moonlighting gig")
    b = canon.canonicalize(
        "income_type", "moonlighting gig"
    )  # same normalized key → learned, no 2nd call
    assert a.value == "other" and a.source == FactSource.CANONICAL_AI and a.confidence == 0.6
    assert b.value == "other"
    assert stub.calls == 1  # learned within the run


async def test_snapshot_persists_and_reloads_with_types(db_session: AsyncSession) -> None:
    loan_file = await _build_full_file(db_session)
    ns = await assemble_fact_namespace(db_session, loan_file)

    run = Verification(loan_file_id=loan_file.id, trigger=VerificationTrigger.MANUAL)
    db_session.add(run)
    await db_session.flush()
    save_fact_snapshot(run, ns)
    await db_session.flush()

    reloaded = load_fact_snapshot(run)
    assert reloaded is not None
    # Types intact across the JSON round-trip.
    assert isinstance(reloaded.file.loan_amount.value, Decimal)
    assert reloaded.computed.ltv.value == ns.computed.ltv.value
    assert reloaded.transactions[0].date.value == __import__("datetime").date(2026, 1, 15)
    assert reloaded.documented.credit_tradelines.absent


async def test_cross_source_projection_matches_legacy(db_session: AsyncSession) -> None:
    """Regression: the projection reproduces the legacy CrossSourceFacts byte-for-byte, so the 5
    live rules see identical inputs (LF-6T3N-style)."""
    loan_file = await _build_full_file(db_session)

    context = await assemble_cross_source_context(db_session, loan_file)
    legacy = await build_cross_source_facts(db_session, loan_file=loan_file, context=context)

    ns = await assemble_fact_namespace(db_session, loan_file)
    projected = project_cross_source_facts(ns)

    assert projected == legacy


async def test_r5fix8_v1_snapshot_loads_without_bank_statements(db_session: AsyncSession) -> None:
    # Round-5 FIX 8: a persisted v1 snapshot (before bank_statements existed) must still load — the field
    # defaults to [] so the schema bump 1→2 is round-trip-safe, not a ValidationError.
    from app.verification.fact_namespace.snapshot import FactNamespace

    loan_file = await _build_full_file(db_session)
    ns = await assemble_fact_namespace(db_session, loan_file)
    v1 = ns.model_dump(mode="json")
    v1.pop("bank_statements")  # simulate the v1 shape
    v1["schema_version"] = 1
    reloaded = FactNamespace.model_validate(v1)  # must not raise
    assert reloaded.bank_statements == []
