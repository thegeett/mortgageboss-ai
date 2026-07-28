"""LP-338 — the representative LF-6T3N snapshot, built IN CODE (no committed snapshot JSON).

LP-337's coverage bug was diagnosed against a STRIPPED fixture (5 bank statements, empty fields). The
honest measurement needs the real LF-6T3N shape (~30 documents, populated fields). Rather than commit a
large synthetic snapshot JSON, this builder constructs it deterministically at call time:

* it reuses the already-committed ``lf6t3n_tagged_snapshot.json`` for the 5 bank statements + their 50
  transactions VERBATIM (so txn.* subject-ids / any human labels stay stable), populating their fields, and
* appends 25 synthetic, DE-IDENTIFIED documents (driver's licences, pay-stubs, W-2s, investment accounts,
  a brokerage statement, mortgage statements, property-tax bills, a purchase agreement, unknowns).

Deterministic + keyless (no clock, no randomness, no API). The brokerage_statement + the 4 unknown docs are
left ``fields = {}`` on purpose — the content-empty case (a subject that exists but cannot be labeled).
"""

from __future__ import annotations

from uuid import UUID

from app.verification.eval.harness import load_fixture_snapshot
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    SnapshotField,
)

_BASE_FIXTURE = "lf6t3n_tagged_snapshot.json"

# --------------------------------------------------------------------------- #
# LP-379-B — the 2 wired borrowers, mirroring the DB LF-6T3N's STRUCTURE (2 borrowers, one primary + one
# co-borrower, each owning their income documents). The DB's real borrowers are Akash (primary, index 1) and
# Bansari (co, index 2) Patel; the FIXTURE stays de-identified — it mirrors the SHAPE (ids + attribution +
# a 2-year non-declining W-2 history), never the DB's PII. borrower_ids are fixed synthetic UUIDs.
_B1_ID = UUID(
    "11111111-1111-4111-8111-111111111111"
)  # Jordan A Rivera (primary — mirrors DB index 1)
_B2_ID = UUID("22222222-2222-4222-8222-222222222222")  # Taylor M Nguyen (co — mirrors DB index 2)
_B1_NAME = "Jordan A Rivera"
_B2_NAME = "Taylor M Nguyen"
_B1_REF = BorrowerRef(borrower_id=_B1_ID, name=_B1_NAME)
_B2_REF = BorrowerRef(borrower_id=_B2_ID, name=_B2_NAME)


def _f(value: str) -> Field:
    return Field.present(value, source=FieldSource.EXTRACTED)


def _doc(cid: str, dtype: str, **fields: str) -> DocumentEntry:
    return DocumentEntry(
        content_id=cid,
        document_type=dtype,
        belongs_to=None,
        fields={k: _f(v) for k, v in fields.items()},
    )


# The borrower identity facts (built after _f is defined). borrower.1 = primary, borrower.2 = co-borrower,
# mirroring the DB. employer.{n}.name traces to each borrower's OWN W-2s in this fixture.
_BORROWER_MISMO: dict[str, SnapshotField] = {
    "borrower.1.borrower_id": _f(str(_B1_ID)),
    "borrower.1.first_name": _f("Jordan"),
    "borrower.1.last_name": _f("Rivera"),
    "borrower.1.is_primary": _f("true"),
    "borrower.1.employer.1.name": _f("Acme Logistics Inc"),
    "borrower.1.employer.2.name": _f("Northgate Warehousing"),
    "borrower.2.borrower_id": _f(str(_B2_ID)),
    "borrower.2.first_name": _f("Taylor"),
    "borrower.2.last_name": _f("Nguyen"),
    "borrower.2.is_primary": _f("false"),
    "borrower.2.employer.1.name": _f("Sterling Retail LLC"),
    "borrower.2.employer.2.name": _f("Cafe Bluebird"),
    # LP-414: the subject property's stated 1003/MISMO purchase price (was ABSENT — the LP-407-2 gap), so
    # property.purchase_price READS it. It matches the purchase agreement's sales_price (365000), so a future
    # PC-2 SATISFIES on this clean anchor. NOT an occupancy signal — the occupancy AI group reasons only over
    # property.occupancy + the declarations (none present here), so OC-2 stays couldnt_check (LP-414 A2).
    "property.purchase_price": _f("365000.00"),
}

