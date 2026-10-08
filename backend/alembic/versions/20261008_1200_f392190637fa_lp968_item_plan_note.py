"""LP-968 — `condition_items.plan_note`: her words on a change she made to the plan.

Why a task is not needed, how she knows it is already done, or how she is doing it herself. Nullable, no
backfill: no existing task carries one.

NOT IN THE READONLY VIEW. `readonly.condition_items` lists its columns explicitly (LP-956), so a new column
stays out of it; this one is free text, like `name`, which the view also leaves out.

Revision ID: f392190637fa
Revises: 0915cdf12565
Create Date: 2026-10-08 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f392190637fa"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "0915cdf12565"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("condition_items", sa.Column("plan_note", sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column("condition_items", "plan_note")
