"""Snapshot persistence (LP-209) — immutable per-run round-trip through the DB.

Covers: lossless persist→load (PII masked, confidence-null, source tags, absent≠empty
preserved through JSONB), write-once immutability (dup run_id raises, original row
unchanged), append-only history (two runs → two rows, both loadable), and the
PII-clean-at-rest write guard (raw PII rejected, not stored).
"""

import json
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


def test_guard_names_the_offending_path_without_printing_the_value() -> None:
    """LP-509-C1 — the refusal must say WHERE, and must not become a PII leak of its own.

    LF-WCHG had zero persisted snapshots: every run was refused with "a long bare digit run
    (unmasked account/SSN) is present" and nothing else. That sentence is true and unactionable —
    it names no field, no document, no path — so the field responsible could not be identified, and
    with no snapshot there were no persisted tag values to inspect either. The refusal is correct;
    being undiagnosable is the defect.
    """
    from app.verification.snapshot.persistence import _assert_no_raw_pii

    payload = '{"documents": [{"fields": {"policy_number": {"value": "987654321"}}}]}'
    with pytest.raises(RawPiiAtRestError) as excinfo:
        _assert_no_raw_pii(payload)

    message = str(excinfo.value)
    assert "documents[0].fields.policy_number.value" in message
    assert "9-digit run" in message
    # The guard must never log the thing it exists to keep out of the logs.
    assert "987654321" not in message


def test_guard_reports_every_offending_path_not_just_the_first() -> None:
    """One fix per re-run is a slow way to clear a file that has several unmasked fields."""
    from app.verification.snapshot.persistence import _assert_no_raw_pii

    with pytest.raises(RawPiiAtRestError) as excinfo:
        _assert_no_raw_pii('{"a": {"acct": "123456789"}, "b": {"ssn": "123-45-6789"}}')
    message = str(excinfo.value)
    assert "a.acct" in message and "b.ssn" in message


def test_a_uuid_whose_last_group_is_all_digits_does_not_refuse_the_snapshot() -> None:
    """LP-509-C1 — the defect that made ~1-2% of loan files permanently unpersistable.

    A uuid4's final group is TWELVE hex characters bounded by a hyphen and a quote. About 1 uuid in
    281 draws twelve decimal digits there, which is exactly the shape of an unmasked account number,
    and the guard refused the write. `run_id` only cost that run — but `loan_file_id` and the
    borrower ids are STABLE, so a loan file that drew such a uuid could never persist a snapshot on
    any run, ever, losing every tag value and observation with it.

    It was a real flake in this very file: the suite failed intermittently on a DIFFERENT test each
    time, and the path-naming added in this ticket is what identified it — the message pointed
    straight at `loan_file_id` and `run_id`.
    """
    from app.verification.snapshot.persistence import _assert_no_raw_pii

    # The exact shape that was failing. Not synthetic — this is a valid uuid4 layout.
    _assert_no_raw_pii('{"loan_file_id": "3f2504e0-4f89-41d3-9a0c-030405060708"}')
    _assert_no_raw_pii('{"run_id": "3f2504e0-4f89-41d3-9a0c-123456789012"}')
    # ...and matching by SHAPE means it covers a uuid under any key, not a list of blessed names.
    _assert_no_raw_pii('{"documents": [{"belongs_to": ["3f2504e0-4f89-41d3-9a0c-987654321098"]}]}')

    # A bare digit run of the same length, NOT in uuid shape, is still refused.
    with pytest.raises(RawPiiAtRestError):
        _assert_no_raw_pii('{"loan_file_id": "123456789012"}')
    # A uuid is not a hiding place: a dashed SSN embedded in a uuid-length string still fails.
    with pytest.raises(RawPiiAtRestError):
        _assert_no_raw_pii('{"note": "3f2504e0-4f89-41d3-9a0c-030405060708 ssn 123-45-6789"}')


#: A uuid4 whose last group is twelve decimal digits — CONSTRUCTED, not searched for.
#:
#: Searching ("generate uuids until one has a 9+ digit run") is the shape the LP-705 ticket
#: reached for first, and the loop is lumpier than it looks: median 202 iterations, p95 852,
#: p99 1,402, and 2,291 observed in 2,000 trials. Unbounded it will occasionally read as a
#: hang; bounded at a comfortable-sounding 500 it fails spuriously about one run in twenty —
#: worse than the bug, because a flaky test gets deleted rather than read. This is a valid
#: RFC 4122 version-4 uuid and it says what it is testing.
_UUID_WITH_A_DIGIT_RUN = "12345678-9012-4345-8678-901234567890"


