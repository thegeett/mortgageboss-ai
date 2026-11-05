"""LP-1008 — `inbound_messages.envelope_recipients`: where SES actually delivered the mail.

Routing reads only this (loan-email.md rule 7), never To/Cc. Existing rows get `[]`.

Not in `readonly.inbound_messages`: these are addresses, and `to_addresses` is excluded too. The view
lists its columns by name, so it does not change.

Revision ID: c4f7a92e1b36
Revises: 5c8e1a7d3b92
Create Date: 2026-11-04 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4f7a92e1b36"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "5c8e1a7d3b92"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "inbound_messages",
        sa.Column(
            "envelope_recipients",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("inbound_messages", "envelope_recipients")
