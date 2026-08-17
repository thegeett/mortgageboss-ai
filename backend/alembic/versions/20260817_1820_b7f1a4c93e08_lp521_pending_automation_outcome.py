"""LP-521 — let the outcome constraints store `pending_automation`.

⚠️ THIS IS A LIVE BREAKAGE FIX. LP-391 added `pending_automation` to the Python `EvaluationOutcome`
enum and the engine has produced it ever since, but NO migration extended the database's CHECK
constraints, which still carry LP-316's original five values. Nothing had ever hit it, because the
outcome is emitted only by the pending-checks pass — for a rule that is BLOCKED (not activated) yet
finds something in its scope — and no such rule had inputs that resolved.

LP-519's AS-13 is the first. It is inert by design, and its input is a LOAN-subject derived tag that
materialises on every file, so pending-checks emits `pending_automation` for it on every run. The
insert is rejected, the rule-engine task retries, and each retry re-runs the whole AI pipeline
(~6 minutes, real Bedrock spend) until MAX_RETRIES is exhausted. Every verification on every file fails
until this lands.

The fix is the constraint, not the engine: `pending_automation` is a legitimate designed state (LP-391
Tab 1, "manual review — automated check not yet active"), deliberately produced, and the database
simply could not store it. Any future inert-but-resolving rule would hit this identically.

Three constraints share the same value list — `findings.evaluation_outcome`, and the finding_events
log's `from_outcome` / `to_outcome`. All three are rebuilt, because a finding that cannot transition is
as broken as one that cannot be written.

Revision ID: b7f1a4c93e08
Revises: c3e940f8ee9d
Create Date: 2026-08-17 18:20:00.000000
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7f1a4c93e08"  # pragma: allowlist secret
down_revision: str | None = "c3e940f8ee9d"  # pragma: allowlist secret
branch_labels: None = None
depends_on: None = None

# The LP-316 five, plus LP-391's pending_automation. MUST equal `EvaluationOutcome` in
# app/models/finding.py — test_pending_automation_outcome_lp521 asserts the two cannot drift again,
# which is the guard that was missing when LP-391 shipped.
_OUTCOMES = (
    "open",
    "satisfied",
    "needs_review",
    "couldnt_check",
    "pending_automation",
    "no_longer_applies",
)
_PREVIOUS = tuple(v for v in _OUTCOMES if v != "pending_automation")

# ⚠️ THE finding_events NAMES ARE DOUBLE-PREFIXED, AND THAT IS NOT A TYPO. Read from the live schema
# (pg_constraint), not from LP-316's source: that migration passed an already-prefixed name to
# `sa.CheckConstraint(name="ck_finding_events_finding_event_from_outcome")` inside `create_table`, and
# the metadata naming convention `ck_%(table_name)s_%(constraint_name)s` prefixed it AGAIN. The
# `findings` constraint escaped this because LP-316 created it with raw `ALTER TABLE ... ADD CONSTRAINT`,
# which the convention never touches.
#
# A first version of this migration used the short names and failed on staging with
# UndefinedObjectError — after the `findings` drop had already run. Alembic's transactional DDL rolled
# the whole thing back cleanly, which is the only reason that was a non-event. Do not "tidy" these
# names without renaming the live constraints in the same migration.
_CONSTRAINTS = (
    ("findings", "ck_findings_evaluationoutcome", "evaluation_outcome"),
    (
        "finding_events",
        "ck_finding_events_ck_finding_events_finding_event_from_outcome",
        "from_outcome",
    ),
    (
        "finding_events",
        "ck_finding_events_ck_finding_events_finding_event_to_outcome",
        "to_outcome",
    ),
)


def _in(column: str, values: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{v}'" for v in values)
    return f"{column} IS NULL OR {column} IN ({joined})"


def _rebuild(values: tuple[str, ...]) -> None:
    for table, name, column in _CONSTRAINTS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({_in(column, values)})")


def upgrade() -> None:
    _rebuild(_OUTCOMES)


def downgrade() -> None:
    """Narrow the constraints back to the LP-316 five.

    ⚠️ This DELETES any `pending_automation` row first. Postgres validates a new CHECK against existing
    rows, so leaving them would make the downgrade fail outright — and a downgrade that cannot run is
    worse than one that is explicit about what it discards. The rows are reproducible: they are derived
    per run by the pending-checks pass, not authored by a human.
    """
    op.execute("DELETE FROM finding_events WHERE from_outcome = 'pending_automation'")
    op.execute("DELETE FROM finding_events WHERE to_outcome = 'pending_automation'")
    op.execute("DELETE FROM findings WHERE evaluation_outcome = 'pending_automation'")
    _rebuild(_PREVIOUS)
