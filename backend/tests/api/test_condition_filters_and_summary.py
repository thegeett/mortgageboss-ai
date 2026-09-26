"""The conditions read API: filters, sorts, the summary, one condition and its history (LP-911).

EVERY NUMBER HERE COMES FROM THE ROUND-1 FIXTURE, NOT FROM A HAND-BUILT ROW. `uwm_round1` is imported
through the real upload door, so the eleven conditions carry the codes, headings and owner hints the
reader and the code map actually produce. A fixture assembled with `make_condition` would let a filter
pass against rows shaped to suit it — and the one assertion this ticket is named for ("open + waiting
on borrower returns exactly 7086 6132 6637") is only worth anything if the owners were derived rather
than typed.

THE CODE MAP IS SEEDED THROUGH THE PRODUCT'S OWN PATH. `seed_lender_codes` is public and split from its
CLI precisely so a test can drive it, and it is what fills `default_owner_hint` — without it NINE of
the eleven conditions come back `unknown` (only `1947` and `6378` keep `title`, from the lender's own
`TC:` prefix, which the reader sets with no map at all). That failure would read as a broken filter
rather than as a fixture that seeded nothing, so `_seeded_uwm_file` asserts the rows landed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
import structlog
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from app.models.condition import Condition
from app.models.lender_condition_code import LenderCodeStatus, LenderConditionCode
from app.models.loan_file import LoanFile
from app.scripts.seed_lender_codes import seed_lender_codes
from app.services.conditions import MAX_CONDITIONS
from app.services.loan_files import create_loan_file
from app.tasks import conditions as task_module
from app.tasks.conditions import parse_round
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.fixture_helpers import UWM_ROUND_1, portal_excerpt
from tests.conditions.uwm_pdf_fixture import render_uwm_pdf
from tests.models.conftest_helpers import make_lender

API = "/api/v1"

#: Round 1's eleven codes, in the order the sheet prints them. The list, unsorted, must read this way.
ROUND_1_CODES = [
    "1228",
    "7086",
    "6132",
    "6637",
    "6178",
    "0132",
    "1947",
    "1582",
    "0006",
    "0007",
    "6378",
]


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


async def _company_user(db: AsyncSession, *, slug: str) -> tuple[Company, dict[str, str]]:
    company = Company(name=slug.title(), slug=f"{slug}-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=f"u-{uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("irrelevant"),
        first_name="Test",
        last_name="Processor",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return company, {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def _seeded_uwm_file(db: AsyncSession, company: Company) -> LoanFile:
    """A UWM file whose code map is seeded the way the application seeds it.

    `canonical_lender_key` IS THE WHOLE MECHANISM AND `make_lender` DOES NOT SET IT. `seed_lender_codes`
    matches lenders on that key alone (ADR-407: a slug is per-company and cannot identify "UWM"), so a
    fixture that omits it seeds nothing, reports the key unclaimed, and leaves every owner `unknown`.
    The assertion below is what makes that show up as a fixture error rather than as a filter that
    appears not to work.
    """
    loan_file = await create_loan_file(db, company_id=company.id)
    lender = await make_lender(db, company=company, name="UWM")
    lender.canonical_lender_key = "uwm"
    loan_file.lender_id = lender.id
    await db.flush()

    result = await seed_lender_codes(db)
    assert result.inserted > 0, "the UWM map must have seeded, or every owner hint below is unknown"
    assert "uwm" not in result.unclaimed_keys, "canonical_lender_key did not match"

    rows = (
        (
            await db.execute(
                select(LenderConditionCode).where(LenderConditionCode.lender_id == lender.id)
            )
        )
        .scalars()
        .all()
    )
    # SEEDED, NOT OBSERVED_UNMAPPED. `resolved_status` never demotes, and SEEDED is what makes
    # `unmapped_codes` come back empty on import — a hand-built row defaulting to OBSERVED_UNMAPPED
    # would change both quietly.
    assert rows and all(row.status is LenderCodeStatus.SEEDED for row in rows)
    return loan_file


async def _import_round_1(
    client: AsyncClient,
    auth: dict[str, str],
    loan_file: LoanFile,
    *,
    db: AsyncSession,
    enqueued: list[str],
) -> str:
    """Round 1 through the real upload door, parsed and imported. Returns the round id."""
    response = await client.post(
        f"{API}/loan-files/{loan_file.id}/condition-rounds/uploads",
        files={"file": ("round1.pdf", render_uwm_pdf(UWM_ROUND_1), "application/pdf")},
        headers=auth,
    )
    assert response.status_code == 202, response.text
    round_id = response.json()["id"]
    assert enqueued[-1] == round_id

    await parse_round(db, UUID(round_id))
    imported = await client.post(f"{API}/condition-rounds/{round_id}/import", headers=auth)
    assert imported.status_code == 200, imported.text
    assert imported.json()["created"] == 11
    return str(round_id)


@pytest.fixture
async def imported(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> tuple[LoanFile, dict[str, str], str]:
    """The state every test below reads: round 1 imported on a seeded UWM file."""
    company, auth = await _company_user(db_session, slug="read-api")
    loan_file = await _seeded_uwm_file(db_session, company)
    round_id = await _import_round_1(client, auth, loan_file, db=db_session, enqueued=enqueued)
    return loan_file, auth, round_id


async def _list(
    client: AsyncClient, auth: dict[str, str], loan_file: LoanFile, **params: Any
) -> list[dict[str, Any]]:
    response = await client.get(
        f"{API}/loan-files/{loan_file.id}/conditions", headers=auth, params=params
    )
    assert response.status_code == 200, response.text
    body: list[dict[str, Any]] = response.json()
    return body


def _codes(rows: list[dict[str, Any]]) -> list[str]:
    return [row["lender_code"] for row in rows]


# --------------------------------------------------------------------------- #
# The default response is Stage 1's, unchanged
# --------------------------------------------------------------------------- #


async def test_the_unfiltered_list_is_stage_ones_response_in_sheet_order(
    client: AsyncClient, imported: tuple[LoanFile, dict[str, str], str]
) -> None:
    """A DONE-WHEN, NOT A COURTESY. The Stage 1 imported list still reads this route, so a caller that
    passes no filters must get exactly what LP-909 served — in `sequence` order, which is the order
    the lender printed them."""
    loan_file, auth, _round_id = imported

    rows = await _list(client, auth, loan_file)

    assert _codes(rows) == ROUND_1_CODES
    assert all(row["round_numbers"] == [1] for row in rows)
    assert all(row["prep_status"] == "to_do" for row in rows)
    assert all(row["lender_status"] == "open" for row in rows)


async def test_every_row_carries_updated_at_so_lp912s_stale_guard_is_reachable(
    client: AsyncClient, imported: tuple[LoanFile, dict[str, str], str]
) -> None:
    """SURVEY D-3. LP-912's writes are optimistic on `updated_at`, and a client cannot echo a value it
    was never given — which is how LP-909 §4 found the draft's 409 could never fire. This is the
    assertion that keeps the field on the wire."""
    loan_file, auth, _round_id = imported

    rows = await _list(client, auth, loan_file)

    assert all(row["updated_at"] for row in rows)


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #


async def test_open_and_waiting_on_borrower_returns_exactly_the_three_asset_conditions(
    client: AsyncClient, imported: tuple[LoanFile, dict[str, str], str]
) -> None:
    """THE ASSERTION THIS TICKET IS NAMED FOR (spec §LP-911 Done-when).

    The three owners are DERIVED, not typed: `7086`, `6132` and `6637` carry
    `default_owner_hint: borrower` in the shipped UWM map, and nothing on the sheet says so. `6178` is
    `insurance` and `1947`/`6378` are `title` from the lender's own `TC:` prefix, which outranks the
    map — so this list is wrong the moment any of those three mechanisms breaks.
    """
    loan_file, auth, _round_id = imported

    rows = await _list(client, auth, loan_file, lender_status="open", owner="borrower")

    assert sorted(_codes(rows)) == sorted(["7086", "6132", "6637"])


async def test_an_unknown_owner_is_unknown_with_the_code_map_as_its_source(
    client: AsyncClient, imported: tuple[LoanFile, dict[str, str], str]
) -> None:
    """SURVEY D-6, AND A TRAP FOR LP-913. `1228` carries `default_owner_hint: unknown`, which the map
    DOES apply — so its source is `code_map`, not `none`. A screen that decided "Not known" from the
    source would render "Not known · from code map", which S2-01 does not draw."""
    loan_file, auth, _round_id = imported

    (row,) = await _list(client, auth, loan_file, lender_code="1228")

    assert row["effective_owner"] == "unknown"
    assert row["effective_owner_source"] == "code_map"


async def test_the_bucket_filter_splits_the_sheet_six_and_five(
    client: AsyncClient, imported: tuple[LoanFile, dict[str, str], str]
) -> None:
    """S2-01's two headline numbers. The 6 includes `0132`, whose heading "Compliance - Prior To
    Closing (PTD)" reads `prior_to_docs` from the parenthetical rather than from the words."""
    loan_file, auth, _round_id = imported

    docs = await _list(client, auth, loan_file, bucket_kind="prior_to_docs")
    funding = await _list(client, auth, loan_file, bucket_kind="prior_to_funding")

    assert len(docs) == 6
    assert "0132" in _codes(docs)
    assert len(funding) == 5


