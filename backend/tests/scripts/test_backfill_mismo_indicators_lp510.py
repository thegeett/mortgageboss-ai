"""LP-510 — the property-indicator backfill.

LP-509-B1 taught the parser to read `PropertyInProjectIndicator` / `PUDIndicator`, which decide
`property.type` when an export states none. Import is ONE-SHOT, so every file imported before that
change has both columns NULL and re-running verification never re-parses the XML — CO-1/CO-3/CO-4/IH-7
went on abstaining on the real staging file even after the fix deployed. This backfill closes that.

The properties asserted here are the ones that make it safe to run against production data: it writes
nothing without an explicit flag, it only ever fills a NULL, and one unreadable file does not stop the
batch.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.models.company import Company
from app.models.loan_file import LoanFile
from app.models.mismo_import import MismoImport, MismoImportStatus
from app.models.property import Property
from app.scripts.backfill_mismo_property_indicators import _backfill
from sqlalchemy.ext.asyncio import AsyncSession

# The two indicators inside an otherwise minimal MISMO 3.4 SUBJECT_PROPERTY.
_MISMO = """<?xml version="1.0" encoding="UTF-8"?>
<MESSAGE xmlns="http://www.mismo.org/residential/2009/schemas">
  <DEAL_SETS><DEAL_SET><DEALS><DEAL>
    <COLLATERALS><COLLATERAL><SUBJECT_PROPERTY>
      <ADDRESS><AddressLineText>1 Cedar Ct</AddressLineText><CityName>Rivertown</CityName>
        <StateCode>IL</StateCode><PostalCode>60000</PostalCode></ADDRESS>
      <PROPERTY_DETAIL>
        <AttachmentType>Detached</AttachmentType>
        <PropertyInProjectIndicator>false</PropertyInProjectIndicator>
        <PUDIndicator>true</PUDIndicator>
        <FinancedUnitCount>1</FinancedUnitCount>
      </PROPERTY_DETAIL>
    </SUBJECT_PROPERTY></COLLATERAL></COLLATERALS>
    <PARTIES><PARTY><INDIVIDUAL><NAME><FirstName>Sam</FirstName><LastName>Tan</LastName></NAME>
      </INDIVIDUAL><ROLES><ROLE><ROLE_DETAIL><PartyRoleType>Borrower</PartyRoleType></ROLE_DETAIL>
      </ROLE></ROLES></PARTY></PARTIES>
  </DEAL></DEALS></DEAL_SET></DEAL_SETS>
</MESSAGE>
"""


async def _file_with_import(db: AsyncSession, storage_path: str | None) -> Property:
    company = Company(name="LP-510", slug=f"lp510-{uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
    loan_file = LoanFile(
        company_id=company.id,
        display_id=f"LF-{uuid4().hex[:4].upper()}",
        inbox_token=uuid4().hex,  # NOT NULL — the per-file upload capability
    )
    db.add(loan_file)
    await db.flush()
    prop = Property(loan_file_id=loan_file.id)  # in_project / is_pud left NULL, as a pre-fix row is
    db.add(prop)
    db.add(
        MismoImport(
            loan_file_id=loan_file.id,
            source_format="xml",
            status=MismoImportStatus.COMPLETED,
            raw_file_path=storage_path,
        )
    )
    await db.flush()
    return prop


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
        "app.scripts.backfill_mismo_property_indicators.get_storage_backend", lambda: storage
    )


async def test_report_only_writes_nothing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default must be safe to run against production: it says what it WOULD do and stops.

    Looking and changing are separate actions — that is the whole reason the flag exists.
    """
    _use_storage(monkeypatch, _Storage())
    await _file_with_import(db_session, "mismo/raw.xml")

    outcome = await _backfill(db_session, apply=False)

    # It found the row and says so, and it marks the line as not written. The row itself is not
    # re-read here: report-only ends in `rollback()`, which in a shared test session also discards the
    # fixture inserts — in production `_run` owns the session, so the rollback only undoes the backfill.
    assert outcome.filled == 1
    assert any("report only — not written" in line for line in outcome.details)


async def test_apply_fills_both_indicators(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_storage(monkeypatch, _Storage())
    prop = await _file_with_import(db_session, "mismo/raw.xml")

    outcome = await _backfill(db_session, apply=True)

    assert outcome.filled == 1
    await db_session.refresh(prop)
    assert prop.in_project is False
    assert prop.is_pud is True


async def test_an_existing_value_is_never_overwritten(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Idempotent AND non-destructive: a hand-corrected value survives a re-run.

    The fixture states `is_pud=true`; the row already says False. The backfill must leave it alone —
    otherwise re-running this would silently revert a human's correction.
    """
    _use_storage(monkeypatch, _Storage())
    prop = await _file_with_import(db_session, "mismo/raw.xml")
    prop.is_pud = False
    await db_session.flush()

    await _backfill(db_session, apply=True)

    await db_session.refresh(prop)
    assert prop.is_pud is False  # not flipped to the fixture's True
    assert prop.in_project is False  # the still-NULL one was filled


async def test_a_row_with_both_set_is_skipped(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_storage(monkeypatch, _Storage())
    prop = await _file_with_import(db_session, "mismo/raw.xml")
    prop.in_project = True
    prop.is_pud = True
    await db_session.flush()

    outcome = await _backfill(db_session, apply=True)

    assert outcome.already_set == 1 and outcome.filled == 0


async def test_one_unreadable_file_does_not_stop_the_batch(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lost object is reported and skipped; the other files still get backfilled.

    Aborting the run on the first missing object would make the task all-or-nothing across every
    loan file in the environment — one absent S3 key would block the rest indefinitely.
    """
    _use_storage(monkeypatch, _Storage(broken={"mismo/missing.xml"}))
    good = await _file_with_import(db_session, "mismo/raw.xml")
    await _file_with_import(db_session, "mismo/missing.xml")

    outcome = await _backfill(db_session, apply=True)

    assert outcome.unreadable == 1
    assert outcome.filled == 1
    await db_session.refresh(good)
    assert good.in_project is False


async def test_an_import_with_no_retained_file_is_reported(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing to re-parse is a REPORTED outcome, not a silent skip — it is the one case where the
    data is genuinely unrecoverable and someone has to decide what to do about it."""
    _use_storage(monkeypatch, _Storage())
    await _file_with_import(db_session, None)

    outcome = await _backfill(db_session, apply=True)

    assert outcome.no_raw_file == 1 and outcome.filled == 0