def test_a_uuid_INSIDE_a_key_does_not_refuse_the_snapshot() -> None:
    """LP-705 — one stated liability in 283 permanently refused its loan file's snapshot.

    LP-509-C1 skipped a value that IS a uuid. It anchored the match, so a value that CONTAINS
    one was still scanned — and a DTI line key is ``f"debt.{liab.id}"``, a prefix plus a uuid.
    The uuid's own twelve-character tail was then read as an unmasked account number and the
    whole write was refused: no snapshot, no tag values, no findings, on every subsequent run
    until that row was edited.

    Measured over 2,000,000 samples, 0.354% of uuid4s carry a 9+ digit run (95% CI
    0.3457-0.3622%), so about one stated liability in 283. Nothing about the file predicts it —
    the trigger is which uuid a row happened to draw, which is why LP-565/bug-001 recorded
    "22 completed runs, 0 persisted" with no pattern anyone could see.
    """
    from app.verification.snapshot.persistence import _assert_no_raw_pii

    # The two real shapes, from services/dti.py.
    for key in (f"debt.{_UUID_WITH_A_DIGIT_RUN}", f"income.{_UUID_WITH_A_DIGIT_RUN}"):
        _assert_no_raw_pii(json.dumps({"calculations": {"dti": {"breakdown": [{"key": key}]}}}))
    # And a uuid anywhere inside a longer string, since the fix is by shape not by prefix.
    _assert_no_raw_pii(json.dumps({"note": f"line for {_UUID_WITH_A_DIGIT_RUN}, stated"}))


def test_the_constructed_uuid_really_is_the_case_under_test() -> None:
    """The positive control for the constant above.

    Without this, ``_UUID_WITH_A_DIGIT_RUN`` could be edited into a uuid with no digit run and
    every assertion above would go on passing while testing nothing — the exact way a guard goes
    green by construction. Asserted from both sides: it is a real version-4 uuid, and its digits
    are what the guard would otherwise refuse.
    """
    import uuid as uuid_module

    from app.verification.snapshot.persistence import _LONG_DIGITS, _assert_no_raw_pii

    parsed = uuid_module.UUID(_UUID_WITH_A_DIGIT_RUN)
    assert parsed.version == 4
    assert _LONG_DIGITS.search(_UUID_WITH_A_DIGIT_RUN) is not None

    # The same digits, NOT in uuid shape, are still refused — so the test above passes
    # because of the fix and not because the value was harmless all along.
    with pytest.raises(RawPiiAtRestError):
        _assert_no_raw_pii(json.dumps({"asset.account": "901234567890"}))


def test_removing_a_uuid_is_not_a_hiding_place() -> None:
    """The safety argument for matching a uuid ANYWHERE, asserted rather than reasoned.

    Widening a skip is the kind of change that can quietly turn a guard off, so each way it
    could is checked. Removal deletes exactly 36 characters of canonical uuid, and neither an
    SSN (hyphens at 3 and 6) nor a bare account number (no hyphens) can be contained by that
    shape.

    THE REPLACEMENT IS A SPACE, and the case that needs it is narrower than it first looks. A
    leak at the START of a value survives either way — the string edge is already a word
    boundary — so a test using ``"<uuid>123456789"`` passes with the uuid replaced by nothing
    at all, and an earlier draft of this test proved only that. The case that separates them is
    a WORD CHARACTER immediately before the uuid: with an empty replacement ``"debt"`` joins the
    digits, ``\b`` never opens, and the leak walks straight through.
    """
    from app.verification.snapshot.persistence import _assert_no_raw_pii

    # THIS WAS the distinguishing case for `sub(" ")` versus `sub("")`, and it no
    # longer distinguishes — worth saying rather than leaving a comment that has
    # quietly stopped being true. Requiring the uuid to be DELIMITED (LP-705
    # review) means digits can never sit against one that is removed: both
    # lookarounds reject an alphanumeric neighbour, so `debt<uuid>123456789` is not
    # a uuid match at all and the run survives whatever the replacement is.
    #
    # The space is kept as defence in depth — if the delimiters are ever loosened
    # it starts mattering again — but the delimiters are what carries this now, and
    # `TestAUuidMustBeDelimitedToBeSkipped` is where that is actually tested.
    with pytest.raises(RawPiiAtRestError):
        _assert_no_raw_pii(json.dumps({"note": f"debt{_UUID_WITH_A_DIGIT_RUN}123456789"}))
    # A leak written flush against a uuid at either end.
    with pytest.raises(RawPiiAtRestError):
        _assert_no_raw_pii(json.dumps({"note": f"{_UUID_WITH_A_DIGIT_RUN}123456789"}))
    with pytest.raises(RawPiiAtRestError):
        _assert_no_raw_pii(json.dumps({"note": f"123456789{_UUID_WITH_A_DIGIT_RUN}"}))
    # A dashed SSN beside a uuid.
    with pytest.raises(RawPiiAtRestError):
        _assert_no_raw_pii(json.dumps({"note": f"debt.{_UUID_WITH_A_DIGIT_RUN} ssn 123-45-6789"}))
    # A near-uuid that is NOT canonical (wrong group lengths) buys nothing.
    with pytest.raises(RawPiiAtRestError):
        _assert_no_raw_pii(json.dumps({"note": "1234567-8901-2345-8678-901234567890"}))


