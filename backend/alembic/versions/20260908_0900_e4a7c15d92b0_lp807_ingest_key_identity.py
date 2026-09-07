"""LP-807: dedup inbound messages on ingest_key alone.

The index was ``(company_id, ingest_key) NULLS NOT DISTINCT``. That dedups correctly only while
nothing fills ``company_id`` — and LP-807 wires LP-805's routing into the ingest task, which fills
it. A redelivery then stopped colliding with the first copy (which had moved from ``(NULL, key)`` to
``(company, key)``), inserted a second row, and raised a UniqueViolation when routing tried to move
that one to the same place. SQS delivery is at-least-once, so this is the ordinary case, not an edge.

Reversible: the downgrade restores the composite index exactly as LP-803 created it, including
``NULLS NOT DISTINCT``, which is required for it to dedup unrouted rows at all.

Revision ID: e4a7c15d92b0
Revises: c9d3a71b8e52
Create Date: 2026-09-08 09:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e4a7c15d92b0"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "c9d3a71b8e52"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("uq_inbound_messages_ingest_key", table_name="inbound_messages")
    op.create_index(
        "uq_inbound_messages_ingest_key", "inbound_messages", ["ingest_key"], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_inbound_messages_ingest_key", table_name="inbound_messages")
    op.execute(
        "CREATE UNIQUE INDEX uq_inbound_messages_ingest_key "
        "ON inbound_messages (company_id, ingest_key) NULLS NOT DISTINCT"
    )
