"""Documents section assembler (LP-206) — DB-backed (test DB has the real schema).

Covers: single-borrower, joint, no-match belongsTo; soft-deleted document +
soft-deleted borrower exclusion; honest confidence; PII masking (no raw); and
absent≠empty. Seeds an LF-6T3N-like file.
"""

from typing import Any
from uuid import UUID, uuid4

from app.models import (
    Borrower,
    Company,
    Document,
    ExtractionStatus,
    UploadSource,
)
from app.models.base import utcnow
from app.models.document_borrower_link import DocumentBorrowerLink, MatchMethod
from app.services.extractions import create_extraction_version
from app.services.loan_files import create_loan_file
from app.verification.snapshot.documents_section import (
    build_document_fields,
    build_documents_section,
)
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.pii import PiiField
from sqlalchemy.ext.asyncio import AsyncSession


def _field(value: Any, confidence: float | None) -> dict[str, Any]:
    return {"value": value, "source": None, "confidence": confidence}


async def _seed(db: AsyncSession) -> tuple[UUID, dict[str, Borrower], dict[str, Document]]:
    company = Company(name="Acme", slug="acme")
    db.add(company)
    await db.flush()
    lf = await create_loan_file(db, company_id=company.id)
    akash = Borrower(
        loan_file_id=lf.id,
        first_name="Akash",
        last_name="Patel",
        is_primary=True,
        borrower_position=1,
    )
    priya = Borrower(loan_file_id=lf.id, first_name="Priya", last_name="Patel", borrower_position=2)
    db.add_all([akash, priya])
    await db.flush()

    docs: dict[str, Document] = {}

    async def _doc(slug: str, extracted: dict[str, Any] | None) -> Document:
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
        if extracted is not None:
            await create_extraction_version(
                db,
                document_id=d.id,
                extracted_data=extracted,
                extraction_status=ExtractionStatus.SUCCEEDED,
            )
        docs[slug] = d
        return d

    await _doc(
        "pay_stub",
        {
            "employee_name": _field("Akash Patel", 0.98),
            "gross_pay": _field("5700.00", 0.94),
            "rate": _field(None, None),  # absent — omitted
            "pay_frequency": _field("", 0.5),  # present-empty
        },
    )
    await _doc(
        "bank_statement",
        {
            "account_holder_name": _field("Akash Patel and Priya Patel", 0.96),
            "account_number_masked": _field("****3312", 0.99),  # pre-masked PII
        },
    )
    await _doc("appraisal", {"appraised_value": _field("485000.00", 0.96)})

    # W-2 stores the SSN RAW ("as written") + a 1099 stores the TIN RAW — both must be
    # routed through PiiField (masked, raw discarded), never a plaintext Field.
    await _doc(
        "w2",
        {
            "employee_name": _field("Akash Patel", 0.9),
            "employee_ssn": _field("123-45-6789", 0.95),  # RAW SSN
        },
    )
    await _doc(
        "1099",
        {
            "recipient_name": _field("Akash Patel", 0.9),
            "recipient_tin": _field("987-65-4321", 0.9),  # RAW TIN/SSN
        },
    )

    # A soft-deleted document — must be excluded from the section.
    gone = await _doc("voe", {"employee_name": _field("Akash Patel", 0.9)})
    gone.deleted_at = utcnow()

    # Links: pay_stub → Akash; bank_statement → both (joint).
    db.add_all(
        [
            DocumentBorrowerLink(
                document_id=docs["pay_stub"].id,
                borrower_id=akash.id,
                confidence=1.0,
                method=MatchMethod.EXACT,
            ),
            DocumentBorrowerLink(
                document_id=docs["bank_statement"].id,
                borrower_id=akash.id,
                confidence=0.97,
                method=MatchMethod.NORMALIZED,
            ),
            DocumentBorrowerLink(
                document_id=docs["bank_statement"].id,
                borrower_id=priya.id,
                confidence=0.97,
                method=MatchMethod.NORMALIZED,
            ),
        ]
    )
    await db.flush()
    return lf.id, {"akash": akash, "priya": priya}, docs


def _by_type(entries: list, doc_type: str):
    return next(e for e in entries if e.document_type == doc_type)


