"""What an import found changed (LP-915, spec §7.2 and §7.3).

EVERY EXPECTED VALUE HERE IS THE SPEC'S, TRANSCRIBED BEFORE THE ENGINE RAN. §7.2 and §7.3 state the
exact codes in each outcome and the exact letter changes, and the Done-when says it "must be an exact
assertion, not a count". Writing the comparison first and asserting whatever it produced would test
that the code does what it does.

DRIVEN THROUGH THE REAL IMPORT, NEVER HAND-BUILT EVENTS. The engine derives every outcome from the
`CONDITION_CREATED` / `SEEN_AGAIN` / `CAME_BACK` rows the importer writes, so a test that wrote those
rows itself would assert against a shape of my own invention. That is exactly how LP-916's projection
tests passed while the feature was broken — they built `detail` by hand with keys the writer never
produced — and the reviewer's R1 is the same lesson one ticket earlier. The sheets go in as PDFs
through the upload door and are imported the way a processor imports them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from app.models.condition import Condition
from app.models.condition_round import ConditionRound, ConditionRoundCompleteness
from app.models.loan_file import LoanFile
from app.services.condition_compare import confirm_probably_cleared
from app.services.loan_files import create_loan_file
from app.tasks import conditions as task_module
from app.tasks.conditions import parse_round
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.fixture_helpers import UWM_ROUND_1, UWM_ROUND_2, UWM_ROUND_3
from tests.conditions.uwm_pdf_fixture import render_uwm_pdf
from tests.models.conftest_helpers import make_lender

API = "/api/v1"


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


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What the upload door handed to Celery — recorded rather than sent."""
    seen: list[str] = []
    monkeypatch.setattr(
        task_module.parse_condition_round, "delay", lambda round_id: seen.append(round_id)
    )
    return seen