# Attribution by the RESOLVED holder name (LP-202: belongs_to is the evidence-based link). A document is
# attributed to the borrower whose name its own identity field carries; joint/property documents (mortgage,
# property-tax, purchase agreement, the empty brokerage, unknowns) resolve to no single borrower → None.
_NAME_FIELD_BY_TYPE = {
    "drivers_license": "full_name",
    "pay_stub": "employee_name",
    "w2": "employee_name",
    "investment_account": "account_holder",
    "bank_statement": "account_holder_name",
}
_REF_BY_NAME = {_B1_NAME: _B1_REF, _B2_NAME: _B2_REF}


def _attribution(entry: DocumentEntry) -> tuple[BorrowerRef, ...] | None:
    name_field = _NAME_FIELD_BY_TYPE.get(entry.document_type or "")
    if name_field is None:
        return None
    field = entry.fields.get(name_field)
    holder = str(field.value) if isinstance(field, Field) and field.is_present else None
    ref = _REF_BY_NAME.get(holder or "")
    return (ref,) if ref is not None else None


# LP-379-C — the REAL DB original_filename for each LF-6T3N document (exactly what the Document tab shows),
# keyed by the fixture's content_id, so the calibration worksheet names the actual document a labeler opens.
# Read from the DB LF-6T3N (mirrors it). The 5 bank statements share content_ids with the DB (they come from
# the committed tagged snapshot); the synthetic documents map by borrower + document type + order. NOTE: the
# field VALUES stay de-identified (Jordan/Taylor/Acme) while the FILENAMES are the real ones (Akash/BofA) — a
# deliberate choice (a labeler locates the document by the tab's real name; the row's context is a stand-in).
LF6T3N_DOCUMENT_FILENAMES: dict[str, str] = {
    # bank statements — content_ids match the DB (the transaction parents; the acute "which statement?" case)
    "doce9fa604faeb2faaa": "BofA checking April.pdf",
    "doc78c0460250e6cefb": "BofA checking_May.pdf",
    "docd8f0515f0f1ef311": "BofA savings April.pdf",
    "docb6645cb3380bb3e5": "BofA savings May.pdf",
    "doc30312688b1d919b3": "EMD Withdrawal.pdf",
    # drivers licenses (primary = Akash, co = Bansari)
    "dl1": "DL Akash Patel.pdf",
    "dl2": "DL Bansari.pdf",
    # pay stubs
    "ps1": "Akash Pay stub 1.pdf",
    "ps2": "Akash pay stub 2.pdf",
    "ps3": "Bansari Stub May 1 (1).pdf",
    "ps4": "PAY Bansari Stub May 2 (1).pdf",
    # W-2s (w1/w3 = 2025, w2/w4 = 2024 per the LP-379-B tax-year wiring)
    "w1": "Akash W2 BofA 2025.pdf",
    "w2": "Akash W2 BofA 2024.pdf",
    "w3": "W2 2025 Bansari.pdf",
    "w4": "Bansari W2 2024.pdf",
    # investment accounts (the DB's Wells brokerage/savings statements)
    "inv1": "Wells Brokerage April.pdf",
    "inv2": "Wells Brokerage May.pdf",
    "inv3": "Wells Savings April.pdf",
}


# De-identified field metadata for the 5 preserved bank statements (holder + account + period + balances).
_BANK_META = [
    (
        "First Springfield Bank",
        "checking",
        "****5678",
        "2026-03-01",
        "2026-03-31",
        "8412.55",
        "11233.78",
    ),
    (
        "First Springfield Bank",
        "checking",
        "****5678",
        "2026-04-01",
        "2026-04-30",
        "11233.78",
        "9880.12",
    ),
    (
        "Prairie State Credit Union",
        "savings",
        "****2210",
        "2026-03-01",
        "2026-03-31",
        "40200.00",
        "45200.00",
    ),
    (
        "Prairie State Credit Union",
        "savings",
        "****2210",
        "2026-04-01",
        "2026-04-30",
        "45200.00",
        "45320.44",
    ),
    (
        "First Springfield Bank",
        "checking",
        "****5678",
        "2026-05-01",
        "2026-05-31",
        "9880.12",
        "10544.90",
    ),
]