async def _section(db: AsyncSession):
    lf_id, borrowers, _docs = await _seed(db)
    from app.models.loan_file import LoanFile
    from sqlalchemy import select

    loan_file = (await db.execute(select(LoanFile).where(LoanFile.id == lf_id))).scalar_one()
    return await build_documents_section(db, loan_file), borrowers


async def test_single_borrower_belongs_to_and_asserted_name(db_session: AsyncSession) -> None:
    entries, borrowers = await _section(db_session)
    pay = _by_type(entries, "pay_stub")
    assert pay.belongs_to is not None and len(pay.belongs_to) == 1
    ref = pay.belongs_to[0]
    assert ref.borrower_id == borrowers["akash"].id
    assert ref.name == "Akash Patel"
    # raw asserted name kept in fields, distinct from the resolved ref
    assert pay.fields["asserted_name"].value == "Akash Patel"
    assert pay.fields["employee_name"].value == "Akash Patel"


async def test_joint_document_belongs_to_multiple(db_session: AsyncSession) -> None:
    entries, borrowers = await _section(db_session)
    bank = _by_type(entries, "bank_statement")
    assert bank.belongs_to is not None and len(bank.belongs_to) == 2
    assert {r.borrower_id for r in bank.belongs_to} == {
        borrowers["akash"].id,
        borrowers["priya"].id,
    }
    assert {r.name for r in bank.belongs_to} == {"Akash Patel", "Priya Patel"}


async def test_no_match_document_belongs_to_is_none(db_session: AsyncSession) -> None:
    entries, _ = await _section(db_session)
    appraisal = _by_type(entries, "appraisal")
    assert appraisal.belongs_to is None
    assert appraisal.fields["appraised_value"].value == "485000.00"


async def test_soft_deleted_document_excluded(db_session: AsyncSession) -> None:
    entries, _ = await _section(db_session)
    assert all(e.document_type != "voe" for e in entries)


async def test_link_to_soft_deleted_borrower_excluded(db_session: AsyncSession) -> None:
    lf_id, borrowers, _docs = await _seed(db_session)
    borrowers["priya"].deleted_at = utcnow()  # remove a joint borrower after matching
    await db_session.flush()
    from app.models.loan_file import LoanFile
    from sqlalchemy import select

    loan_file = (
        await db_session.execute(select(LoanFile).where(LoanFile.id == lf_id))
    ).scalar_one()
    entries = await build_documents_section(db_session, loan_file)
    bank = _by_type(entries, "bank_statement")
    # Only Akash remains; Priya's link is dropped (soft-delete-safe read).
    assert bank.belongs_to is not None and len(bank.belongs_to) == 1
    assert bank.belongs_to[0].borrower_id == borrowers["akash"].id


async def test_confidence_surfaced_faithfully_never_fabricated(db_session: AsyncSession) -> None:
    entries, _ = await _section(db_session)
    pay = _by_type(entries, "pay_stub")
    assert pay.fields["gross_pay"].confidence == 0.94
    assert pay.fields["employee_name"].confidence == 0.98
    # every field is source=extracted
    assert all(f.source is FieldSource.EXTRACTED for f in pay.fields.values())


def test_credit_report_free_text_alert_scrubs_embedded_ssn() -> None:
    """LP-445 review: ssn_alert_status is free text (not whole-value PII), but a model could embed a raw
    SSN. The snapshot passes it through the 9+-digit scrub — the alert wording survives, a leaked SSN is
    redacted — so it can't sit unmasked beside the MASKED borrower_ssn."""
    lf = uuid4()
    fields = build_document_fields(
        {
            "ssn_alert_status": _field("SSN 123-45-6789 requires investigation", None),
            "address_usage_alert": _field("USED 006 TIMES IN THE LAST 30 DAYS", None),
        },
        "credit_report",
        loan_file_id=lf,
    )
    # The embedded 9-digit SSN is redacted; the surrounding alert wording is kept.
    assert isinstance(fields["ssn_alert_status"], Field)
    assert "123456789" not in fields["ssn_alert_status"].value
    assert "123-45-6789" not in fields["ssn_alert_status"].value
    assert "[redacted]" in fields["ssn_alert_status"].value
    assert "requires investigation" in fields["ssn_alert_status"].value
    # A clean alert with no digit run is untouched.
    assert fields["address_usage_alert"].value == "USED 006 TIMES IN THE LAST 30 DAYS"


