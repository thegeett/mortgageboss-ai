"""LP-78.1 verifications.input_fingerprint (cross-source result caching)

Revision ID: a1c4e7b9f320
Revises: e3b9c2d4a187
Create Date: 2026-06-29 10:00:00.000000

Adds a nullable ``input_fingerprint`` (SHA-256 hex, 64 chars) to ``verifications``
(LP-78.1): a stable hash of the verification inputs (the stated + verified data the
cross-source pass compared), stored when a pass completes. A re-run whose current
inputs hash to the same value returns the cached findings without re-calling the AI.
Nullable — existing runs have no fingerprint (they re-run on the next trigger).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1c4e7b9f320"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "e3b9c2d4a187"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable input_fingerprint column."""
    op.add_column(
        "verifications",
        sa.Column("input_fingerprint", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    """Drop the input_fingerprint column."""
    op.drop_column("verifications", "input_fingerprint")
