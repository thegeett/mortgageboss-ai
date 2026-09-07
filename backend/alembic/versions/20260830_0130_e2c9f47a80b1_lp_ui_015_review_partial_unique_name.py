"""LP-UI-015 review - make the saved-view name constraint real

`uq_saved_views_owner_name` was a UNIQUE constraint over
``(owner_user_id, name, deleted_at)``. In Postgres a unique key containing a
NULL treats every such row as distinct, so two LIVE views — both with
``deleted_at`` NULL — never collided, and the constraint enforced nothing its
own comment claimed. Confirmed by inserting the duplicate before this ran.

A partial unique index over ``(owner_user_id, name) WHERE deleted_at IS NULL``
is what was meant: it forbids two live views of one name and still frees the
name when one is deleted. Same idiom as ``uq_findings_loan_file_rule_subject``.

Recreated under the SAME name, so nothing else has to learn a new one.

Revision ID: e2c9f47a80b1
Revises: d4b8e2f61a05
Create Date: 2026-08-30 01:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2c9f47a80b1"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "d4b8e2f61a05"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "uq_saved_views_owner_name"


def upgrade() -> None:
    """Swap the ineffective constraint for the partial index it should have been."""
    op.drop_constraint(_NAME, "saved_views", type_="unique")
    op.create_index(
        _NAME,
        "saved_views",
        ["owner_user_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    """Restore the constraint, ineffective as it was."""
    op.drop_index(_NAME, table_name="saved_views")
    op.create_unique_constraint(_NAME, "saved_views", ["owner_user_id", "name", "deleted_at"])
