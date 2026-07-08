"""LP-119 author AS-5 gift-letter applicability (the filter thin-slice rule)

Revision ID: a7c4e9f2b6d3
Revises: f3a9c2d5e8b1
Create Date: 2026-07-08 10:00:00.000000

Sets the ``applicability`` (scope / triggers / required_inputs, LP-119) on the AS-5 gift-letter rule
(``xsrc.asset.gift_without_letter``) in ``verification_rules`` — the thin-slice rule the
applicability filter is proven on. Trigger: a gift asset exists (``assets[].is_gift == true``);
required input: the ``is_gift`` data. The gift LETTER is the check-target (LP-120), NOT a required
input. Data-only update to one existing seed row; no schema change, no behaviour change (nothing
reads applicability on the live path yet).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c4e9f2b6d3"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "f3a9c2d5e8b1"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RULE_ID = "xsrc.asset.gift_without_letter"
_APPLICABILITY = {
    "scope": {},
    "triggers": {
        "all": [
            {
                "kind": "entity_exists",
                "collection": "assets",
                "field": "is_gift",
                "op": "eq",
                "value": True,
            }
        ]
    },
    "required_inputs": [{"kind": "data_field", "path": "assets[].is_gift"}],
}


def _rules_table() -> sa.TableClause:
    return sa.table(
        "verification_rules",
        sa.column("rule_id", sa.Text()),
        sa.column("applicability", sa.JSON()),
    )


def upgrade() -> None:
    """Author AS-5's applicability (the row exists from the LP-118 seed)."""
    rules = _rules_table()
    op.execute(
        rules.update().where(rules.c.rule_id == _RULE_ID).values(applicability=_APPLICABILITY)
    )


def downgrade() -> None:
    """Intentionally a NO-OP (FIX 7).

    The LP-118 seed (``d4b8f1a63c27``) now carries AS-5's authored applicability in
    ``rule_seed.json``, so on a fresh DB the row is already authored BEFORE this migration runs and
    this ``upgrade`` is an idempotent re-assert. Setting the applicability back to NULL on downgrade
    would leave AS-5 with no trigger → universally READY_TO_RUN (a silent over-apply) — a state
    matching neither the pre-migration DB nor the seeded value. So downgrade leaves the seeded
    (authored) applicability in place; there is nothing to revert to that is safe.
    """
