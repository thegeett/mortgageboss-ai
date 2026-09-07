"""Loan file identifier generation (per ADR-036).

A loan file has three identifiers:
  1. UUID primary key (internal) — from UUIDMixin, not generated here.
  2. Display ID (LF-XXXX) — non-sequential readable code for human reference.
  3. Inbox token — cryptographically unguessable token for the borrower
     email address (a capability: possession grants the ability to send
     documents into the file).

Security notes:
  - Both the display ID's random characters and the inbox token use the
    ``secrets`` module (cryptographically secure), NEVER ``random``.
  - The inbox token is generated INDEPENDENTLY of the display ID. It is
    never derived from the display ID or any other predictable value.
"""

import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Unambiguous alphabet: no 0/O, no 1/I/L, to avoid confusion when spoken/typed.
DISPLAY_ALPHABET = (
    "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # pragma: allowlist secret  (alphabet, not a secret)
)
DISPLAY_CODE_LENGTH = 4
DISPLAY_PREFIX = "LF-"

# LP-802 — 16, not 12: token_urlsafe(16) -> 22 chars, 128 bits. Widened while it is free. The token is
# a bearer capability (anyone holding the address can post documents into the file), it is printed in
# an email address that gets forwarded and quoted, and it has no expiry — so its entropy is the whole
# of its security. Existing tokens keep working; the column is String(64) and needs no migration.
INBOX_TOKEN_BYTES = 16

MAX_DISPLAY_ID_ATTEMPTS = 10


def generate_display_id() -> str:
    """Generate a non-sequential readable display ID, e.g. ``'LF-7K3M'``.

    Uses :func:`secrets.choice` over an unambiguous alphabet. Not
    collision-checked here — see :func:`generate_unique_display_id` for
    DB-checked generation.
    """
    code = "".join(secrets.choice(DISPLAY_ALPHABET) for _ in range(DISPLAY_CODE_LENGTH))
    return f"{DISPLAY_PREFIX}{code}"


def generate_inbox_token() -> str:
    """Generate a cryptographically unguessable inbox token.

    Used to construct the borrower inbox email address. Must be infeasible
    to guess or enumerate. Generated independently of the display ID.
    """
    return secrets.token_urlsafe(INBOX_TOKEN_BYTES)


async def generate_unique_display_id(db: AsyncSession) -> str:
    """Generate a display ID guaranteed unique against existing loan files.

    Display IDs are globally unique (ADR-048). Collisions are rare
    (31**4 ~ 924k codes) but possible, so we check and regenerate. The unique
    DB constraint on ``display_id`` is the final safety net.

    Raises:
        RuntimeError: if a unique candidate is not found within
            :data:`MAX_DISPLAY_ID_ATTEMPTS` attempts.
    """
    # Imported here to avoid a circular import at module load.
    from app.models.loan_file import LoanFile

    for _ in range(MAX_DISPLAY_ID_ATTEMPTS):
        candidate = generate_display_id()
        existing = await db.scalar(select(LoanFile.id).where(LoanFile.display_id == candidate))
        if existing is None:
            return candidate
    raise RuntimeError(
        f"Could not generate a unique display ID after {MAX_DISPLAY_ID_ATTEMPTS} attempts"
    )