async def test_filters_combine_with_and(
    client: AsyncClient, imported: tuple[LoanFile, dict[str, str], str]
) -> None:
    """Two fields narrow; they do not widen. `prior_to_funding` has five rows and two of them are
    `title`, so the pair must return those two rather than either set."""
    loan_file, auth, _round_id = imported

    rows = await _list(client, auth, loan_file, bucket_kind="prior_to_funding", owner="title")

    assert sorted(_codes(rows)) == sorted(["1947", "6378"])


async def test_a_multi_valued_filter_is_an_or_within_itself(
    client: AsyncClient, imported: tuple[LoanFile, dict[str, str], str]
) -> None:
    """Repeated keys, which is the form FastAPI reads — and the reason the client must not serialise
    arrays with brackets."""
    loan_file, auth, _round_id = imported

    rows = await _list(client, auth, loan_file, owner=["title", "insurance"])

    assert sorted(_codes(rows)) == sorted(["1947", "6378", "6178"])


async def test_the_round_filter_answers_from_the_appearance_events(
    client: AsyncClient, imported: tuple[LoanFile, dict[str, str], str]
) -> None:
    """Round 1 carried all eleven, and round 2 does not exist here — so round 1 returns everything and
    round 2 returns nothing rather than erroring."""
    loan_file, auth, _round_id = imported

    assert len(await _list(client, auth, loan_file, round=1)) == 11
    assert await _list(client, auth, loan_file, round=2) == []