def build_lf6t3n_snapshot() -> Snapshot:
    """The representative 30-document LF-6T3N snapshot (deterministic; no key)."""
    base = load_fixture_snapshot(_BASE_FIXTURE)
    bank = list(base.documents.entries)
    if not (len(bank) == 5 and all(e.document_type == "bank_statement" for e in bank)):
        raise AssertionError("base LF-6T3N fixture changed shape (expected 5 bank statements)")

    # 1) the 5 bank statements, verbatim transactions, now with populated fields
    entries: list[DocumentEntry] = []
    for entry, (bank_name, acct_type, masked, ps, pe, beg, end) in zip(
        bank, _BANK_META, strict=True
    ):
        entries.append(
            entry.model_copy(
                update={
                    "fields": {
                        "account_holder_name": _f("Jordan A Rivera"),
                        "bank_name": _f(bank_name),
                        "account_number_masked": _f(masked),
                        "account_type": _f(acct_type),
                        "statement_period_start": _f(ps),
                        "statement_period_end": _f(pe),
                        "beginning_balance": _f(beg),
                        "ending_balance": _f(end),
                    }
                }
            )
        )

    # 2) drivers_license x2 — ID-1/3/4/5 LIVE; the REAL-DL check of LP-335's current_address_type fix
    entries += [
        _doc(
            "dl1",
            "drivers_license",
            full_name="Jordan A Rivera",
            date_of_birth="1985-06-12",
            address="123 Maple Ave, Springfield IL 62704",
            id_number_masked="****4821",
            issuing_state="IL",
            issuing_authority="Illinois Secretary of State",
            expiration_date="2029-06-12",
            asserted_name="Jordan A Rivera",
        ),
        _doc(
            "dl2",
            "drivers_license",
            full_name="Taylor M Nguyen",
            date_of_birth="1990-02-28",
            address="456 Oak Street, Springfield IL 62704",
            id_number_masked="****7702",
            issuing_state="IL",
            issuing_authority="Illinois Secretary of State",
            expiration_date="2028-02-28",
            asserted_name="Taylor Marie Nguyen",
        ),
    ]

    # 3) pay_stub x4 — IN-1/2/3/5
    for i, (emp, name, ps, pe, pd, gross, net, ytd, freq) in enumerate(
        [
            (
                "Acme Logistics Inc",
                "Jordan A Rivera",
                "2026-04-16",
                "2026-04-30",
                "2026-05-05",
                "3250.00",
                "2480.11",
                "29250.00",
                "semimonthly",
            ),
            (
                "Acme Logistics Inc",
                "Jordan A Rivera",
                "2026-05-01",
                "2026-05-15",
                "2026-05-20",
                "3250.00",
                "2480.11",
                "32500.00",
                "semimonthly",
            ),
            (
                "Sterling Retail LLC",
                "Taylor M Nguyen",
                "2026-04-19",
                "2026-05-02",
                "2026-05-08",
                "2100.00",
                "1712.44",
                "18900.00",
                "biweekly",
            ),
            (
                "Sterling Retail LLC",
                "Taylor M Nguyen",
                "2026-05-03",
                "2026-05-16",
                "2026-05-22",
                "2100.00",
                "1712.44",
                "21000.00",
                "biweekly",
            ),
        ],
        start=1,
    ):
        entries.append(
            _doc(
                f"ps{i}",
                "pay_stub",
                employer_name=emp,
                employee_name=name,
                pay_period_start=ps,
                pay_period_end=pe,
                pay_date=pd,
                gross_pay=gross,
                net_pay=net,
                ytd_gross=ytd,
                pay_frequency=freq,
                hours="80",
                rate_of_pay="40.625",
            )
        )

    # 4) w2 x4 — IN-1/5, and (LP-379-B) income_stability's per-borrower history. Each borrower has TWO W-2s;
    # the tax_year is assigned so the LOWER-wage W-2 falls in 2024 and the higher in 2025 — a 2-year,
    # NON-DECLINING history mirroring the DB (both DB borrowers rose/held). tax_year is the ONLY field changed
    # here (no golden reads it); employer_name + wages are untouched, so the employer_normalized /
    # documented_monthly goldens stay valid. Jordan: Northgate 12,200 (2024) -> Acme 76,500 (2025); Taylor:
    # Cafe Bluebird 8,300 (2024) -> Sterling 50,400 (2025). Residual vs DB: the DB's co-borrower (Bansari)
    # held ONE employer across both years; the fixture's Taylor changes employer — mirroring that would rewrite
    # w4's employer_name and break its filled golden, so it is left and reported (see docs/tickets/LP-379-B.md).
    for i, (name, ssn, emp, ein, wages, fed, tax_year) in enumerate(
        [
            (
                "Jordan A Rivera",
                "***-**-4821",
                "Acme Logistics Inc",
                "**-***1234",
                "76500.00",
                "9120.00",
                "2025",
            ),
            (
                "Jordan A Rivera",
                "***-**-4821",
                "Northgate Warehousing",
                "**-***5566",
                "12200.00",
                "1300.00",
                "2024",
            ),
            (
                "Taylor M Nguyen",
                "***-**-7702",
                "Sterling Retail LLC",
                "**-***7788",
                "50400.00",
                "5210.00",
                "2025",
            ),
            (
                "Taylor M Nguyen",
                "***-**-7702",
                "Cafe Bluebird",
                "**-***9900",
                "8300.00",
                "610.00",
                "2024",
            ),
        ],
        start=1,
    ):
        entries.append(
            _doc(
                f"w{i}",
                "w2",
                tax_year=tax_year,
                employee_name=name,
                employee_ssn=ssn,
                employer_name=emp,
                employer_ein=ein,
                wages_tips_other_comp=wages,
                federal_income_tax_withheld=fed,
                social_security_wages=wages,
                medicare_wages=wages,
                state="IL",
                state_wages=wages,
                state_income_tax="3200.00",
            )
        )

    # 5) investment_account x3 — AS-4/6/11
    for i, (inst, holder, masked, atype, total) in enumerate(
        [
            ("Vanguard", "Jordan A Rivera", "****3391", "brokerage", "88250.00"),
            ("Fidelity", "Jordan A Rivera", "****1180", "roth_ira", "41500.00"),
            (
                "Prairie State Credit Union",
                "Taylor M Nguyen",
                "****2210",
                "money_market",
                "22000.00",
            ),
        ],
        start=1,
    ):
        entries.append(
            _doc(
                f"inv{i}",
                "investment_account",
                institution_name=inst,
                account_holder=holder,
                account_number_masked=masked,
                account_type=atype,
                statement_period_start="2026-04-01",
                statement_period_end="2026-04-30",
                total_value=total,
                vested_balance=total,
            )
        )

    # 6) brokerage_statement x1 — GENUINELY EMPTY (the content-empty case)
    entries.append(_doc("brk1", "brokerage_statement"))

    # 7) mortgage_statement x4
    for i, (serv, masked, bal, pmt) in enumerate(
        [
            ("Rushmore Servicing", "****8801", "212440.10", "1685.22"),
            ("Rushmore Servicing", "****8801", "211980.55", "1685.22"),
            ("Lakeview Loan", "****2245", "154210.00", "1204.90"),
            ("Lakeview Loan", "****2245", "153870.31", "1204.90"),
        ],
        start=1,
    ):
        entries.append(
            _doc(
                f"mort{i}",
                "mortgage_statement",
                servicer_name=serv,
                loan_number_masked=masked,
                statement_date="2026-05-01",
                principal_balance=bal,
                escrow_balance="2210.00",
                monthly_payment=pmt,
                next_due_date="2026-06-01",
            )
        )

    # 8) property_tax_bill x2. LP-414: the field names now match the property_tax_bill EXTRACTOR
    # (annual_tax_amount / due_dates), not the placeholders (amount_due / due_date) LP-407-2 found — so
    # housing.taxes_monthly READS the figure instead of seeing an absent field. (Two bills for two DIFFERENT
    # properties — the borrowers' residences, not the subject 789 Birchwood — so the recipe still ABSTAINS on
    # the conflict; the VALUE stays "unknown", now for the honest reason. A single-bill scenario materializes
    # a real figure — see fire_path_scenarios.build_subject_tax_snapshot.)
    for i, (parcel, addr, amt) in enumerate(
        [
            ("14-22-301-004", "123 Maple Ave, Springfield IL 62704", "4820.00"),
            ("14-22-301-118", "456 Oak Street, Springfield IL 62704", "3910.00"),
        ],
        start=1,
    ):
        entries.append(
            _doc(
                f"ptax{i}",
                "property_tax_bill",
                parcel_number=parcel,
                property_address=addr,
                tax_year="2025",
                assessed_value="240000.00",
                annual_tax_amount=amt,
                due_dates="2026-08-01",
            )
        )

    # 9) purchase_agreement x1. LP-414: sales_price (the purchase_agreement EXTRACTOR's field), not the
    # placeholder purchase_price LP-407-2 found — so contract.sales_price READS it. closing_date is UNCHANGED
    # (PC-7's contract.days_until_closing == "1" is the realism anchor that must not move).
    entries.append(
        _doc(
            "pa1",
            "purchase_agreement",
            property_address="789 Birchwood Ln, Springfield IL 62711",
            sales_price="365000.00",
            earnest_money_amount="7300.00",
            closing_date="2026-07-15",
            buyer_name="Jordan A Rivera",
            seller_name="Morgan Fields",
        )
    )

    # 10) unknown x4 — unclassified, fields empty (content-empty)
    for i in range(1, 5):
        entries.append(_doc(f"unk{i}", "unknown"))

    # LP-379-B: attribute each person-owned document to its borrower (belongs_to, by resolved holder name),
    # and wire the 2 MISMO borrowers — so the per-borrower producer (LP-385) enumerates them and
    # income_stability materializes. Additive: joint/property documents stay unattributed; no field changed.
    attributed = [entry.model_copy(update={"belongs_to": _attribution(entry)}) for entry in entries]
    return base.model_copy(
        update={
            "mismo": MismoSection.present(_BORROWER_MISMO),
            "documents": DocumentsSection.present(attributed),
        }
    )


