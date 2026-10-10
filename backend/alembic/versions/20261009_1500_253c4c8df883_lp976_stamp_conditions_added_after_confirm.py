"""LP-976 — stamp the conditions that are in force today only through the round fallback.

LP-976 makes a condition's plan in force by its own stamp alone (`condition_plan.plan_confirmed`). Before
it, a condition with no stamp on a round whose plan was confirmed was in force through the round: one
added after confirm, by hand, by merging a PDF, or by forwarding an attachment into the round. Dropping
the fallback without this would take those plans out of force on deploy, and their unsent emails would
start being refused.

So each one is stamped, with the time it came into force under the old rule: the later of the round's
confirm and the condition's own creation. Only conditions added AFTER this ships wait for her to confirm
their plan on the panel.

Data only; no schema change. The downgrade cannot tell these stamps from ones a confirm wrote, so it
leaves them, and LP-975's fallback (the code this reverts to) reads them the same way.

Revision ID: 253c4c8df883
Revises: 40f6b9efb93c
Create Date: 2026-10-09 15:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "253c4c8df883"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "40f6b9efb93c"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE conditions AS c
        SET plan_confirmed_at = GREATEST(r.plan_confirmed_at, c.created_at)
        FROM condition_rounds AS r
        WHERE r.id = c.last_seen_round_id
          AND r.plan_confirmed_at IS NOT NULL
          AND c.plan_confirmed_at IS NULL
        """
    )


def downgrade() -> None:
    # Nothing to undo: see the module docstring.
    pass
