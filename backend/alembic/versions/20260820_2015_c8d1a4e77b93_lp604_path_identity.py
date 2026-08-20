"""lp604 path identity for snapshot findings

Revision ID: c8d1a4e77b93
Revises: b7c4e91f2d38
Create Date: 2026-08-20 20:15:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8d1a4e77b93"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "b7c4e91f2d38"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # LP-604 — RETIRE the stored rows rather than re-key them, and this is the opposite of what
    # LP-600 did one migration ago. The difference is what the new key is made of.
    #
    # LP-600 could recompute: the old key was (kind, sources) and the new key was (normalised kind,
    # same sources), so every input was still in the row. LP-604's key is (kind, PATHS) — and no
    # stored row has paths. They were never asked for. There is nothing to recompute from, and
    # inventing a path from a label ("application", "property tax bill") would be a guess written
    # into an identity that then looks authoritative.
    #
    # So the honest move is to clear them and let the next run re-observe. What that costs is real
    # and worth stating: a `signed_off` / `not_an_issue` row is a decision a processor made, and this
    # discards it. It is done ONLY because the alternative — a fabricated path — silently mismatches
    # forever, which loses the same dismissals AND leaves a wrong key behind.
    #
    # The scan markers go with them: leaving a marker whose fingerprint matches would make the next
    # run a cache HIT over an empty table, so the tab would sit empty until the file changed.
    dispositioned = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM snapshot_findings WHERE disposition IN ('signed_off','not_an_issue')"
            )
        )
        .scalar()
    )
    print(f"LP-604: clearing snapshot findings; {dispositioned} carried a human disposition")

    op.execute("DELETE FROM snapshot_findings")
    op.execute("DELETE FROM snapshot_finding_scans")


def downgrade() -> None:
    # Nothing to restore — the rows are gone and their pre-LP-604 keys were not path-based.
    pass