def build_lf6t3n_plus() -> Snapshot:
    """LP-384 — LF-6T3N EXTENDED: the base snapshot PLUS the documents its stuck deterministic rules need,
    each carrying a KNOWN, assertable answer. ``build_lf6t3n_snapshot`` stays FROZEN for its many existing
    consumers (worksheet / eval traces); this SIBLING adds only:

      * TWO VOEs with a DELIBERATE 77-day employment gap (a prior job ending 2024-06-30, the current job
        starting 2024-09-15) → IN-4 FIRES (the gap exceeds the 30-day window). The known typo, so the rule's
        CATCH is provable.
      * ONE bank statement that PRINTS "Page 1 of 5" but has only 4 pages present → AS-9 FIRES (a page is
        missing). It joins an EXISTING account + month (First Springfield ``****5678``, May 2026), so AS-10's
        per-account month counts — and its SATISFIED verdict — are UNCHANGED (this document exercises AS-9
        only, never AS-10).

    AS-10 already resolves on the BASE fixture (its statements carry account identity + period dates —
    LP-381's "input absent" went stale as the fixture grew). AS-3 (no §3B cash-to-close calculator) and IN-3
    (needs the AI ``income.documented_monthly``) stay blocked — see docs/tickets/LP-384.md. Additive: every
    tag the base materializes is identical here; the extension only appends documents."""
    base = build_lf6t3n_snapshot()
    extra: list[DocumentEntry] = [
        # IN-4 — the deliberate 77-day gap (prior job end → current job start).
        DocumentEntry(
            content_id="voe_prior",
            document_type="voe",
            belongs_to=(_B1_REF,),
            fields={
                "employer_name": _f("Northgate Warehousing"),
                "start_date": _f("2022-01-10"),
                "end_date": _f("2024-06-30"),
            },
        ),
        DocumentEntry(
            content_id="voe_current",
            document_type="voe",
            belongs_to=(_B1_REF,),
            fields={
                "employer_name": _f("Acme Logistics Inc"),
                "start_date": _f("2024-09-15"),
            },
        ),
        # AS-9 — declares 5 pages, only 4 present. SAME account + month as an existing First Springfield
        # statement, so AS-10's month counts (and its SATISFIED verdict) are unchanged.
        _doc(
            "stmt_missing_page",
            "bank_statement",
            account_holder_name="Jordan A Rivera",
            bank_name="First Springfield Bank",
            account_number_masked="****5678",
            account_type="checking",
            statement_period_start="2026-05-01",
            statement_period_end="2026-05-31",
            beginning_balance="10544.90",
            ending_balance="10980.00",
            page_count_declared="5",
            page_count_present="4",
        ),
    ]
    docs = list(base.documents.entries) + extra
    return base.model_copy(update={"documents": DocumentsSection.present(docs)})


__all__ = ["LF6T3N_DOCUMENT_FILENAMES", "build_lf6t3n_plus", "build_lf6t3n_snapshot"]
