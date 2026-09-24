"""Reading rounds and conditions (LP-909 section 1, spec §LP-909).

⚠️ THE TWO FIELDS UNDER TEST HERE HAD NO PRODUCER UNTIL THIS SECTION. `condition_count` defaulted to
0 and `round_numbers` to `[]` from LP-904 onward — declared, documented, indexed for, and filled by
nothing. A round strip reading "0 on sheet" and `R1 R2` chips that never appeared would have looked
like a UI bug for as long as anyone cared to look, which is why the assertions below are about the
VALUES rather than about the endpoints answering 200.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from app.conditions.fingerprint import fingerprint
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from app.models.condition import BucketKind, Condition
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import (
    ConditionRound,
    ConditionRoundCompleteness,
    ConditionRoundStatus,
)
from app.services.condition_rounds import create_round_from_paste
from app.services.loan_files import create_loan_file
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.fixture_helpers import portal_excerpt


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Shadows the root fixture so the request shares this test's session (see LP-905 §1)."""

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _user(db: AsyncSession, *, slug: str) -> tuple[Company, str]:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=f"u@{slug}.com",
        hashed_password=hash_password("irrelevant"),
        first_name="Test",
        last_name="User",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return company, create_access_token(user.id)


async def _imported_round(
    db: AsyncSession, *, slug: str, number: int = 1
) -> tuple[object, ConditionRound, str]:
    """A round whose rows became conditions, with the appearance events import writes."""
    company, token = await _user(db, slug=slug)
    loan_file = await create_loan_file(db, company_id=company.id)
    round_ = await create_round_from_paste(
        db,
        loan_file=loan_file,
        text=portal_excerpt(),
        completeness=ConditionRoundCompleteness.FULL,
    )
    for index, row in enumerate(round_.draft_rows or [], start=1):
        condition = Condition(
            company_id=company.id,
            loan_file_id=loan_file.id,
            first_round_id=round_.id,
            last_seen_round_id=round_.id,
            sequence=index,
            lender_code=row["lender_code"],
            bucket_heading=row["bucket_heading"],
            bucket_kind=BucketKind(row["bucket_kind"]),
            verbatim_text=row["verbatim_text"],
            text_fingerprint=fingerprint(row["verbatim_text"]),
            underwriter_notes=[],
        )
        db.add(condition)
        await db.flush()
        db.add(
            ConditionEvent(
                company_id=company.id,
                loan_file_id=loan_file.id,
                round_id=round_.id,
                condition_id=condition.id,
                kind=ConditionEventKind.CONDITION_CREATED,
                detail={"source": "import"},
            )
        )
    round_.status = ConditionRoundStatus.IMPORTED
    round_.round_number = number
    round_.draft_rows = None
    await db.flush()
    return loan_file, round_, token


