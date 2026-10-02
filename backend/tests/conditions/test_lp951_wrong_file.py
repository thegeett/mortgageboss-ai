"""LP-951 — the wrong-file warning (the staging trial's item 11, raised to High).

The fixture sheet's title line is `LOAN APPROVAL CONDITIONS - RIVERA - 1226500417`. The staging trial
imported a sheet for one borrower onto another's file without a word; now the review screen warns, the
import route refuses until she confirms, and her confirmation is a round event with no names in it.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from app.models import Company
from app.models.borrower import Borrower
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import ConditionRound, ConditionRoundStatus, ConditionSourceKind
from app.models.loan_file import LoanFile
from app.services.condition_import import import_round
from app.services.condition_rounds import SheetBytes, create_round_from_sheet
from app.services.condition_wrong_file import wrong_file_check
from app.tasks.conditions import parse_round
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.fixture_helpers import UWM_ROUND_1
from tests.conditions.uwm_pdf_fixture import render_uwm_pdf
from tests.models.conftest_helpers import make_loan_file

SHEET_NUMBER = "1226500417"


async def _file(db: AsyncSession, *last_names: str) -> LoanFile:
    company = Company(name="Wrong file", slug=f"wf-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    loan_file = await make_loan_file(db, company=company)
    for index, last in enumerate(last_names):
        db.add(
            Borrower(
                loan_file_id=loan_file.id,
                first_name="Test",
                last_name=last,
                is_primary=index == 0,
            )
        )
    await db.flush()
    return loan_file


async def _draft(db: AsyncSession, loan_file: LoanFile) -> ConditionRound:
    round_ = await create_round_from_sheet(
        db,
        loan_file=loan_file,
        sheet=SheetBytes(
            content=render_uwm_pdf(UWM_ROUND_1), source_kind=ConditionSourceKind.PDF_UPLOAD
        ),
    )
    await db.flush()
    await parse_round(db, round_.id)
    await db.refresh(round_)
    assert round_.status is ConditionRoundStatus.DRAFT
    assert f"RIVERA - {SHEET_NUMBER}" in (round_.raw_text or "")
    return round_


# --------------------------------------------------------------------------------------------- #
# The check
# --------------------------------------------------------------------------------------------- #


async def test_a_sheet_for_another_borrower_is_flagged(db_session: AsyncSession) -> None:
    loan_file = await _file(db_session, "Patel")
    found = await wrong_file_check(db_session, round_=await _draft(db_session, loan_file))
    assert found is not None
    assert (found.sheet_surname, found.file_surnames) == ("RIVERA", ["Patel"])
    assert found.borrower_differs and not found.loan_number_differs


@pytest.mark.parametrize("last_names", [("Rivera",), ("Patel", "rivera"), ("Rivera-Lopez",)])
async def test_the_right_borrower_is_not_flagged(
    db_session: AsyncSession, last_names: tuple[str, ...]
) -> None:
    """The positive control: the same sheet, the borrower on the file (any case, a co-borrower, a
    hyphenated surname)."""
    loan_file = await _file(db_session, *last_names)
    assert await wrong_file_check(db_session, round_=await _draft(db_session, loan_file)) is None


async def test_nothing_to_compare_is_not_a_mismatch(db_session: AsyncSession) -> None:
    """No borrowers and no earlier sheet: the first sheet on an empty file is not refused."""
    loan_file = await _file(db_session)
    assert await wrong_file_check(db_session, round_=await _draft(db_session, loan_file)) is None


async def test_a_new_loan_number_against_the_earlier_sheets_is_flagged(
    db_session: AsyncSession,
) -> None:
    loan_file = await _file(db_session, "Rivera")
    first = await _draft(db_session, loan_file)
    await import_round(db_session, round_=first)

    second = await _draft(db_session, loan_file)
    assert await wrong_file_check(db_session, round_=second) is None  # same number: no warning
    second.raw_text = (second.raw_text or "").replace(SHEET_NUMBER, "9988776655")
    found = await wrong_file_check(db_session, round_=second)
    assert found is not None
    assert found.loan_number_differs and not found.borrower_differs
    assert (found.sheet_loan_number, found.file_loan_numbers) == ("9988776655", [SHEET_NUMBER])


# --------------------------------------------------------------------------------------------- #
# The routes
# --------------------------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _drop_db_override() -> Any:
    from app.core.database import get_db
    from app.main import app

    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def _no_reading(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import conditions as conditions_api

    monkeypatch.setattr(conditions_api, "_enqueue_reading", lambda _rid: None)


async def _confirmed_events(db: AsyncSession, round_: ConditionRound) -> list[ConditionEvent]:
    return list(
        await db.scalars(
            select(ConditionEvent).where(
                ConditionEvent.round_id == round_.id,
                ConditionEvent.kind == ConditionEventKind.ROUND_WRONG_FILE_CONFIRMED,
            )
        )
    )


async def test_import_is_refused_until_she_confirms_and_the_override_is_recorded(
    db_session: AsyncSession,
) -> None:
    from tests.conditions.test_lender_condition_settings import _clients

    loan_file = await _file(db_session, "Patel")
    round_ = await _draft(db_session, loan_file)
    client, _, processor = await _clients(db_session, loan_file)
    base = f"/api/v1/condition-rounds/{round_.id}"
    async with client:
        warning = await client.get(f"{base}/wrong-file", headers=processor)
        assert warning.status_code == 200
        assert warning.json()["sheet_surname"] == "RIVERA"
        assert warning.json()["borrower_differs"] is True

        refused = await client.post(f"{base}/import", json={}, headers=processor)
        assert refused.status_code == 409
        assert "does not look like this file's" in refused.json()["error"]["message"]
        assert refused.json()["error"]["data"]["code"] == "wrong_file"
        await db_session.refresh(round_)
        assert round_.status is ConditionRoundStatus.DRAFT

        imported = await client.post(
            f"{base}/import", json={"confirm_wrong_file": True}, headers=processor
        )
        assert imported.status_code == 200, imported.text
    [event] = await _confirmed_events(db_session, round_)
    # WHICH facts differed, never the names or numbers.
    assert event.detail == {"borrower_differs": True, "loan_number_differs": False}
    assert event.condition_id is None and event.actor_user_id is not None


async def test_a_matching_sheet_imports_without_a_confirmation_or_an_event(
    db_session: AsyncSession,
) -> None:
    from tests.conditions.test_lender_condition_settings import _clients

    loan_file = await _file(db_session, "Rivera")
    round_ = await _draft(db_session, loan_file)
    client, _, processor = await _clients(db_session, loan_file)
    base = f"/api/v1/condition-rounds/{round_.id}"
    async with client:
        warning = await client.get(f"{base}/wrong-file", headers=processor)
        assert warning.status_code == 200 and warning.json() is None
        imported = await client.post(f"{base}/import", json={}, headers=processor)
        assert imported.status_code == 200, imported.text
    assert await _confirmed_events(db_session, round_) == []


async def test_another_companys_round_is_404(db_session: AsyncSession) -> None:
    from tests.conditions.test_lender_condition_settings import _clients

    loan_file = await _file(db_session, "Patel")
    round_ = await _draft(db_session, loan_file)
    stranger = await _file(db_session, "Other")
    client, _, processor = await _clients(db_session, stranger)
    async with client:
        got = await client.get(
            f"/api/v1/condition-rounds/{round_.id}/wrong-file", headers=processor
        )
        assert got.status_code == 404


# --------------------------------------------------------------------------------------------- #
# LP-951 review — names as lenders print them, other readers, and the other doors
# --------------------------------------------------------------------------------------------- #


def _title(surname: str, number: str = SHEET_NUMBER) -> str:
    return f"LOAN APPROVAL CONDITIONS - {surname} - {number}\nPrior to Docs\n"


@pytest.mark.parametrize(
    ("sheet", "file_name", "differs"),
    [
        # Lenders print ASCII capitals; the file keeps the borrower's spelling. Each was a false warning.
        ("MUNOZ", "Muñoz", False),
        ("OBRIEN", "O'Brien", False),
        ("OBRIEN", "O\u2019Brien", False),
        ("DELACRUZ", "De La Cruz", False),
        # Inside a compound name the joined form does not rescue them, so these need the stripping.
        ("MUNOZ", "Muñoz-Garcia", False),
        ("OBRIEN", "O'Brien-Kelly", False),
        ("SMITH JR", "Smith", False),
        ("LE", "Le", False),
        # A shared particle is not the same surname; a name inside another word is not either.
        ("DE LA CRUZ", "De Leon", True),
        ("ANN", "Annabel", True),
    ],
)
async def test_names_compare_as_lenders_print_them(
    db_session: AsyncSession, sheet: str, file_name: str, differs: bool
) -> None:
    from app.services.condition_wrong_file import compare_sheet

    loan_file = await _file(db_session, file_name)
    found = await compare_sheet(db_session, loan_file_id=loan_file.id, text=_title(sheet))
    assert (found is not None and found.borrower_differs) is differs


async def test_a_hyphenated_surname_on_the_sheet_is_still_read(db_session: AsyncSession) -> None:
    """`[^-\\n]` in the title pattern made RIVERA-LOPEZ's whole title unreadable, number included, so
    the check was silently off for any hyphenated borrower."""
    from app.services.condition_drafts import letter_title
    from app.services.condition_wrong_file import compare_sheet

    assert letter_title(_title("RIVERA-LOPEZ")) == ("RIVERA-LOPEZ", SHEET_NUMBER)
    patel = await _file(db_session, "Patel")
    found = await compare_sheet(db_session, loan_file_id=patel.id, text=_title("RIVERA-LOPEZ"))
    assert found is not None and found.sheet_surname == "RIVERA-LOPEZ"
    lopez = await _file(db_session, "Lopez")
    assert (
        await compare_sheet(db_session, loan_file_id=lopez.id, text=_title("RIVERA-LOPEZ")) is None
    )


async def test_a_champions_loan_number_is_compared(db_session: AsyncSession) -> None:
    """Champions prints `Loan #:` on every page and no title line; it was never read."""
    from app.services.condition_wrong_file import compare_sheet, sheet_facts

    champions = "Conditional Approval Certificate\nDate: 9/11/26 Loan #: 4400-123-456\n"
    assert sheet_facts(champions) == (None, "4400123456")
    loan_file = await _file(db_session, "Rivera")
    await import_round(db_session, round_=await _draft(db_session, loan_file))

    found = await compare_sheet(db_session, loan_file_id=loan_file.id, text=champions)
    assert found is not None and found.loan_number_differs
    assert found.file_loan_numbers == [SHEET_NUMBER]
    same = f"Conditional Approval Certificate\nDate: 9/11/26 Loan #: {SHEET_NUMBER}\n"
    assert await compare_sheet(db_session, loan_file_id=loan_file.id, text=same) is None


async def test_a_discarded_sheet_is_not_the_files_number(db_session: AsyncSession) -> None:
    from app.services.condition_rounds import discard_round

    loan_file = await _file(db_session, "Rivera")
    await discard_round(db_session, round_=await _draft(db_session, loan_file))
    second = await _draft(db_session, loan_file)
    second.raw_text = (second.raw_text or "").replace(SHEET_NUMBER, "9988776655")
    assert await wrong_file_check(db_session, round_=second) is None


async def test_two_borrowers_with_one_surname_are_named_once(db_session: AsyncSession) -> None:
    loan_file = await _file(db_session, "Patel", "PATEL")
    found = await wrong_file_check(db_session, round_=await _draft(db_session, loan_file))
    assert found is not None and found.file_surnames == ["Patel"]


async def _pasted(db: AsyncSession, loan_file: LoanFile) -> ConditionRound:
    from app.models.condition_round import ConditionRoundCompleteness
    from app.services.condition_rounds import create_round_from_paste
    from tests.conditions.fixture_helpers import portal_excerpt

    round_ = await create_round_from_paste(
        db,
        loan_file=loan_file,
        text=portal_excerpt(),
        completeness=ConditionRoundCompleteness.PARTIAL,
    )
    await db.flush()
    return round_


@pytest.mark.parametrize("imported", [False, True])
async def test_attaching_another_files_pdf_is_refused_until_she_confirms(
    db_session: AsyncSession, imported: bool
) -> None:
    """The attach door turns a PDF into rows (draft) or conditions (imported), and the enrich discards
    the PDF's text, so the import route's check never saw its title."""
    from tests.conditions.test_lender_condition_settings import _clients

    loan_file = await _file(db_session, "Patel")
    round_ = await _pasted(db_session, loan_file)
    if imported:
        await import_round(db_session, round_=round_)
    sources_before = list(round_.sources or [])
    client, _, processor = await _clients(db_session, loan_file)
    url = f"/api/v1/condition-rounds/{round_.id}/attach-pdf"
    pdf = {"file": ("sheet.pdf", render_uwm_pdf(UWM_ROUND_1), "application/pdf")}
    async with client:
        refused = await client.post(url, files=pdf, headers=processor)
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"]["data"]["code"] == "wrong_file"
        await db_session.refresh(round_)
        assert list(round_.sources or []) == sources_before
        assert await _confirmed_events(db_session, round_) == []

        attached = await client.post(
            url, files=pdf, data={"confirm_wrong_file": "true"}, headers=processor
        )
        assert attached.status_code == 200, attached.text
    [event] = await _confirmed_events(db_session, round_)
    assert event.detail == {"borrower_differs": True, "loan_number_differs": False}


async def test_attaching_this_files_pdf_needs_no_confirmation(db_session: AsyncSession) -> None:
    """The positive control for the attach door."""
    from tests.conditions.test_lender_condition_settings import _clients

    loan_file = await _file(db_session, "Rivera")
    round_ = await _pasted(db_session, loan_file)
    client, _, processor = await _clients(db_session, loan_file)
    pdf = {"file": ("sheet.pdf", render_uwm_pdf(UWM_ROUND_1), "application/pdf")}
    async with client:
        attached = await client.post(
            f"/api/v1/condition-rounds/{round_.id}/attach-pdf", files=pdf, headers=processor
        )
        assert attached.status_code == 200, attached.text
    assert await _confirmed_events(db_session, round_) == []


async def test_a_forwarded_pdf_merged_into_a_round_is_checked_too(db_session: AsyncSession) -> None:
    """The email door into an existing round goes through the same enrich."""
    from app.models.inbound_message import InboundMessage
    from tests.api.test_condition_forward_endpoint import _arrive
    from tests.conditions.test_lender_condition_settings import _clients

    loan_file = await _file(db_session, "Patel")
    round_ = await _pasted(db_session, loan_file)
    attachment = await _arrive(
        db_session, address=loan_file.get_inbox_address(), content=render_uwm_pdf(UWM_ROUND_1)
    )
    message = await db_session.get(InboundMessage, attachment.inbound_message_id)
    assert message is not None
    message.loan_file_id = loan_file.id
    await db_session.flush()
    client, _, processor = await _clients(db_session, loan_file)
    url = f"/api/v1/loan-files/{loan_file.id}/inbound/attachments/{attachment.id}/condition-round"
    async with client:
        refused = await client.post(
            url, json={"attach_to_round_id": str(round_.id)}, headers=processor
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"]["data"]["code"] == "wrong_file"
        merged = await client.post(
            url,
            json={"attach_to_round_id": str(round_.id), "confirm_wrong_file": True},
            headers=processor,
        )
        assert merged.status_code == 200, merged.text
    assert len(await _confirmed_events(db_session, round_)) == 1


async def test_a_pasted_rounds_own_title_is_the_files_number_on_attach(
    db_session: AsyncSession,
) -> None:
    """A pasted round that carried UWM's title names its loan number; a PDF with another is refused."""
    from app.models.condition_round import ConditionRoundCompleteness
    from app.services.condition_enrich import enrich_round_with_pdf
    from app.services.condition_rounds import create_round_from_paste
    from app.services.condition_wrong_file import WrongFileRefused
    from tests.conditions.fixture_helpers import portal_excerpt

    loan_file = await _file(db_session, "Rivera")
    round_ = await create_round_from_paste(
        db_session,
        loan_file=loan_file,
        text=_title("RIVERA", "9988776655") + portal_excerpt(),
        completeness=ConditionRoundCompleteness.PARTIAL,
    )
    await db_session.flush()
    with pytest.raises(WrongFileRefused):
        await enrich_round_with_pdf(db_session, round_=round_, content=render_uwm_pdf(UWM_ROUND_1))
