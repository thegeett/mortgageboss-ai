"""LP-316 finding outcome states + subject_key + provenance + per-finding event log

Revision ID: a3d7f1e9c2b5
Revises: f7a2c9d4e1b8
Create Date: 2026-07-14 16:00:00.000000

Persists rule-engine evaluations (LP-315/LP-314a) as durable findings by EXTENDING the shared
``findings`` model (not forking it):

* ``evaluation_outcome`` — the NEW verification-outcome axis (open / satisfied / needs_review /
  couldnt_check / no_longer_applies), orthogonal to the severity + resolution enums. Nullable
  (only tag-rule findings carry it).
* ``subject_key`` — the stable per-subject identity (a deposit's content_id, LP-312), promoted
  from ``details`` JSON to a column, with a PARTIAL unique index ``(loan_file_id, rule_id,
  subject_key)`` over LIVE findings that have a subject_key (so soft-deleted / legacy null rows
  don't participate).
* ``load_bearing_tags`` — the inline provenance (JSONB): the tags a verdict rested on.

And creates ``finding_events`` — the append-only per-finding lifecycle log (LP-316 emits only the
``created`` event; LP-322 wires the rest).

CHECK / index names use the literals the models' ``str_enum`` + naming convention produce, so a
fresh ``create_all`` and this migration converge.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a3d7f1e9c2b5"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "f7a2c9d4e1b8"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OUTCOMES = ("open", "satisfied", "needs_review", "couldnt_check", "no_longer_applies")
_EVENT_TYPES = ("created", "outcome_changed", "resolved", "retired")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    """Extend findings + create the finding_events log."""
    # --- findings: the new columns -------------------------------------------
    op.add_column("findings", sa.Column("evaluation_outcome", sa.String(length=32), nullable=True))
    op.execute(
        f"ALTER TABLE findings ADD CONSTRAINT ck_findings_evaluationoutcome "
        f"CHECK ({_in('evaluation_outcome', _OUTCOMES)})"
    )
    op.create_index("ix_findings_evaluation_outcome", "findings", ["evaluation_outcome"])

    op.add_column("findings", sa.Column("subject_key", sa.String(length=256), nullable=True))
    op.create_index("ix_findings_subject_key", "findings", ["subject_key"])

    op.add_column(
        "findings",
        sa.Column("load_bearing_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    # A subject is ONE live finding per rule — partial unique over live, subject-keyed findings.
    op.create_index(
        "uq_findings_loan_file_rule_subject",
        "findings",
        ["loan_file_id", "rule_id", "subject_key"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND subject_key IS NOT NULL"),
    )

    # --- finding_events: the append-only per-finding log ---------------------
    op.create_table(
        "finding_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("from_outcome", sa.String(length=32), nullable=True),
        sa.Column("to_outcome", sa.String(length=32), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            _in("event_type", _EVENT_TYPES), name="ck_finding_events_findingeventtype"
        ),
        sa.CheckConstraint(
            _in("from_outcome", _OUTCOMES), name="ck_finding_events_finding_event_from_outcome"
        ),
        sa.CheckConstraint(
            _in("to_outcome", _OUTCOMES), name="ck_finding_events_finding_event_to_outcome"
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["findings.id"],
            name=op.f("fk_finding_events_finding_id_findings"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_finding_events")),
    )
    op.create_index(
        op.f("ix_finding_events_finding_id"), "finding_events", ["finding_id"], unique=False
    )


def downgrade() -> None:
    """Drop the finding_events log + the findings columns/constraints/indexes."""
    op.drop_index(op.f("ix_finding_events_finding_id"), table_name="finding_events")
    op.drop_table("finding_events")

    op.drop_index("uq_findings_loan_file_rule_subject", table_name="findings")
    op.drop_column("findings", "load_bearing_tags")
    op.drop_index("ix_findings_subject_key", table_name="findings")
    op.drop_column("findings", "subject_key")
    op.drop_index("ix_findings_evaluation_outcome", table_name="findings")
    op.execute("ALTER TABLE findings DROP CONSTRAINT ck_findings_evaluationoutcome")
    op.drop_column("findings", "evaluation_outcome")