def test_business_tax_ids_are_masked_not_plaintext() -> None:
    """employer_ein (W-2) and payer_tin (1099) are 9-digit tax ids → masked, no raw run.

    Surfaced by the LP-209 at-rest guard on real data: a raw EIN is a bare 9-digit run.
    Masking them upstream keeps the guard strong instead of exempting a tax id.
    """
    lf = uuid4()
    w2 = build_document_fields({"employer_ein": _field("12-3456789", None)}, "w2", loan_file_id=lf)
    ein = w2["employer_ein"]
    assert isinstance(ein, PiiField)
    assert ein.display == "****6789"

    f1099 = build_document_fields(
        {"payer_tin": _field("98-7654321", None)}, "1099", loan_file_id=lf
    )
    tin = f1099["payer_tin"]
    assert isinstance(tin, PiiField)
    assert tin.display == "****4321"

    # Neither the dashed as-written form nor the collapsed digits appear anywhere in the
    # produced fields. Exclude match_hash (a keyed hex digest legitimately contains digit
    # runs), matching test_raw_ssn_and_tin_are_masked's stricter sweep.
    def _no_raw(field: PiiField) -> str:
        dumped = field.model_dump()
        dumped.pop("match_hash", None)
        return repr(dumped)

    for field, raws in ((ein, ("12-3456789", "123456789")), (tin, ("98-7654321", "987654321"))):
        blob = _no_raw(field)
        for raw in raws:
            assert raw not in blob


async def test_pii_account_is_masked_piifield_no_raw(db_session: AsyncSession) -> None:
    entries, _ = await _section(db_session)
    bank = _by_type(entries, "bank_statement")
    acct = bank.fields["account_number_masked"]
    assert isinstance(acct, PiiField)
    assert acct.display == "****3312"
    assert acct.match_hash is None  # only the masked form was ever captured
    assert "3312" in acct.display  # last-4 shown


async def test_raw_ssn_and_tin_are_masked_piifields_never_plaintext(
    db_session: AsyncSession,
) -> None:
    """W-2 employee_ssn / 1099 recipient_tin are stored RAW — must not leak as Field."""
    import re

    entries, _ = await _section(db_session)
    ssn = _by_type(entries, "w2").fields["employee_ssn"]
    assert isinstance(ssn, PiiField)
    assert ssn.display == "***-**-6789"
    assert ssn.match_hash is not None and ssn.match_hash.startswith("v1:")  # raw → matchable
    tin = _by_type(entries, "1099").fields["recipient_tin"]
    assert isinstance(tin, PiiField) and tin.display == "***-**-4321"

    # The raw SSN/TIN appears NOWHERE in the section's displayed/valued content — dashed
    # OR undashed. (Exclude match_hash: a keyed hex hash legitimately contains digit
    # runs and is not a raw value.)
    dumps = []
    for e in entries:
        for v in e.fields.values():
            d = v.model_dump()
            d.pop("match_hash", None)
            dumps.append(d)
    blob = repr(dumps)
    for raw in ("123-45-6789", "123456789", "987-65-4321", "987654321"):
        assert raw not in blob
    assert not re.search(r"\d{3}-\d{2}-\d{4}|\d{9,}", blob)  # no SSN-shaped or long digit run


