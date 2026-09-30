"""LP-942 — a draft to the lender: `condition_drafts.recipient` gains `lender`.

Asks whose performer is the lender, and asks for the appraiser (which go through the lender), used to
reach no draft. RAW SQL (ADR-037, LP-932); THE CHECK SWAP LISTS EVERY VALUE: 9 recipients.

THE DOWNGRADE REFUSES while any lender draft exists, rather than deleting a draft she may have sent.

Revision ID: 7b2d4e61c9a8
Revises: 3c1e7a90d4b2
Create Date: 2026-09-29 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7b2d4e61c9a8"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "3c1e7a90d4b2"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CK = "ck_condition_drafts_draftrecipient"
_BEFORE = (
    "borrower",
    "title_attorney",
    "lo",
    "insurance",
    "hoa",
    "employer",
    "other_party",
    "underwriter",
)
_AFTER = (*_BEFORE, "lender")


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _swap(values: Sequence[str]) -> None:
    op.execute(f"ALTER TABLE condition_drafts DROP CONSTRAINT IF EXISTS {_CK}")
    op.execute(
        f"ALTER TABLE condition_drafts ADD CONSTRAINT {_CK} CHECK ({_in('recipient', values)})"
    )


def upgrade() -> None:
    _swap(_AFTER)


def downgrade() -> None:
    present = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM condition_drafts WHERE recipient = 'lender'"))
        .scalar()
    )
    if present:
        raise RuntimeError(
            f"{present} draft(s) to the lender exist; downgrading would have to delete them, so it "
            "stops here."
        )
    _swap(_BEFORE)