def test_the_door_and_the_end_of_the_run_agree() -> None:
    """``refuses_at_rest`` and the persist guard are ONE decision, not two copies of it.

    They were two, and they disagreed: the guard skipped uuids and the door did not, so a value
    the reviewer would have refused was one the snapshot accepted. The direction happens to be
    the harmless one — but a rule stated twice is a rule that will differ the other way
    eventually, and LP-703's whole reason for exporting this was that the two must not.
    """
    from app.verification.snapshot.persistence import _assert_no_raw_pii, refuses_at_rest

    for value in (
        f"debt.{_UUID_WITH_A_DIGIT_RUN}",
        _UUID_WITH_A_DIGIT_RUN,
        "123456789.00",
        "docABC0000000000",
    ):
        assert refuses_at_rest(value) is None, value
        _assert_no_raw_pii(json.dumps({"v": value}))

    for value in ("123456789", "123-45-6789", "901234567890"):
        assert refuses_at_rest(value) is not None, value
        with pytest.raises(RawPiiAtRestError):
            _assert_no_raw_pii(json.dumps({"v": value}))


def test_guard_exempts_no_other_key_because_the_derived_ids_do_not_need_it() -> None:
    """LP-509-C1 — why the structural walk added no allowlist.

    A key-aware scan invites a "these keys are ours, skip them" exemption for `content_id` and
    `match_hash`. It is not needed and was not added: a content id is LETTER-prefixed (`doc…` /
    `txn…`) and a match hash is `v1:<hex>`, so in both the digit run is preceded by a word
    character and `\\b` never opens one. `test_content_ids_never_trip_the_pii_guard` pins the
    prefix that makes this true.

    Asserted from the other side here — a bare all-digit value under those very key names IS still
    refused — so that if the prefix ever goes away, the failure is a loud refusal rather than a
    value quietly waved through by an exemption nobody re-derived.
    """
    from app.verification.snapshot.persistence import _assert_no_raw_pii

    _assert_no_raw_pii('{"documents": [{"content_id": "docABC0000000000"}]}')
    _assert_no_raw_pii('{"match_hash": "v1:abc123456789def"}')

    with pytest.raises(RawPiiAtRestError):
        _assert_no_raw_pii('{"documents": [{"content_id": "1234567890123456"}]}')


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


class TestAUuidMustBeDelimitedToBeSkipped:
    """The skip may only exempt a uuid that STANDS ALONE.

    The argument for removing uuids was that neither leak pattern can be CONTAINED
    by an 8-4-4-4-12 run. That is true and it is not sufficient: a leak does not
    need to be contained, only to OVERLAP. The final group is exactly twelve hex,
    so an undelimited match eats the first twelve digits of a longer run and leaves
    a remainder too short to report.

    Every one of these values was REFUSED before the uuid skip existed. A skip that
    makes the guard accept them is a regression in a PII-at-rest check, which is
    the one direction this file must never move in.
    """

    @staticmethod
    def _refuses(value: str) -> str | None:
        from app.verification.snapshot.persistence import refuses_at_rest

        return refuses_at_rest(value)

    @pytest.mark.parametrize(
        ("value", "digits"),
        [
            # 8-4-4-4 of hex, then a card number: the first twelve digits complete a
            # uuid-shaped match and "1111" is left behind.
            ("aaaaaaaa-aaaa-aaaa-aaaa-4111111111111111", 16),
            ("aaaaaaaa-aaaa-aaaa-aaaa-12345678901234567890", 20),
            # And the mirror: digits leading into uuid-shaped hex.
            ("41111111111111119012-4345-8678-9012-345678901234", 20),
        ],
    )
    def test_a_leak_touching_uuid_shaped_hex_is_still_refused(
        self, value: str, digits: int
    ) -> None:
        assert self._refuses(value) is not None, (
            f"a {digits}-digit run was refused before the uuid skip and is accepted now"
        )

    @pytest.mark.parametrize(
        "value",
        [
            f"debt.{_UUID_WITH_A_DIGIT_RUN}",
            f"income.{_UUID_WITH_A_DIGIT_RUN}",
            str(_UUID_WITH_A_DIGIT_RUN),
            f"run {_UUID_WITH_A_DIGIT_RUN} completed",
        ],
    )
    def test_a_delimited_uuid_is_still_skipped(self, value: str) -> None:
        # The control. Tightening the skip must not undo what LP-705 fixed — these
        # are the shapes that were costing a loan file its whole snapshot.
        assert self._refuses(value) is None