async def test_the_search_finds_the_wording_and_the_code(
    client: AsyncClient, imported: tuple[LoanFile, dict[str, str], str]
) -> None:
    """`q` searches both. "Earnest money" appears in `6637`'s wording only."""
    loan_file, auth, _round_id = imported

    by_words = await _list(client, auth, loan_file, q="earnest money")
    by_code = await _list(client, auth, loan_file, q="6132")

    assert _codes(by_words) == ["6637"]
    assert _codes(by_code) == ["6132"]


async def test_the_search_term_never_reaches_a_log_line(
    client: AsyncClient, imported: tuple[LoanFile, dict[str, str], str]
) -> None:
    """ADR-405 MADE A TEST RATHER THAN AN INTENTION. `q` searches `verbatim_text`, so the term is
    routinely a borrower's employer or an account ending. The read logs WHICH filters ran and how many
    rows came back, and never a value — so a log that grows a value fails here."""
    loan_file, auth, _round_id = imported
    # NAMED FOR WHAT IT IS: a search term standing in for NPI, not a credential. Called `secret` at
    # first, which `detect-secrets` flagged as a "Secret Keyword" — correctly, on the name. The repo
    # marks genuine false positives with `# pragma: allowlist secret`, and every one of those is a
    # VALUE that looks like a credential (a dummy key, a test password, a hash). This was a bad name
    # over a bank name lifted from the fixture's own wording, so it is renamed rather than allowlisted.
    npi_term = "Capital One"

    with structlog.testing.capture_logs() as logs:
        await _list(client, auth, loan_file, q=npi_term)

    listed = [entry for entry in logs if entry.get("event") == "conditions_listed"]
    assert listed, "the read must log that it ran, or this guard is checking nothing"
    # A THIRD ASSERTION STOOD HERE AND COULD NOT FAIL: `all(... or True for ...)`, which is true of
    # every input. Deleted rather than repaired, because the two below already state the property in
    # both directions — the value is absent from the WHOLE captured output, and the NAME is present.
    # LP-909's ticket file records this same shape four times; writing it into the file that guards
    # ADR-405 would have been the fifth.
    rendered = " ".join(str(value) for entry in logs for value in entry.values())
    assert npi_term.lower() not in rendered.lower(), "the search term reached a log line"
    assert "q" in listed[0]["filters"], "the filter NAME is what may be logged"


# --------------------------------------------------------------------------- #
# Sorts
# --------------------------------------------------------------------------- #


async def test_the_code_sort_orders_as_strings_keeping_leading_zeros(
    client: AsyncClient, imported: tuple[LoanFile, dict[str, str], str]
) -> None:
    """ADR-407. A code is an identifier printed on a document, so "0006" sorts before "1228" — and an
    int cast to "fix" the order would be the silent loss the column type refuses."""
    loan_file, auth, _round_id = imported

    rows = await _list(client, auth, loan_file, sort="code")

    assert _codes(rows) == sorted(ROUND_1_CODES)
    assert _codes(rows)[0] == "0006"


