"""LP-991 — the file address a draft's body was rendered with.

`communications.rendered_file_address`: NULL for a body that names no address (no domain, the
setting off, or a template that does not carry one). `refresh_if_stale` re-renders an unsent plain
draft when this differs from the file's address now, so a domain linked, changed or deactivated
after a draft was composed does not leave the old address (or no address) in it.

Not exposed by `readonly.communications`: excluded only to avoid rebuilding the view for a column no
query uses yet. No backfill: an existing draft reads as NULL, and a draft whose file now has an
address is re-rendered once on its next read, which is lossless for a plain draft.

Hand-written, like every migration against this schema.

Revision ID: 2d577c6ed90c
Revises: 6e1f6b5aa190
Create Date: 2026-10-26 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2d577c6ed90c"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "6e1f6b5aa190"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "communications", sa.Column("rendered_file_address", sa.String(length=256), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("communications", "rendered_file_address")
