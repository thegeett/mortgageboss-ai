"""LP-122R certify AS-5 gift-letter as validated (rule #1)

Revision ID: b6f2d9c4e1a8
Revises: a7c4e9f2b6d3
Create Date: 2026-07-08 11:00:00.000000

Flips AS-5 (``xsrc.asset.gift_without_letter``) to ``validated=true`` in ``verification_rules``. AS-5
has NO tunable numeric threshold (its trigger is the boolean ``is_gift``, not a Priya-threshold) and
its evaluator reproduces the live gift-without-letter verdict, so it is certified at full confidence —
the runner (LP-121 FIX 5) no longer emits it as provisional. This is the LP-122R criterion in action:
validated=true is justified ONLY for non-threshold rules that reproduce known-correct behaviour;
threshold-bearing rules stay validated=false until Priya confirms the number. Data-only update to one
existing seed row; no schema change, no live-path behaviour change (nothing reads ``validated`` on the
live path yet).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b6f2d9c4e1a8"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "a7c4e9f2b6d3"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RULE_ID = "xsrc.asset.gift_without_letter"


def _rules_table() -> sa.TableClause:
    return sa.table(
        "verification_rules",
        sa.column("rule_id", sa.Text()),
        sa.column("validated", sa.Boolean()),
    )


def upgrade() -> None:
    """Certify AS-5 as validated (the row exists from the LP-118 seed)."""
    rules = _rules_table()
    op.execute(rules.update().where(rules.c.rule_id == _RULE_ID).values(validated=True))


def downgrade() -> None:
    """Intentionally a NO-OP.

    The LP-118 seed (``rule_seed.json``) now carries AS-5's ``validated=true`` (LP-122R), so on a fresh
    DB the row is already validated BEFORE this migration runs and this ``upgrade`` is an idempotent
    re-assert. Reverting to ``validated=false`` on downgrade would leave AS-5 provisional — a state
    matching neither the seeded value nor the certified reality — so downgrade leaves it validated.
    """