async def test_the_owner_sort_groups_the_owners(
    client: AsyncClient, imported: tuple[LoanFile, dict[str, str], str]
) -> None:
    """Each owner's rows are contiguous, which is what "group by waiting on" needs from the server."""
    loan_file, auth, _round_id = imported

    owners = [row["effective_owner"] for row in await _list(client, auth, loan_file, sort="owner")]

    runs = [owner for index, owner in enumerate(owners) if index == 0 or owner != owners[index - 1]]
    assert len(runs) == len(set(runs)), f"an owner appeared in two runs: {owners}"


# --------------------------------------------------------------------------- #
# The summary
# --------------------------------------------------------------------------- #


async def test_the_summary_is_s2_01s_seven_numbers(
    client: AsyncClient, imported: tuple[LoanFile, dict[str, str], str]
) -> None:
    """Screen S2-01, from the fixture rather than from a mock.

    `information 0` IS NOT LUCK: the only `info_only` row in the shipped UWM map is `0973`, which
    appears on neither sheet. If a later map marked one of round 1's codes information-only, this
    number and `open` would both move, which is exactly what it should catch.
    """
    loan_file, auth, _round_id = imported

    response = await client.get(f"{API}/loan-files/{loan_file.id}/conditions/summary", headers=auth)

    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["total"] == 11
    assert summary["open"] == 11
    assert summary["cleared"] == 0
    assert summary["waived"] == 0
    assert summary["not_cleared"] == 0
    assert summary["superseded"] == 0
    assert summary["info_only"] == 0
    assert summary["open_prior_to_docs"] == 6
    assert summary["open_prior_to_funding"] == 5
    assert summary["by_prep_status"] == {"to_do": 11}
    assert summary["by_owner"]["borrower"] == 3
    #: 0 until LP-915 produces one — asserted so the field cannot start reading as measured.
    assert summary["pending_suggestions"] == 0
    assert summary["latest_round"]["round_number"] == 1


# --------------------------------------------------------------------------- #
# One condition, and its history
# --------------------------------------------------------------------------- #


async def _one_condition(db: AsyncSession, loan_file: LoanFile, code: str) -> Condition:
    condition = await db.scalar(
        select(Condition).where(
            Condition.loan_file_id == loan_file.id, Condition.lender_code == code
        )
    )
    assert condition is not None
    return condition


async def test_one_condition_comes_back_with_every_round_and_whether_it_was_on_it(
    client: AsyncClient, db_session: AsyncSession, imported: tuple[LoanFile, dict[str, str], str]
) -> None:
    """Screen S2-03's Rounds pills. Round 1 carried `6132`, so it is on the sheet."""
    loan_file, auth, round_id = imported
    condition = await _one_condition(db_session, loan_file, "6132")

    response = await client.get(f"{API}/conditions/{condition.id}", headers=auth)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["lender_code"] == "6132"
    # The row's own fields are here too: the sheet extends the row so the two cannot disagree.
    assert body["prep_status"] == "to_do"
    (appearance,) = body["rounds"]
    assert appearance["round_id"] == round_id
    assert appearance["round_number"] == 1
    assert appearance["on_sheet"] is True
    assert appearance["completeness"] == "full"
    # `6132` carries the sheet's dated note, and it arrived in THIS round.
    assert appearance["note"]["text"]


async def test_a_first_import_writes_only_created_even_for_a_condition_with_a_note(
    client: AsyncClient, db_session: AsyncSession, imported: tuple[LoanFile, dict[str, str], str]
) -> None:
    """A NOTE CHIP DOES NOT IMPLY A `CONDITION_NOTE_ADDED` EVENT, and the first version of the test
    below assumed it did.

    `6132` carries the sheet's dated note "8/28 Not in Upload", and it is stored by
    `_create_condition` as part of the row — `underwriter_notes=_notes_from_row(...)` — so the note
    ARRIVED WITH the condition rather than being added to it. `CONDITION_NOTE_ADDED` is written only on
    the seen-again path, where `_new_notes` finds a note the saved condition did not already have.

    Worth pinning rather than just fixing: LP-912 wires A1 (came back) to that same "new note"
    decision, so anything reasoning from "this condition has a note" to "a note event exists" would be
    wrong in the direction that reopens conditions.
    """
    loan_file, auth, _round_id = imported
    condition = await _one_condition(db_session, loan_file, "6132")

    response = await client.get(f"{API}/conditions/{condition.id}/events", headers=auth)

    assert response.status_code == 200, response.text
    assert [event["kind"] for event in response.json()] == ["condition_created"]
    # The note is on the condition all the same — it simply came with it.
    detail = await client.get(f"{API}/conditions/{condition.id}", headers=auth)
    assert detail.json()["latest_note"]["text"]


