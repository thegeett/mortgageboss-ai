"""User preference endpoint tests (LP-79, LP-UI-010).

The behaviour worth pinning is the PARTIAL update. LP-UI-010 made both fields
optional so that "only the provided fields change" is true; before that a client
changing density alone had to send back a thoroughness it was not changing, and
a stale copy would have silently overwritten the real value. That is a data-loss
shape, and nothing was asserting it.
"""

from collections.abc import AsyncIterator

import pytest_asyncio
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from app.models.user import RowDensity
from app.verification.confidence import AggressionLevel
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

PREFS = "/api/v1/users/me/preferences"


@pytest_asyncio.fixture
async def db(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    connection = await test_engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


async def _user_and_token(db: AsyncSession, *, email: str = "u@acme.com") -> tuple[User, str]:
    company = Company(name="Acme", slug="acme")
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=email,
        hashed_password=hash_password("irrelevant"),  # pragma: allowlist secret
        first_name="Test",
        last_name="User",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    await db.commit()
    return user, create_access_token(user.id)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_get_returns_both_preferences_at_their_defaults(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A user who has never set anything reads back the model defaults."""
    _user, token = await _user_and_token(db)

    body = (await client.get(PREFS, headers=_auth(token))).json()

    assert body["default_aggression_level"] == AggressionLevel.BALANCED.value
    assert body["density"] == RowDensity.COMPACT.value


async def test_setting_density_alone_leaves_thoroughness_untouched(
    client: AsyncClient, db: AsyncSession
) -> None:
    """The reason both fields became optional — a density-only PUT must not reset the dial."""
    _user, token = await _user_and_token(db)
    await client.put(PREFS, headers=_auth(token), json={"default_aggression_level": "thorough"})

    put = await client.put(PREFS, headers=_auth(token), json={"density": "relaxed"})

    assert put.status_code == 200
    assert put.json()["density"] == "relaxed"
    # The field the client never mentioned. Required-and-echoed-back is how a
    # stale client value silently reverts a preference set on another device.
    assert put.json()["default_aggression_level"] == "thorough"
    assert (await client.get(PREFS, headers=_auth(token))).json()[
        "default_aggression_level"
    ] == "thorough"


async def test_setting_thoroughness_alone_leaves_density_untouched(
    client: AsyncClient, db: AsyncSession
) -> None:
    """The same guarantee in the other direction — the dial is the older caller."""
    _user, token = await _user_and_token(db)
    await client.put(PREFS, headers=_auth(token), json={"density": "comfortable"})

    put = await client.put(
        PREFS, headers=_auth(token), json={"default_aggression_level": "conservative"}
    )

    assert put.status_code == 200
    assert put.json()["default_aggression_level"] == "conservative"
    assert put.json()["density"] == "comfortable"


async def test_both_fields_together_still_work(client: AsyncClient, db: AsyncSession) -> None:
    _user, token = await _user_and_token(db)

    put = await client.put(
        PREFS,
        headers=_auth(token),
        json={"default_aggression_level": "thorough", "density": "relaxed"},
    )

    assert put.status_code == 200
    # LP-UI-030 added the reviewer split. Kept as an EXACT comparison rather than
    # a subset check: this endpoint returns a user's stored preferences, and a
    # field appearing in it unnoticed is the thing exact equality is for.
    assert put.json() == {
        "default_aggression_level": "thorough",
        "density": "relaxed",
        "reviewer_pane_split": None,
        # LP-855 adds three: the stored answer, and the suggestion served beside it. Extended
        # deliberately rather than loosened to a subset check — this assertion exists to notice
        # exactly this, and it did.
        "mail_client": None,
        "suggested_mail_client": "mailto",
        "mail_client_suggestion_reason": "",
    }


async def test_an_empty_body_changes_nothing(client: AsyncClient, db: AsyncSession) -> None:
    """Accepted rather than rejected: "only the provided fields change" and nothing was."""
    _user, token = await _user_and_token(db)
    await client.put(PREFS, headers=_auth(token), json={"density": "relaxed"})

    put = await client.put(PREFS, headers=_auth(token), json={})

    assert put.status_code == 200
    assert put.json()["density"] == "relaxed"


async def test_an_unknown_density_is_rejected(client: AsyncClient, db: AsyncSession) -> None:
    """The enum is bounded at the edge, not only by the column's CHECK constraint."""
    _user, token = await _user_and_token(db)

    put = await client.put(PREFS, headers=_auth(token), json={"density": "gigantic"})

    assert put.status_code == 422
    assert (await client.get(PREFS, headers=_auth(token))).json()["density"] == "compact"


async def test_an_explicit_null_does_not_clear_a_field(
    client: AsyncClient, db: AsyncSession
) -> None:
    """`None` means "not sent", so a client that spells it explicitly cannot wipe a value.

    Worth pinning: the endpoint distinguishes present-from-absent with `is not None`,
    so an explicit null is indistinguishable from omission — deliberate, since
    neither preference has a meaningful "unset" state to return to.
    """
    _user, token = await _user_and_token(db)
    await client.put(PREFS, headers=_auth(token), json={"density": "relaxed"})

    put = await client.put(PREFS, headers=_auth(token), json={"density": None})

    assert put.status_code == 200
    assert put.json()["density"] == "relaxed"


# --------------------------------------------------------------------------- #
# The reviewer pane split (LP-UI-030)
# --------------------------------------------------------------------------- #


async def test_reviewer_split_round_trips(client: AsyncClient, db: AsyncSession) -> None:
    _user, token = await _user_and_token(db)
    put = await client.put(
        PREFS,
        headers=_auth(token),
        json={"reviewer_pane_split": [22, 53]},
    )
    assert put.status_code == 200
    assert put.json()["reviewer_pane_split"] == [22, 53]

    got = await client.get(PREFS, headers=_auth(token))
    assert got.json()["reviewer_pane_split"] == [22, 53]


async def test_never_adjusted_is_null_not_a_default(client: AsyncClient, db: AsyncSession) -> None:
    # NULL and "adjusted back to the default" are different facts. The UI shows
    # its own default for NULL rather than writing one nobody chose.
    _user, token = await _user_and_token(db)
    got = await client.get(PREFS, headers=_auth(token))
    assert got.json()["reviewer_pane_split"] is None


async def test_a_split_that_hides_a_pane_is_rejected(client: AsyncClient, db: AsyncSession) -> None:
    """The value is JSON and it SURVIVES to the next session.

    A client persisting `[90, 5]` gives itself a layout with a pane it cannot
    reach, and a bad write is not a refresh away from being fixed — which is why
    this is validated at the boundary rather than clamped in the browser.
    """
    _user, token = await _user_and_token(db)
    for bad in ([90, 5], [5, 20], [50, 50], [40], [10, 20, 30]):
        put = await client.put(PREFS, headers=_auth(token), json={"reviewer_pane_split": bad})
        assert put.status_code == 422, f"{bad} should be rejected"


async def test_setting_the_split_leaves_other_preferences_alone(
    client: AsyncClient, db: AsyncSession
) -> None:
    _user, token = await _user_and_token(db)
    await client.put(PREFS, headers=_auth(token), json={"density": "relaxed"})
    await client.put(PREFS, headers=_auth(token), json={"reviewer_pane_split": [25, 50]})
    got = await client.get(PREFS, headers=_auth(token))
    assert got.json()["density"] == "relaxed"
    assert got.json()["reviewer_pane_split"] == [25, 50]


# --------------------------------------------------------------------------------------------- #
# LP-855 — where this processor writes their email
# --------------------------------------------------------------------------------------------- #
async def test_nobody_has_been_asked_reads_back_as_null(
    client: AsyncClient, db: AsyncSession
) -> None:
    """NULL IS A REAL ANSWER HERE, unlike every other preference on this table.

    The others default to the value the product would use anyway, because "never chosen" and "chose
    the default" are the same thing for them. They are not the same thing for this one: `mailto` is
    both the safe answer AND what "Not now" selects, so a default would make "nobody has been asked"
    indistinguishable from "they picked the desktop default" — and the picker would then either
    never appear or appear forever.
    """
    _user, token = await _user_and_token(db)

    body = (await client.get(PREFS, headers=_auth(token))).json()

    assert body["mail_client"] is None


async def test_the_suggestion_is_served_and_never_applied(
    client: AsyncClient, db: AsyncSession
) -> None:
    """IT MOVES A RADIO BUTTON AND SAYS WHY. IT NEVER DECIDES.

    A guess that applied itself would open the wrong compose window with nothing on screen
    explaining it, and the processor would have to work out that we had chosen for them. So the
    suggestion travels BESIDE the stored value, and the stored value is still null.
    """
    _user, token = await _user_and_token(db, email="priya@gmail.com")

    body = (await client.get(PREFS, headers=_auth(token))).json()

    assert body["suggested_mail_client"] == "gmail"
    assert body["mail_client_suggestion_reason"] == "you sign in as priya@gmail.com"
    assert body["mail_client"] is None, "the suggestion was applied"


async def test_a_domain_that_says_nothing_suggests_the_safe_answer_and_no_reason(
    client: AsyncClient, db: AsyncSession
) -> None:
    """THE COMMON CASE. A processor at a mortgage company signs in as `@theirfirm.com`, which is
    consistent with Gmail, Outlook, Apple Mail and a locally installed Outlook alike. Suggesting one
    of them on no evidence would be a coin flip wearing a recommendation's clothes — and
    "suggested because we could not tell" is not a reason anybody benefits from reading.
    """
    _user, token = await _user_and_token(db, email="priya@acmemortgage.com")

    body = (await client.get(PREFS, headers=_auth(token))).json()

    assert body["suggested_mail_client"] == "mailto"
    assert body["mail_client_suggestion_reason"] == ""


async def test_a_lookalike_domain_is_not_mistaken_for_a_tenant(
    client: AsyncClient, db: AsyncSession
) -> None:
    """EXACT DOMAINS, NOT SUBSTRINGS. An `"outlook" in domain` test matches
    `outlook-consulting.com`, which is a brokerage rather than a Microsoft tenant — and the
    suggestion would then be wrong in a way that looks authoritative."""
    _user, token = await _user_and_token(db, email="p@outlook-consulting.com")

    body = (await client.get(PREFS, headers=_auth(token))).json()

    assert body["suggested_mail_client"] == "mailto"


async def test_the_answer_persists_and_is_changeable(client: AsyncClient, db: AsyncSession) -> None:
    """ACCEPTANCE 4. Per USER, so it survives a reload, a different file and a different machine."""
    _user, token = await _user_and_token(db)

    saved = await client.put(PREFS, headers=_auth(token), json={"mail_client": "gmail"})
    assert saved.status_code == 200
    assert saved.json()["mail_client"] == "gmail"
    assert (await client.get(PREFS, headers=_auth(token))).json()["mail_client"] == "gmail"

    # CHANGEABLE — "you can change this any time in settings" is the picker's own promise.
    changed = await client.put(PREFS, headers=_auth(token), json={"mail_client": "outlook_work"})
    assert changed.json()["mail_client"] == "outlook_work"


async def test_setting_the_mail_client_leaves_the_other_preferences_alone(
    client: AsyncClient, db: AsyncSession
) -> None:
    """The partial-update property this file exists for, extended to the new field."""
    _user, token = await _user_and_token(db)
    await client.put(PREFS, headers=_auth(token), json={"density": "relaxed"})

    await client.put(PREFS, headers=_auth(token), json={"mail_client": "gmail"})

    body = (await client.get(PREFS, headers=_auth(token))).json()
    assert body["density"] == "relaxed"
    assert body["mail_client"] == "gmail"


async def test_an_unknown_mail_client_is_rejected(client: AsyncClient, db: AsyncSession) -> None:
    """A value outside the enum would be stored and then read back by a client that has no route
    for it — the button would say "Copy & open undefined"."""
    _user, token = await _user_and_token(db)

    refused = await client.put(PREFS, headers=_auth(token), json={"mail_client": "carrier_pigeon"})

    assert refused.status_code == 422
    assert (await client.get(PREFS, headers=_auth(token))).json()["mail_client"] is None
