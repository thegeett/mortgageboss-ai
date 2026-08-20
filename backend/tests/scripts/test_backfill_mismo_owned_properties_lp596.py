"""LP-596 — the real-estate-owned backfill.

The parser now reads `OWNED_PROPERTY` and the snapshot projects it, but import is ONE-SHOT: every file
imported before that change has no `stated_owned_properties` rows, and re-running verification never
re-parses the XML. So AS-4 / DT-6 / DT-8 would go on answering from a checkbox on exactly the files
that already exist — including the one real staging file, whose export carries five of these.

The properties asserted here are the ones that make it safe to run against production data: it writes
nothing without an explicit flag, it never touches a file that already has rows, and one unreadable
file does not stop the batch.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from app.models.company import Company
from app.models.loan_file import LoanFile
from app.models.mismo_import import MismoImport, MismoImportStatus
from app.models.stated_financials import StatedOwnedProperty
from app.scripts.backfill_mismo_owned_properties import _backfill
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# Two owned properties inside an otherwise minimal MISMO 3.4 deal: one retained investment property
# carrying a lien, one the borrower is selling. The `false` subject indicators mirror the real export.
_MISMO = """<?xml version="1.0" encoding="UTF-8"?>
<MESSAGE xmlns="http://www.mismo.org/residential/2009/schemas">
  <DEAL_SETS><DEAL_SET><DEALS><DEAL>
    <ASSETS><OWNED_PROPERTIES>
      <OWNED_PROPERTY>
        <OWNED_PROPERTY_DETAIL>
          <OwnedPropertyDispositionStatusType>Retain</OwnedPropertyDispositionStatusType>
          <OwnedPropertyLienUPBAmount>311262.00</OwnedPropertyLienUPBAmount>
          <OwnedPropertyOwnedUnitCount>1</OwnedPropertyOwnedUnitCount>
          <OwnedPropertyRentalIncomeNetAmount>-2381.00</OwnedPropertyRentalIncomeNetAmount>
          <OwnedPropertySubjectIndicator>false</OwnedPropertySubjectIndicator>
        </OWNED_PROPERTY_DETAIL>
        <PROPERTY><PROPERTY_DETAIL>
          <PropertyCurrentUsageType>Investment</PropertyCurrentUsageType>
          <PropertyEstimatedValueAmount>750000.00</PropertyEstimatedValueAmount>
          <PropertyUsageType>Investment</PropertyUsageType>
        </PROPERTY_DETAIL></PROPERTY>
      </OWNED_PROPERTY>
      <OWNED_PROPERTY>
        <OWNED_PROPERTY_DETAIL>
          <OwnedPropertyDispositionStatusType>Sell</OwnedPropertyDispositionStatusType>
          <OwnedPropertyLienUPBAmount>120000.00</OwnedPropertyLienUPBAmount>
          <OwnedPropertySubjectIndicator>false</OwnedPropertySubjectIndicator>
        </OWNED_PROPERTY_DETAIL>
        <PROPERTY><PROPERTY_DETAIL>
          <PropertyCurrentUsageType>PrimaryResidence</PropertyCurrentUsageType>
        </PROPERTY_DETAIL></PROPERTY>
      </OWNED_PROPERTY>
    </OWNED_PROPERTIES></ASSETS>
    <PARTIES><PARTY><INDIVIDUAL><NAME><FirstName>Sam</FirstName><LastName>Tan</LastName></NAME>
      </INDIVIDUAL><ROLES><ROLE><ROLE_DETAIL><PartyRoleType>Borrower</PartyRoleType></ROLE_DETAIL>
      </ROLE></ROLES></PARTY></PARTIES>
  </DEAL></DEALS></DEAL_SET></DEAL_SETS>
