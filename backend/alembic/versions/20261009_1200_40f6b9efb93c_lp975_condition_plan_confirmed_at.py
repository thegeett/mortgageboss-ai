"""LP-975 — `conditions.plan_confirmed_at`: when she confirmed a plan this condition was on.

Whether a condition's plan is in force was asked of its `last_seen_round_id`'s round. A condition seen
again moves to the new round, so that forgot a plan confirmed on round 1 as soon as round 2 was imported,
and put an earlier plan she never confirmed in force when she confirmed round 2.

BACKFILL: a condition is stamped with the EARLIEST confirm of any round it appeared on (a
`condition_created` or `condition_seen_again` event on that round), or of its last-seen round. The second
half is today's rule, so nothing that is in force today stops being in force; the first is what a
condition seen again after a confirmed round should always have had.

EARLIEST, AS THE CODE WRITES IT (LP-975 review): `confirm_round_plan` stamps only a condition with no stamp
yet, so a live stamp is the first confirm of a plan the condition was on. The backfill took `max` and so
disagreed with the code about what the timestamp means; only whether it is set is read today, but a later
reader of the date would have got two meanings.

NOT IN THE READONLY VIEW. `readonly.conditions` lists its columns explicitly (LP-956), so a new column
stays out of it until a ticket adds it.

Revision ID: 40f6b9efb93c
Revises: f392190637fa
Create Date: 2026-10-09 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "40f6b9efb93c"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "f392190637fa"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conditions",
        sa.Column("plan_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE conditions AS c
        SET plan_confirmed_at = stamped.at
        FROM (
            SELECT condition_id, min(at) AS at
            FROM (
                SELECT e.condition_id, r.plan_confirmed_at AS at
                FROM condition_events AS e
                JOIN condition_rounds AS r ON r.id = e.round_id
                WHERE e.kind IN ('condition_created', 'condition_seen_again')
                  AND e.condition_id IS NOT NULL
                  AND r.plan_confirmed_at IS NOT NULL
                UNION ALL
                SELECT c2.id, r2.plan_confirmed_at
                FROM conditions AS c2
                JOIN condition_rounds AS r2 ON r2.id = c2.last_seen_round_id
                WHERE r2.plan_confirmed_at IS NOT NULL
            ) AS confirmed
            GROUP BY condition_id
        ) AS stamped
        WHERE c.id = stamped.condition_id
        """
    )


def downgrade() -> None:
    op.drop_column("conditions", "plan_confirmed_at")