async def test_one_conditions_history_is_its_own_events_newest_first(
    client: AsyncClient, db_session: AsyncSession, imported: tuple[LoanFile, dict[str, str], str]
) -> None:
    """THE READER `ix_condition_events_condition_occurred` HAS LACKED SINCE LP-904, which that index's
    own comment and LP-909 both flagged as unjustified until something asked the question.

    TWO IMPORTS, BECAUSE ONE EVENT CANNOT DEMONSTRATE AN ORDER. This test is named for "newest first",
    and a single-event history is true of that ordering and of its opposite — the shape LP-909's ticket
    file records four times and which the first version of this test had. `1228` is on round 1 and on
    round 2's portal excerpt, so it genuinely has two events: created, then seen again.
    """
    loan_file, auth, _round_id = imported

    pasted = await client.post(
        f"{API}/loan-files/{loan_file.id}/condition-rounds/paste",
        json={"text": portal_excerpt(), "completeness": "partial"},
        headers=auth,
    )
    assert pasted.status_code == 201, pasted.text
    second = await client.post(f"{API}/condition-rounds/{pasted.json()['id']}/import", headers=auth)
    assert second.status_code == 200, second.text
    assert second.json()["seen_again"] == 6

    condition = await _one_condition(db_session, loan_file, "1228")
    response = await client.get(f"{API}/conditions/{condition.id}/events", headers=auth)

    assert response.status_code == 200, response.text
    kinds = [event["kind"] for event in response.json()]
    assert kinds == ["condition_seen_again", "condition_created"], "newest first"
    # Round-level events belong to the ROUND's history, not to one condition's — the opposite filter
    # from `events_for_round`, which excludes per-condition rows.
    assert "round_imported" not in kinds


# --------------------------------------------------------------------------- #
# Tenancy
# --------------------------------------------------------------------------- #


async def test_another_company_gets_404_on_every_new_route(
    client: AsyncClient, db_session: AsyncSession, imported: tuple[LoanFile, dict[str, str], str]
) -> None:
    """404 AND NEVER 403: confirming an id exists would be an oracle over another tenant's rows.

    The gating walk proves the dependency is DECLARED on the new router; this proves it refuses. Both
    are needed — LP-909's own gating test says a declared gate is still a check that can be forgotten,
    and a gate that is declared and does not refuse would pass that walk.
    """
    loan_file, _auth, _round_id = imported
    condition = await _one_condition(db_session, loan_file, "6132")
    _other, stranger = await _company_user(db_session, slug="read-stranger")

    for path in (
        f"/loan-files/{loan_file.id}/conditions",
        f"/loan-files/{loan_file.id}/conditions/summary",
        f"/conditions/{condition.id}",
        f"/conditions/{condition.id}/events",
    ):
        response = await client.get(f"{API}{path}", headers=stranger)
        assert response.status_code == 404, (path, response.status_code)


# --------------------------------------------------------------------------- #
# The cap
# --------------------------------------------------------------------------- #


async def test_the_cap_is_reported_rather_than_truncating_in_silence(
    client: AsyncClient, db_session: AsyncSession, imported: tuple[LoanFile, dict[str, str], str]
) -> None:
    """A list that quietly stops is indistinguishable from a file with nothing more to show.

    Built by copying one condition past the cap rather than importing a vast sheet: the property under
    test is the cap, not the reader.
    """
    loan_file, auth, _round_id = imported
    original = await _one_condition(db_session, loan_file, "6132")

    for index in range(MAX_CONDITIONS):
        db_session.add(
            Condition(
                company_id=original.company_id,
                loan_file_id=original.loan_file_id,
                lender_id=original.lender_id,
                first_round_id=original.first_round_id,
                last_seen_round_id=original.last_seen_round_id,
                sequence=100 + index,
                lender_code=None,
                bucket_heading=original.bucket_heading,
                bucket_kind=original.bucket_kind,
                verbatim_text=f"Filler {index}.",
                text_fingerprint=f"{index:064d}",
                underwriter_notes=[],
            )
        )
    await db_session.flush()

    response = await client.get(f"{API}/loan-files/{loan_file.id}/conditions", headers=auth)

    assert response.status_code == 200, response.text
    assert len(response.json()) == MAX_CONDITIONS
    assert response.headers.get("X-Conditions-Capped") == "true"
