"""LP-125R build AS-1 large-deposit sourcing (author applicability)

Revision ID: f3d9b6a1c8e2
Revises: e7b2c5a9f1d4
Create Date: 2026-07-08 15:00:00.000000

Builds AS-1 (``xsrc.asset.large_deposit_unsourced``) — a large deposit exceeding 50% of monthly income
must be sourced. The evaluator (``LargeDepositEvaluator``, registered by rule_id) does the per-account
threshold + sourcing logic; this migration only authors the applicability on the existing row:

* ``applicability`` NULL → the wire shape: triggers on a ``bank_statement`` document existing (empty
  documents → doesn't-apply), requires the deposits (``transactions[].amount``) AND the income basis
  (``borrowers[].income_items[].monthly_amount``) — both absent → couldn't-check.

``validated`` is already true (the >50% threshold is Priya-confirmed — decisions.md + seed
``large_deposit_pct=50``) and ``confidence_mode`` is already ``deterministic`` (now the evaluator's
declared mode, FIX 7), so this migration touches only ``applicability``. Data-only; no schema change; no
live-path behaviour change (AS-1 is dormant on the live path). Pairs the ``rule_seed.json`` change.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3d9b6a1c8e2"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "e7b2c5a9f1d4"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RULE_ID = "xsrc.asset.large_deposit_unsourced"
_APPLICABILITY = {
    "scope": {},
    "triggers": {
        "all": [
            {
                "kind": "entity_exists",
                "collection": "documents",
                "field": "document_type",
                "op": "eq",
                "value": "bank_statement",
            }
        ]
    },
    # No required_inputs (LP-125R FIX 3+7): the evaluator self-guards (absent income → couldn't-check;
    # a deposit with no amount → per-deposit couldn't-check). A single fee-line missing its amount must
    # not gate the whole rule. Only the bank-statement-exists trigger gates AS-1.
    "required_inputs": [],
}


def _rules_table() -> sa.TableClause:
    return sa.table(
        "verification_rules",
        sa.column("rule_id", sa.Text()),
        sa.column("applicability", sa.JSON()),
    )


def upgrade() -> None:
    """Author AS-1's applicability (no-op on a fresh DB — the seed already carries it)."""
    rules = _rules_table()
    op.execute(
        rules.update().where(rules.c.rule_id == _RULE_ID).values(applicability=_APPLICABILITY)
    )


def downgrade() -> None:
    """Intentionally a NO-OP.

    The seed now carries AS-1's authored applicability, so on a fresh DB the row already matches BEFORE
    this migration runs (it no-ops). Reverting to NULL applicability would leave AS-1 universally
    ready-to-run — a state matching neither the seed nor the evaluator — so downgrade leaves it authored.
    """