async def test_the_round_strip_counts_the_conditions_on_each_round(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """⚠️ `condition_count`'s FIRST REAL VALUE. Defaulted to 0 since LP-904 with no producer, so the
    round card would have said "0 on sheet" for six conditions."""
    loan_file, round_, token = await _imported_round(db_session, slug="read-strip")

    response = await client.get(
        f"/api/v1/loan-files/{loan_file.id}/condition-rounds", headers=_auth(token)
    )

    assert response.status_code == 200, response.text
    (card,) = response.json()
    assert card["id"] == str(round_.id)
    assert card["round_number"] == 1
    assert card["condition_count"] == 6, "six conditions appeared on this round"


async def test_a_draft_round_counts_the_rows_it_holds(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """⚠️ THE COUNT COMES FROM A DIFFERENT PLACE BEFORE IMPORT, and conflating them would make every
    draft look empty: a draft has rows and no conditions, an imported round the reverse."""
    company, token = await _user(db_session, slug="read-draft")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    await create_round_from_paste(
        db_session,
        loan_file=loan_file,
        text=portal_excerpt(),
        completeness=ConditionRoundCompleteness.PARTIAL,
    )

    response = await client.get(
        f"/api/v1/loan-files/{loan_file.id}/condition-rounds", headers=_auth(token)
    )

    (card,) = response.json()
    assert card["status"] == ConditionRoundStatus.DRAFT.value
    assert card["round_number"] is None, "numbers are assigned on import"
    assert card["condition_count"] == 6


async def test_each_condition_reports_the_rounds_it_appeared_on(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """⚠️ `round_numbers`' FIRST REAL VALUE — the `R1 R2` chips, `[]` since LP-904.

    Derived from the appearance events rather than from `first_round_id` / `last_seen_round_id`,
    because two columns cannot express "appeared on R1 and R3 but not R2".
    """
    loan_file, _round, token = await _imported_round(db_session, slug="read-chips")

    response = await client.get(
        f"/api/v1/loan-files/{loan_file.id}/conditions", headers=_auth(token)
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 6
    assert all(condition["round_numbers"] == [1] for condition in body)
    # Sheet order, which is what `sequence` is for — the order the lender printed them.
    assert [c["sequence"] for c in body] == [1, 2, 3, 4, 5, 6]


async def test_a_condition_seen_on_two_rounds_carries_both_numbers(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The chips' whole purpose: a condition the lender printed again. Two events, two numbers."""
    loan_file, first_round, token = await _imported_round(db_session, slug="read-twochips")

    second = ConditionRound(
        company_id=first_round.company_id,
        loan_file_id=first_round.loan_file_id,
        status=ConditionRoundStatus.IMPORTED,
        round_number=2,
        completeness=ConditionRoundCompleteness.PARTIAL,
        sources=[{"kind": "paste", "at": "2026-09-24T00:00:00+00:00"}],
        round_date=first_round.round_date,
        parse_report={},
    )
    db_session.add(second)
    await db_session.flush()

    # ⚠️ A PLAIN `select(...)` OF THE COLUMN I WANT. An earlier version used
    # `ConditionEvent.__table__.select()` — a Core select whose rows are positional, so
    # `.condition_id` on the first row came back `None` and the assertion failed with
    # `KeyError: 'None'`. That shape appears nowhere else in this suite; it was my invention, and
    # the ORM form every neighbouring test uses says what it wants.
    seen_again = (
        await db_session.scalars(
            select(ConditionEvent.condition_id).where(
                ConditionEvent.round_id == first_round.id,
                ConditionEvent.kind == ConditionEventKind.CONDITION_CREATED,
            )
        )
    ).first()
    assert seen_again is not None
    db_session.add(
        ConditionEvent(
            company_id=first_round.company_id,
            loan_file_id=first_round.loan_file_id,
            round_id=second.id,
            condition_id=seen_again,
            kind=ConditionEventKind.CONDITION_SEEN_AGAIN,
            detail={},
        )
    )
    await db_session.flush()

    body = (
        await client.get(f"/api/v1/loan-files/{loan_file.id}/conditions", headers=_auth(token))
    ).json()

    chips = {c["id"]: c["round_numbers"] for c in body}
    assert chips[str(seen_again)] == [1, 2]
    assert sum(1 for numbers in chips.values() if numbers == [1]) == 5


async def test_one_round_comes_back_with_its_parse_report(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company, token = await _user(db_session, slug="read-one")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    round_ = await create_round_from_paste(
        db_session,
        loan_file=loan_file,
        text=portal_excerpt(),
        completeness=ConditionRoundCompleteness.FULL,
    )

    response = await client.get(f"/api/v1/condition-rounds/{round_.id}", headers=_auth(token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(round_.id)
    assert body["parse_report"]["reader"] == "uwm"
    assert len(body["draft_rows"]) == 6


async def test_another_companys_rounds_are_invisible(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """CRITICAL: cross-tenant isolation, on a READ. An ungated GET is what leaks."""
    loan_file_a, round_a, _token_a = await _imported_round(db_session, slug="read-tenant-a")
    _company_b, token_b = await _user(db_session, slug="read-tenant-b")

    rounds = await client.get(
        f"/api/v1/loan-files/{loan_file_a.id}/condition-rounds", headers=_auth(token_b)
    )
    conditions = await client.get(
        f"/api/v1/loan-files/{loan_file_a.id}/conditions", headers=_auth(token_b)
    )
    one = await client.get(f"/api/v1/condition-rounds/{round_a.id}", headers=_auth(token_b))

    # The same 404 as a missing id — distinguishing them would confirm the id exists.
    assert rounds.status_code == 404
    assert conditions.status_code == 404
    assert one.status_code == 404


async def test_a_missing_file_and_a_missing_round_are_both_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _company, token = await _user(db_session, slug="read-missing")

    assert (
        await client.get(f"/api/v1/loan-files/{uuid4()}/condition-rounds", headers=_auth(token))
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/condition-rounds/{uuid4()}", headers=_auth(token))
    ).status_code == 404


async def test_the_reads_require_authentication(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    loan_file, round_, _token = await _imported_round(db_session, slug="read-anon")

    assert (
        await client.get(f"/api/v1/loan-files/{loan_file.id}/condition-rounds")
    ).status_code == 401
    assert (await client.get(f"/api/v1/condition-rounds/{round_.id}")).status_code == 401