async def _file_with_codes(db: AsyncSession) -> tuple[LoanFile, dict[str, str]]:
    """A UWM file whose code map is seeded the way the application seeds it.

    Without the seed nine of round 1's eleven owners come back `unknown`, which changes nothing this
    file asserts — but a fixture that silently seeded nothing is how a later assertion about owners
    would fail for a reason it is not about.
    """
    company = Company(name="Compare", slug=f"compare-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=f"u-{uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("irrelevant"),
        first_name="Priya",
        last_name="Raman",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db.add(user)
    loan_file = await create_loan_file(db, company_id=company.id)
    lender = await make_lender(db, company=company, name="UWM")
    lender.canonical_lender_key = "uwm"
    loan_file.lender_id = lender.id
    await db.flush()

    return loan_file, {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def _upload_and_import(
    client: AsyncClient,
    auth: dict[str, str],
    loan_file: LoanFile,
    *,
    db: AsyncSession,
    enqueued: list[str],
    fixture: str,
    completeness: str = "full",
) -> UUID:
    """One sheet through the real door: upload → parse → import. Returns the round id."""
    response = await client.post(
        f"{API}/loan-files/{loan_file.id}/condition-rounds/uploads",
        files={"file": (f"{fixture}.pdf", render_uwm_pdf(fixture), "application/pdf")},
        data={"completeness": completeness},
        headers=auth,
    )
    assert response.status_code == 202, response.text
    round_id = response.json()["id"]
    assert enqueued[-1] == round_id

    await parse_round(db, UUID(round_id))
    imported = await client.post(f"{API}/condition-rounds/{round_id}/import", headers=auth)
    assert imported.status_code == 200, imported.text
    return UUID(round_id)


async def _round(db: AsyncSession, round_id: UUID) -> ConditionRound:
    return (
        await db.execute(select(ConditionRound).where(ConditionRound.id == round_id))
    ).scalar_one()


async def _codes(db: AsyncSession, ids: list[str]) -> list[str]:
    """Condition ids → their lender codes, sorted — so an assertion reads as the sheet does."""
    if not ids:
        return []
    rows = (
        (await db.execute(select(Condition).where(Condition.id.in_([UUID(i) for i in ids]))))
        .scalars()
        .all()
    )
    return sorted(row.lender_code or "—" for row in rows)


# --------------------------------------------------------------------------- #
# §7.2 — round 1 (full) then round 2 (full)
# --------------------------------------------------------------------------- #


async def test_round_two_suggests_exactly_the_five_the_spec_names(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    """THE DONE-WHEN, AS AN EXACT SET. "Probably cleared = exactly 7086 6132 6637 6178 0132".

    A count would pass on five of the wrong conditions. This is the assertion the whole comparison
    exists to earn, and the one a reviewer can check against the fixtures by eye.
    """
    loan_file, auth = await _file_with_codes(db_session)
    await _upload_and_import(
        client, auth, loan_file, db=db_session, enqueued=enqueued, fixture=UWM_ROUND_1
    )
    round_2 = await _upload_and_import(
        client, auth, loan_file, db=db_session, enqueued=enqueued, fixture=UWM_ROUND_2
    )

    comparison = (await _round(db_session, round_2)).comparison
    assert comparison is not None, "an import of round 2 computes and saves a comparison"

    assert await _codes(db_session, comparison["probably_cleared"]) == [
        "0132",
        "6132",
        "6178",
        "6637",
        "7086",
    ]
    assert await _codes(db_session, comparison["still_open"]) == [
        "0006",
        "0007",
        "1228",
        "1582",
        "1947",
        "6378",
    ]
    assert comparison["new"] == []
    assert comparison["came_back"] == []
    assert comparison["reworded"] == []
    # "Compared with the 11 conditions that were open before it." (S2-06).
    assert comparison["compared_with"] == 11
    assert comparison["no_suggestions_reason"] is None


async def test_round_two_reports_only_the_letter_values_that_moved(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    """§7.2's letter changes, old → new, and NOTHING that stayed the same.

    `Rate Lock Exp` IS THE ONE THAT MATTERS MOST. Round 1's is blank and round 2's is 09/30/2026, so
    it must read "— → 09/30/2026" — a value appearing, not changing. `Verified Income` is identical
    on both sheets and must be absent: showing every field would bury the note rate under a list of
    things nobody changed.
    """
    loan_file, auth = await _file_with_codes(db_session)
    await _upload_and_import(
        client, auth, loan_file, db=db_session, enqueued=enqueued, fixture=UWM_ROUND_1
    )
    round_2 = await _upload_and_import(
        client, auth, loan_file, db=db_session, enqueued=enqueued, fixture=UWM_ROUND_2
    )

    changes = (await _round(db_session, round_2)).comparison["letter_changes"]
    by_label = {change["label"]: (change["old"], change["new"]) for change in changes}

    assert by_label["note rate"] == ("6.374%", "6.490%")
    assert by_label["housing / debt ratios"] == ("32.51% / 40.36%", "32.83% / 40.69%")
    assert by_label["verified assets"] == ("$11,062.18", "$41,914.42")
    assert by_label["max funds to close"] == ("$11,062.18", "$41,914.42")
    assert by_label["rate lock expiry"] == (None, "09/30/2026")
    assert by_label["UW team"] == ("Tigers", "Lightning")
    assert by_label["close by expiry"] == ("10/30/2026", "11/03/2026")
    assert by_label["asset expiry"] == ("10/30/2026", "11/30/2026")

    assert "verified income" not in by_label, "identical on both sheets, so not a change"
    assert "must not close before" not in by_label


# --------------------------------------------------------------------------- #
# §7.3 — round 3: came back, reworded, new
# --------------------------------------------------------------------------- #


async def test_round_three_separates_came_back_reworded_and_new(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    """§7.3's expected table, exactly.

    THE OLD `6378` IS IN THE PAIR AND NOWHERE ELSE, which is the subtle one. It is open, it came off
    a sheet, and round 3 does not carry its wording — so every rule for "probably cleared" fits it,
    and suggesting it would ask a processor to clear a condition the lender had just REWORDED. The
    pair is the question; clearing it is not.
    """
    loan_file, auth = await _file_with_codes(db_session)
    await _upload_and_import(
        client, auth, loan_file, db=db_session, enqueued=enqueued, fixture=UWM_ROUND_1
    )
    round_2 = await _upload_and_import(
        client, auth, loan_file, db=db_session, enqueued=enqueued, fixture=UWM_ROUND_2
    )

    # ROUND 2'S SUGGESTIONS ARE CONFIRMED FIRST, WHICH IS THE SCENARIO §7.3 DESCRIBES — and the step
    # the first version of this test left out. A suggestion is not a status: unconfirmed, those five
    # are still `open`, round 3 does not carry them either, and the comparison correctly suggested
    # them AGAIN. The engine was right and the test was telling a story with a missing step.
    round_2_row = await _round(db_session, round_2)
    suggested = [UUID(value) for value in round_2_row.comparison["probably_cleared"]]
    confirmed = await confirm_probably_cleared(
        db_session, round_=round_2_row, condition_ids=suggested
    )
    assert len(confirmed) == 5, "§7.2: confirming all 5 writes 5 verdicts sourced to round 2"

    round_3 = await _upload_and_import(
        client, auth, loan_file, db=db_session, enqueued=enqueued, fixture=UWM_ROUND_3
    )

    comparison = (await _round(db_session, round_3)).comparison
    assert await _codes(db_session, comparison["came_back"]) == ["1228"]
    assert await _codes(db_session, comparison["new"]) == ["7383"]
    assert await _codes(db_session, comparison["probably_cleared"]) == ["0006", "0007"]

    (pair,) = comparison["reworded"]
    old_code, new_code = await _codes(db_session, [pair[0]]), await _codes(db_session, [pair[1]])
    assert old_code == ["6378"] and new_code == ["6378"], "same code, different wording"
    assert pair[0] != pair[1], "two conditions, not one"

    # The old half is the pair's subject and nothing else's.
    assert pair[0] not in comparison["probably_cleared"]
    assert pair[0] not in comparison["still_open"]


# --------------------------------------------------------------------------- #
# When suggestions are withheld entirely
# --------------------------------------------------------------------------- #


async def test_a_partial_round_suggests_nothing_and_says_why(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    """ABSENCE IS EVIDENCE ONLY WHEN THE LIST CLAIMED TO BE COMPLETE (ADR-404).

    The sentence is S2-10's own, so the panel shows the server's words rather than composing its own.
    """
    loan_file, auth = await _file_with_codes(db_session)
    await _upload_and_import(
        client, auth, loan_file, db=db_session, enqueued=enqueued, fixture=UWM_ROUND_1
    )
    round_2 = await _upload_and_import(
        client,
        auth,
        loan_file,
        db=db_session,
        enqueued=enqueued,
        fixture=UWM_ROUND_2,
        completeness=ConditionRoundCompleteness.PARTIAL.value,
    )

    comparison = (await _round(db_session, round_2)).comparison
    assert comparison["probably_cleared"] == []
    assert comparison["no_suggestions_reason"] == (
        "This round was just some conditions, so nothing is suggested as cleared."
    )
    # THE OTHER OUTCOMES STILL RUN. A partial round produces New, Still open, Came back and
    # Reworded — only the suggestion is withheld.
    assert await _codes(db_session, comparison["still_open"]) != []


async def test_round_one_is_not_compared_against_nothing(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    """A comparison of the FIRST sheet would say "11 new, 0 still open" — true and useless, and it
    would dress the file's opening list up as a change."""
    loan_file, auth = await _file_with_codes(db_session)
    round_1 = await _upload_and_import(
        client, auth, loan_file, db=db_session, enqueued=enqueued, fixture=UWM_ROUND_1
    )

    assert (await _round(db_session, round_1)).comparison is None
