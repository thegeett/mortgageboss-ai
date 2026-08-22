"""bug-001 — the stored ZIP+4 migration, exercised as SQL against a real database.

The parser fix only reaches files imported after it deploys: the snapshot reads
`properties.postal_code` from the table, not from the XML. So a file already imported keeps losing
its snapshot — all of it, since the at-rest guard's refusal is all-or-nothing — until this runs.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_UP = text(
    r"""
    UPDATE properties
       SET postal_code = substr(postal_code, 1, 5) || '-' || substr(postal_code, 6, 4)
     WHERE postal_code ~ '^\d{9}$'
    """
)


async def _codes(db: AsyncSession, loan_file_id) -> list[str | None]:
    rows = await db.execute(
        text("SELECT postal_code FROM properties WHERE loan_file_id = :lf ORDER BY postal_code"),
        {"lf": loan_file_id},
    )
    return [r[0] for r in rows]


async def test_the_real_value_is_hyphenated_and_the_others_are_untouched(
    db_session: AsyncSession,
) -> None:
    """`341203361` is the value from the file that lost both its snapshots. Everything else — a
    5-digit ZIP, an already-hyphenated ZIP+4, a non-US code, and NULL — must survive unchanged, so a
    normalization cannot corrupt an address it does not understand."""
    from tests.integration import factories

    company = await factories.make_company(db_session, slug="acme")
    # One property per loan file (a unique constraint), so each variant gets its own file.
    ids = []
    for code in ("341203361", "34120", "34120-3361", "SW1A 1AA", None):
        loan_file = await factories.make_loan_file(db_session, company=company)
        await db_session.flush()
        ids.append(loan_file.id)
        await db_session.execute(
            text(
                "INSERT INTO properties (id, loan_file_id, postal_code, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :lf, :code, now(), now())"
            ),
            {"lf": loan_file.id, "code": code},
        )
    await db_session.flush()

    await db_session.execute(_UP)

    after = set()
    for lf_id in ids:
        after |= set(await _codes(db_session, lf_id))
    assert "34120-3361" in after  # the 9-digit run became a ZIP+4...
    assert "341203361" not in after  # ...and no bare 9-digit run survives
    assert {"34120", "SW1A 1AA", None} <= after  # everything else untouched
    # Nothing became a shape that is neither: no double-hyphen, no bare run left anywhere.
    assert not any(c and c.count("-") > 1 for c in after)


async def test_running_it_twice_changes_nothing_the_second_time(db_session: AsyncSession) -> None:
    from tests.integration import factories

    company = await factories.make_company(db_session, slug="acme")
    loan_file = await factories.make_loan_file(db_session, company=company)
    await db_session.execute(
        text(
            "INSERT INTO properties (id, loan_file_id, postal_code, created_at, updated_at) "
            "VALUES (gen_random_uuid(), :lf, '341203361', now(), now())"
        ),
        {"lf": loan_file.id},
    )
    await db_session.flush()

    await db_session.execute(_UP)
    once = await _codes(db_session, loan_file.id)
    await db_session.execute(_UP)

    assert await _codes(db_session, loan_file.id) == once == ["34120-3361"]