def test_pii_registry_covers_every_sensitive_extractor_field() -> None:
    """Drift guard: any extractor field annotated ``# SENSITIVE`` must be PII-routed
    here — this is what stops a new raw-SSN/account field from silently leaking as a
    plain Field. ``date_of_birth`` is excluded: it is a date, not a maskable last-4
    number, and is surfaced as an ordinary field (as the MISMO section also does)."""
    import re
    from pathlib import Path

    from app.verification.snapshot.documents_section import _PII_FIELDS

    _EXCLUDED = {"date_of_birth"}  # PII, but a date — no last-4 masking applies
    ext_dir = Path(__file__).resolve().parents[3] / "app" / "ai" / "extraction"
    # Attribute a ``# SENSITIVE`` comment to the nearest preceding ``<name>: TypedField``
    # declaration — NOT the same line only. ruff wraps a long field across lines and puts
    # the comment on the closing ``)``, so a same-line scrape silently misses those fields
    # (the exact way employer_ein/payer_tin slipped the guard). Tracking the current field
    # keeps a multi-line SENSITIVE field detected.
    sensitive: set[str] = set()
    decl_re = re.compile(r"\s*([a-z0-9_]+)\s*:\s*TypedField")
    for path in ext_dir.glob("*.py"):
        current_field: str | None = None
        for line in path.read_text().splitlines():
            decl = decl_re.match(line)
            if decl:
                current_field = decl.group(1)
            if "# SENSITIVE" in line and current_field is not None:
                sensitive.add(current_field)
    assert sensitive, "expected to find # SENSITIVE typed fields in the extractors"
    # Self-check the detector: the multi-line-formatted fields it previously missed MUST
    # now be seen, or the guard is silently blind again.
    assert {"employee_ssn", "employer_ein", "payer_tin"} <= sensitive
    missing = sensitive - set(_PII_FIELDS) - _EXCLUDED
    assert not missing, f"SENSITIVE extractor fields not PII-routed: {sorted(missing)}"


def test_tax_id_and_account_named_fields_are_routed_even_without_the_annotation() -> None:
    """LP-509-C1 — the SECOND axis, because the guard above can only see what was annotated.

    The guard above asks "was it marked SENSITIVE?". A field nobody thought to mark is invisible to
    it, and that is how `state_employer_id` (W-2 Box 15 — a state-issued employer tax id, the same
    kind of value as the `employer_ein` sitting two lines above it in the same extractor) went
    unrouted, along with `lender_tin` and `tax_bill_or_account_number`.

    Left unrouted, the cost is not a leak — the LP-209 at-rest guard catches it — it is that the
    guard REFUSES THE WHOLE SNAPSHOT. One populated W-2 box costs the loan file every persisted tag
    value it has, on every run, permanently. That is the shape of the LP-509 investigation.

    So this asks a question that needs no annotation: does the NAME say it holds a government or
    institutional identifier? Those are 9+ digits by construction and there is no case for one
    sitting raw at rest. Deliberately narrow — `_number`/`_id` in general are far too broad
    (`comp_number`, `permit_number`, `policy_status`) and a broad rule that has to be suppressed
    everywhere teaches people to suppress it.
    """
    import re
    from pathlib import Path

    from app.verification.snapshot.documents_section import _PII_FIELDS

    identifier_named = re.compile(
        r"(_ein$|^ein$|_tin$|^tin$|tax_id|taxpayer_id|_ssn$|^ssn$|routing|employer_id$"
        r"|account_number$)"
    )
    decl_re = re.compile(r"\s*([a-z0-9_]+)\s*:\s*TypedField")
    ext_dir = Path(__file__).resolve().parents[3] / "app" / "ai" / "extraction"

    found: dict[str, str] = {}
    for path in sorted(ext_dir.glob("*.py")):
        for line in path.read_text().splitlines():
            decl = decl_re.match(line)
            if decl and identifier_named.search(decl.group(1)):
                found.setdefault(decl.group(1), path.name)

    # Self-check the detector, so a broken regex cannot make this pass by finding nothing.
    assert {"employer_ein", "payer_tin", "state_employer_id"} <= set(found)

    unrouted = {name: path for name, path in found.items() if name not in _PII_FIELDS}
    assert not unrouted, (
        "extractor fields whose NAME says they carry a government/institutional identifier, "
        f"but which are not PII-routed: {sorted(unrouted.items())}. Add each to _PII_FIELDS "
        "(PiiKind.ACCOUNT, pre_masked=False) — an unmasked 9+ digit id refuses the entire "
        "snapshot persist for every file carrying that document."
    )


async def test_absent_field_omitted_present_empty_kept(db_session: AsyncSession) -> None:
    entries, _ = await _section(db_session)
    pay = _by_type(entries, "pay_stub")
    assert "rate" not in pay.fields  # value was null → absent
    assert pay.fields["pay_frequency"] == Field.present(
        "", source=FieldSource.EXTRACTED, confidence=0.5
    )
    assert pay.fields["pay_frequency"].value == ""  # present-empty
