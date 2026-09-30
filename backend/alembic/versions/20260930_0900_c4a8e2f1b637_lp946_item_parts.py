"""LP-946 — items with more than one performer: `condition_items.part_of_item_id`.

An item several people act on is split into one item per destination (each outside performer's email, and
her task if she is one of them); each part links to the item it came from.

RAW SQL (ADR-037, LP-932). THE DOWNGRADE REFUSES while any part exists, rather than dropping the links.

Revision ID: c4a8e2f1b637
Revises: 7b2d4e61c9a8
Create Date: 2026-09-30 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4a8e2f1b637"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "7b2d4e61c9a8"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE condition_items ADD COLUMN part_of_item_id UUID")
    op.execute(
        "ALTER TABLE condition_items ADD CONSTRAINT fk_condition_items_part_of_item_id_condition_items "
        "FOREIGN KEY (part_of_item_id) REFERENCES condition_items (id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    present = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM condition_items WHERE part_of_item_id IS NOT NULL"))
        .scalar()
    )
    if present:
        raise RuntimeError(
            f"{present} item part(s) exist; downgrading would drop which item each came from, so it "
            "stops here."
        )
    op.execute(
        "ALTER TABLE condition_items DROP CONSTRAINT fk_condition_items_part_of_item_id_condition_items"
    )
    op.execute("ALTER TABLE condition_items DROP COLUMN part_of_item_id")