</MESSAGE>
"""


async def _file_with_import(db: AsyncSession, storage_path: str | None) -> LoanFile:
    company = Company(name="LP-596", slug=f"lp596-{uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
    loan_file = LoanFile(
        company_id=company.id,
        display_id=f"LF-{uuid4().hex[:4].upper()}",
        inbox_token=uuid4().hex,  # NOT NULL — the per-file upload capability
    )
    db.add(loan_file)
    await db.flush()
    db.add(
        MismoImport(
            loan_file_id=loan_file.id,
            source_format="xml",
            status=MismoImportStatus.COMPLETED,
            raw_file_path=storage_path,
        )
    )
    await db.flush()
    return loan_file


class _Storage:
    """Returns the fixture bytes for any path; a path in `broken` raises, as a lost object would."""

    def __init__(self, broken: set[str] | None = None) -> None:
        self.broken = broken or set()

    async def read(self, storage_path: str) -> bytes:
        if storage_path in self.broken:
            raise FileNotFoundError(storage_path)
        return _MISMO.encode()


def _use_storage(monkeypatch: pytest.MonkeyPatch, storage: _Storage) -> None:
    monkeypatch.setattr(
        "app.scripts.backfill_mismo_owned_properties.get_storage_backend", lambda: storage
    )


async def _count(db: AsyncSession, loan_file: LoanFile) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(StatedOwnedProperty)
            .where(StatedOwnedProperty.loan_file_id == loan_file.id)
        )
    ) or 0


async def test_report_only_writes_nothing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The safety property that lets this be pointed at production and merely looked at."""
    loan_file = await _file_with_import(db_session, "s3://raw/one.xml")
    _use_storage(monkeypatch, _Storage())

    outcome = await _backfill(db_session, apply=False)

    assert outcome.filled_files == 1
    assert outcome.filled_rows == 2
    assert await _count(db_session, loan_file) == 0


async def test_apply_writes_the_whole_schedule(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    loan_file = await _file_with_import(db_session, "s3://raw/one.xml")
    _use_storage(monkeypatch, _Storage())

    outcome = await _backfill(db_session, apply=True)

    assert outcome.filled_files == 1
    assert await _count(db_session, loan_file) == 2
    rows = list(
        (
            await db_session.execute(
                select(StatedOwnedProperty).where(StatedOwnedProperty.loan_file_id == loan_file.id)
            )
        ).scalars()
    )
    assert {r.disposition_status for r in rows} == {"Retain", "Sell"}
    assert {r.lien_upb for r in rows} == {Decimal("311262.00"), Decimal("120000.00")}
    # The tri-state survives the round trip — a stored False must not become None or True.
    assert all(r.is_subject is False for r in rows)


async def test_a_file_that_already_has_rows_is_skipped_entirely(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NOT a top-up, deliberately. A partial schedule is worse than none: a rule counting financed
    properties would count a subset and report a confident wrong number."""
    loan_file = await _file_with_import(db_session, "s3://raw/one.xml")
    db_session.add(StatedOwnedProperty(loan_file_id=loan_file.id, disposition_status="Retain"))
    await db_session.flush()
    _use_storage(monkeypatch, _Storage())

    outcome = await _backfill(db_session, apply=True)

    assert outcome.already_present == 1
    assert outcome.filled_files == 0
    assert await _count(db_session, loan_file) == 1  # untouched, not topped up to 3


async def test_running_twice_is_idempotent(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The property that makes a re-run safe after a partial run."""
    loan_file = await _file_with_import(db_session, "s3://raw/one.xml")
    _use_storage(monkeypatch, _Storage())

    await _backfill(db_session, apply=True)
    second = await _backfill(db_session, apply=True)

    assert second.filled_files == 0
    assert await _count(db_session, loan_file) == 2


async def test_one_unreadable_file_does_not_stop_the_batch(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _file_with_import(db_session, "s3://raw/lost.xml")
    good = await _file_with_import(db_session, "s3://raw/ok.xml")
    _use_storage(monkeypatch, _Storage(broken={"s3://raw/lost.xml"}))

    outcome = await _backfill(db_session, apply=True)

    assert outcome.unreadable == 1
    assert outcome.filled_files == 1
    assert await _count(db_session, good) == 2


async def test_an_export_with_no_schedule_is_recorded_not_failed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A purchase with no real estate owned states none, legitimately."""
    await _file_with_import(db_session, "s3://raw/none.xml")

    class _Empty(_Storage):
        async def read(self, storage_path: str) -> bytes:
            return _MISMO.replace(
                _MISMO[_MISMO.index("<OWNED_PROPERTY>") : _MISMO.rindex("</OWNED_PROPERTY>") + 18],
                "",
            ).encode()

    _use_storage(monkeypatch, _Empty())

    outcome = await _backfill(db_session, apply=True)

    assert outcome.schedule_absent == 1
    assert outcome.filled_files == 0
    assert outcome.unreadable == 0
