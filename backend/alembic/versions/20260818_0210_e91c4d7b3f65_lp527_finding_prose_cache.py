"""LP-527 — the finding-prose cache.

A pure CACHE, keyed by a hash of the fact summary a composition was made from. Identical facts give the
identical key and therefore the identical sentence, without a second model call.

⚠️ THE POINT IS DETERMINISM MORE THAN COST. Without this the same unchanged problem is worded
differently on every run: a processor re-reads a finding thinking something changed, and any cross-run
diff of the queue becomes noise. Cost is a secondary benefit — a re-run of an unchanged file makes no
composition calls at all.

Deliberately NOT tied to a finding: no foreign key, no loan_file_id, no run id. A row is a pure
function of its key, so the table can be truncated at any time with no loss beyond a re-generation, and
two files whose facts coincide share a sentence rather than paying twice.

Revision ID: e91c4d7b3f65
Revises: d5c81b6a47f2
Create Date: 2026-08-18 02:10:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e91c4d7b3f65"  # pragma: allowlist secret
down_revision: str | None = "d5c81b6a47f2"  # pragma: allowlist secret
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "finding_prose",
        # sha256 of the fact summary — the whole identity of a row.
        sa.Column("fact_hash", sa.String(length=64), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("why", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("fact_hash", name=op.f("pk_finding_prose")),
    )


def downgrade() -> None:
    """Dropping the cache loses nothing: every row is reproducible from its inputs."""
    op.drop_table("finding_prose")
