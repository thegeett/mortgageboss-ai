"""LP-124R reproduce employer-count-matches-income-items (author applicability + validate)

Revision ID: e7b2c5a9f1d4
Revises: d1f4a8c2e9b6
Create Date: 2026-07-08 14:00:00.000000

Reproduces the LIVE ``xsrc.income.employer_count_matches_items`` rule in the new engine (off our
authored list — no playbook_id). The evaluator (``EmployerCountEvaluator``, registered by rule_id) does
the file-level count comparison; this migration aligns the existing seed row with the reproduced spec:

* ``applicability`` NULL → the wire shape ``{scope:{}, triggers:{}, required_inputs:[]}``. The live rule
  always runs and self-guards (no-ops when either count is 0) — so it has no trigger/required-input
  gating; the evaluator reproduces the None-guard as couldn't-check. (Requiring the nullable
  ``employment_income`` leaf would diverge, so required_inputs stays empty — STEP 0.)
* ``validated`` false → **true**: exact integer count equality, NO threshold, reproduces known-correct
  live behaviour → validated per the LP-122R criterion (first reproduced-live rule to qualify).
* ``confidence_mode`` NULL → **deterministic** (the rule has no playbook layer; the evaluator emits
  deterministic → align the column with the runner, FIX 6).

Data-only; no schema change; no live-path behaviour change (nothing reads these on the live path yet).
Pairs the ``rule_seed.json`` change per the round-3 discipline.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7b2c5a9f1d4"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "d1f4a8c2e9b6"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RULE_ID = "xsrc.income.employer_count_matches_items"
_APPLICABILITY = {"scope": {}, "triggers": {}, "required_inputs": []}


def _rules_table() -> sa.TableClause:
    return sa.table(
        "verification_rules",
        sa.column("rule_id", sa.Text()),
        sa.column("applicability", sa.JSON()),
        sa.column("confidence_mode", sa.String()),
        sa.column("validated", sa.Boolean()),
    )


def upgrade() -> None:
    """Author + validate the employer-count rule (no-op on a fresh DB — the seed already built it)."""
    rules = _rules_table()
    op.execute(
        rules.update()
        .where(rules.c.rule_id == _RULE_ID)
        .values(applicability=_APPLICABILITY, confidence_mode="deterministic", validated=True)
    )


def downgrade() -> None:
    """Intentionally a NO-OP.

    The seed now carries this rule as authored + validated=true, so on a fresh DB the row already matches
    BEFORE this migration runs (it no-ops). Reverting would leave the reproduced rule provisional / null —
    a state matching neither the seed nor the registered evaluator — so downgrade leaves it in place.
    """
