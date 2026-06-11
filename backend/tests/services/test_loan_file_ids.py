"""Tests for loan file identifier generation (LP-13, ADR-036).

These exercise the **security-sensitive core** of the loan file model: the
display ID and inbox token generators. The properties asserted here map
directly to ADR-036:

  - Display IDs use only the unambiguous alphabet (no 0/O/1/I/L).
  - Inbox tokens are long, high-entropy, and unique across many generations.
  - The inbox token is generated INDEPENDENTLY of the display ID (a token is
    never derived from or correlated with the display ID).
  - Collision-checked display ID generation regenerates on collision and
    raises after a bounded number of attempts.

The collision tests mock the database: ``generate_unique_display_id`` queries
``LoanFile`` (whose model/table arrive in a later stage), so the retry/guard
logic is verified in isolation here, and end-to-end uniqueness is covered by
the model tests.
"""

import sys
import types
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.services import loan_file_ids
from app.services.loan_file_ids import (
    DISPLAY_ALPHABET,
    DISPLAY_PREFIX,
    MAX_DISPLAY_ID_ATTEMPTS,
    generate_display_id,
    generate_inbox_token,
    generate_unique_display_id,
)

# Characters ADR-036 deliberately excludes to avoid spoken/typed confusion.
AMBIGUOUS_CHARS = set("0O1IL")


@pytest.fixture
def stub_loan_file_model(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Provide a stand-in ``app.models.loan_file.LoanFile`` for the unit tests.

    ``generate_unique_display_id`` lazily imports ``LoanFile`` to build its
    lookup query. These tests mock the database and the ``select`` call, so the
    real mapped model is unnecessary — a trivial stub satisfies the import
    without coupling the ID-generation unit tests to the model/table. The
    ``monkeypatch.setitem`` is reverted automatically, so a real
    ``app.models.loan_file`` (once it exists) is unaffected.
    """
    module = types.ModuleType("app.models.loan_file")
    module.LoanFile = MagicMock(name="LoanFile")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.models.loan_file", module)
    yield


def test_display_id_format() -> None:
    """A display ID is the 'LF-' prefix followed by 4 alphabet characters."""
    display_id = generate_display_id()
    assert display_id.startswith(DISPLAY_PREFIX)
    code = display_id.removeprefix(DISPLAY_PREFIX)
    assert len(code) == 4
    assert all(char in DISPLAY_ALPHABET for char in code)


def test_display_id_has_no_ambiguous_characters() -> None:
    """No display ID ever contains 0, O, 1, I, or L (ADR-036 alphabet)."""
    # Generate many to make the assertion meaningful, not just lucky.
    for _ in range(2000):
        code = generate_display_id().removeprefix(DISPLAY_PREFIX)
        assert not (set(code) & AMBIGUOUS_CHARS), f"ambiguous char in {code!r}"


def test_display_alphabet_excludes_ambiguous_characters() -> None:
    """The alphabet constant itself excludes the ambiguous characters."""
    assert not (set(DISPLAY_ALPHABET) & AMBIGUOUS_CHARS)


def test_inbox_token_is_sufficiently_long() -> None:
    """The inbox token is long enough to be infeasible to guess/enumerate."""
    token = generate_inbox_token()
    # token_urlsafe(12) yields ~16 url-safe chars (~96 bits of entropy).
    assert len(token) >= 16
    # url-safe base64 alphabet only.
    assert all(char.isalnum() or char in "-_" for char in token)


def test_inbox_tokens_are_unique_across_many_generations() -> None:
    """1000 tokens are all distinct (statistical uniqueness at ~96 bits)."""
    tokens = {generate_inbox_token() for _ in range(1000)}
    assert len(tokens) == 1000


def test_display_ids_are_well_distributed() -> None:
    """Display IDs are random, not sequential: many generations vary widely."""
    ids = {generate_display_id() for _ in range(1000)}
    # With 31**4 (~924k) codes, 1000 draws should almost never collide; allow a
    # tiny margin so the test is not flaky on the rare birthday collision.
    assert len(ids) >= 995


def test_inbox_token_is_independent_of_display_id() -> None:
    """The inbox token is NOT derived from the display ID (ADR-036).

    Generate many (display_id, inbox_token) pairs and confirm there is no
    relationship: the token never contains the display ID or its random code,
    and identical display codes do not yield identical tokens. The tokens are
    simply independent random values.
    """
    seen_codes: dict[str, str] = {}
    collision_found = False
    for _ in range(1000):
        display_id = generate_display_id()
        token = generate_inbox_token()
        code = display_id.removeprefix(DISPLAY_PREFIX)

        # The token must not encode the display id in any obvious way.
        assert display_id not in token
        assert code not in token

        # If the same 4-char display code recurs (birthday collisions happen),
        # the token must still differ — proving the token is not a function of
        # the display id.
        if code in seen_codes:
            collision_found = True
            assert seen_codes[code] != token
        seen_codes[code] = token

    # Not required for correctness, but make the independence check meaningful:
    # at 1000 draws over 31**4 codes, recurrence is plausible but not certain,
    # so we don't assert it occurred — the per-iteration checks stand on their own.
    _ = collision_found


async def test_generate_unique_display_id_returns_free_candidate(
    monkeypatch: pytest.MonkeyPatch,
    stub_loan_file_model: None,
) -> None:
    """When the first candidate is unused, it is returned as-is."""
    monkeypatch.setattr(loan_file_ids, "select", MagicMock())
    monkeypatch.setattr(loan_file_ids, "generate_display_id", lambda: "LF-2345")

    db = MagicMock()
    db.scalar = AsyncMock(return_value=None)  # nothing exists -> free

    result = await generate_unique_display_id(db)

    assert result == "LF-2345"
    db.scalar.assert_awaited_once()


async def test_generate_unique_display_id_regenerates_on_collision(
    monkeypatch: pytest.MonkeyPatch,
    stub_loan_file_model: None,
) -> None:
    """A collision on the first candidate triggers regeneration of a new one."""
    # ``select`` is mocked away so we never touch the (not-yet-existing) model.
    monkeypatch.setattr(loan_file_ids, "select", MagicMock())
    candidates = iter(["LF-AAAA", "LF-BBBB"])
    monkeypatch.setattr(loan_file_ids, "generate_display_id", lambda: next(candidates))

    db = MagicMock()
    # First lookup finds an existing row (collision), second finds nothing.
    db.scalar = AsyncMock(side_effect=[uuid4(), None])

    result = await generate_unique_display_id(db)

    assert result == "LF-BBBB"
    assert db.scalar.await_count == 2


async def test_generate_unique_display_id_raises_after_max_attempts(
    monkeypatch: pytest.MonkeyPatch,
    stub_loan_file_model: None,
) -> None:
    """If every candidate collides, the guard raises after MAX attempts."""
    monkeypatch.setattr(loan_file_ids, "select", MagicMock())
    monkeypatch.setattr(loan_file_ids, "generate_display_id", lambda: "LF-AAAA")

    db = MagicMock()
    db.scalar = AsyncMock(return_value=uuid4())  # always collides

    with pytest.raises(RuntimeError, match="unique display ID"):
        await generate_unique_display_id(db)

    assert db.scalar.await_count == MAX_DISPLAY_ID_ATTEMPTS
