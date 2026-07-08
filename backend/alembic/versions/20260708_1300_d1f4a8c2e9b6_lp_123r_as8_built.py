"""LP-123R build AS-8 bank-statement continuity (enable + author applicability)

Revision ID: d1f4a8c2e9b6
Revises: c9a3e7f1b5d8
Create Date: 2026-07-08 13:00:00.000000

Builds AS-8 (bank-statement continuity) on its existing playbook row ``pb.as-8`` — a NEW rule with a
self-defined spec (AS-8 has no live counterpart; see ``docs/audits/live-rule-inventory-corrected.md``).
The evaluator (``BankStatementContinuityEvaluator``, registered by rule_id ``pb.as-8``) does the
grouping-by-account + continuity logic; this migration only flips the row from a disabled placeholder to
an enabled rule with its authored applicability + metadata:

* ``enabled`` false → true
* ``applicability`` NULL → the wire shape (trigger: a ``bank_statement`` document exists; required input:
  a ``bank_statement`` document present — the 2+/grouping/continuity logic is evaluator-side)
* ``canonical_type`` / ``message_template`` / ``severity`` set

``validated`` stays **false** (provisional): the exact-match tolerance + one-statement handling are
self-defined choices flagged for Priya. ``confidence_mode`` is already ``deterministic``. Per the
round-3 discipline this pairs the ``rule_seed.json`` change (``pb.as-8`` now built) so existing DBs match.
Data-only; no schema change; no live-path behaviour change.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1f4a8c2e9b6"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "c9a3e7f1b5d8"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RULE_ID = "pb.as-8"
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
    "required_inputs": [{"kind": "document", "document_type": "bank_statement"}],
}
_CANONICAL_TYPE = "bank_statement_discontinuity"
_MESSAGE = "Bank-statement continuity is broken or unverified for one or more accounts."
_SEVERITY = "YELLOW"


def _rules_table() -> sa.TableClause:
    return sa.table(
        "verification_rules",
        sa.column("rule_id", sa.Text()),
        sa.column("applicability", sa.JSON()),
        sa.column("canonical_type", sa.Text()),
        sa.column("message_template", sa.Text()),
        sa.column("severity", sa.String()),
        sa.column("enabled", sa.Boolean()),
    )


def upgrade() -> None:
    """Enable + author AS-8 on the existing ``pb.as-8`` row (no-op on a fresh DB — the seed built it)."""
    rules = _rules_table()
    op.execute(
        rules.update()
        .where(rules.c.rule_id == _RULE_ID)
        .values(
            applicability=_APPLICABILITY,
            canonical_type=_CANONICAL_TYPE,
            message_template=_MESSAGE,
            severity=_SEVERITY,
            enabled=True,
        )
    )


def downgrade() -> None:
    """Intentionally a NO-OP.

    The seed (``rule_seed.json``) now carries AS-8 as a built, enabled rule, so on a fresh DB the row is
    already built BEFORE this migration runs (it no-ops). Reverting to the disabled/NULL placeholder would
    leave AS-8 un-runnable — a state matching neither the seed nor the registered evaluator — so downgrade
    leaves the built row in place.
    """
