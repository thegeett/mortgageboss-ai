"""LP-MB-Admin-05 — loan teams, the LOAN_TEAM_CHANGED activity, and the backfill.

1. `loan_teams`: one row per person per slot on a file (`loan_officer`, `processor`, `assistant`
   reserved). Soft-deleted on removal. Partial unique indexes on live rows: a person holds a slot
   once, and a file has at most one loan officer.
2. `activity_logs.activity_type` gains `loan_team_changed`. THE SWAP LISTS ALL 37 VALUES: each swap
   drops the constraint and recreates it from its own tuple, so a value omitted here would be revoked
   (`tests/test_activity_type_migrations.py`). The 36 came from `[m.value for m in ActivityType]`
   before the new member was added, in enum order, not from a grep. Other branches may add values
   too; at merge, the swap applied last must carry the union.
3. Backfill: each file's creator (the actor of its FILE_CREATED activity), if still active, not
   deleted, and holding PROCESSOR, becomes a processor on its team, added by the system. A file with
   no such creator stays unassigned.
4. `readonly.loan_teams`: every column (ids, a role word, timestamps): nothing in it names a person.

Hand-written, like every migration against this schema.

Revision ID: 14e94a531fce
Revises: 6316da7fe522
Create Date: 2026-11-13 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "14e94a531fce"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "6316da7fe522"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_activity_logs_activitytype"

#: Every value the enum declared before this migration: 36, in enum order, from the enum itself.
_EXISTING = (
    "file_created",
    "file_updated",
    "file_deleted",
    "status_changed",
    "document_uploaded",
    "document_processed",
    "document_type_overridden",
    "document_replaced",
    "document_staleness_resolved",
    "field_reviewed",
    "field_review_reverted",
    "document_reprocessed",
    "finding_resolved",
    "finding_undone",
    "verification_run",
    "dti_overridden",
    "dti_line_added",
    "dti_line_removed",
    "dti_ungated",
    "ltv_overridden",
    "calculator_overridden",
    "lender_overlay_updated",
    "needs_item_created",
    "needs_item_satisfied",
    "needs_item_confirmed",
    "needs_item_adjusted",
    "needs_item_dismissed",
    "needs_item_waived",
    "communication_sent",
    "communication_received",
    "communication_failed",
    "note_added",
    "condition_sheet_received",
    "condition_imported",
    "condition_plan_ready",
    "condition_plan_confirmed",
)

#: 37: the 36 above plus the one this ticket adds.
_NEW_VALUES = (*_EXISTING, "loan_team_changed")

_TEAM_ROLES = ("loan_officer", "processor", "assistant")

_GRANT = """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON readonly.loan_teams TO mbai_readonly';
        END IF;
    END
    $$;
    """


def _swap_check(values: tuple[str, ...]) -> None:
    joined = ", ".join(f"'{value}'" for value in values)
    op.execute(f"ALTER TABLE activity_logs DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE activity_logs ADD CONSTRAINT {_CONSTRAINT} "
        f"CHECK (activity_type IN ({joined}))"
    )


def upgrade() -> None:
    op.create_table(
        "loan_teams",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("loan_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("team_role", sa.String(length=32), nullable=False),
        sa.Column("added_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["loan_file_id"],
            ["loan_files.id"],
            name="fk_loan_teams_loan_file_id_loan_files",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_loan_teams_user_id_users", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["added_by_user_id"],
            ["users.id"],
            name="fk_loan_teams_added_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_loan_teams"),
    )
    op.create_index("ix_loan_teams_loan_file_id", "loan_teams", ["loan_file_id"])
    op.create_index("ix_loan_teams_user_id", "loan_teams", ["user_id"])
    joined = ", ".join(f"'{v}'" for v in _TEAM_ROLES)
    op.execute(
        f"ALTER TABLE loan_teams ADD CONSTRAINT ck_loan_teams_teamrole CHECK (team_role IN ({joined}))"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_loan_teams_member_live ON loan_teams "
        "(loan_file_id, user_id, team_role) WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_loan_teams_one_loan_officer ON loan_teams (loan_file_id) "
        "WHERE deleted_at IS NULL AND team_role = 'loan_officer'"
    )

    _swap_check(_NEW_VALUES)

    # The creator of each file, if still an active processor, works it.
    op.execute(
        """
        INSERT INTO loan_teams (id, loan_file_id, user_id, team_role, added_by_user_id,
                                created_at, updated_at)
        SELECT DISTINCT ON (a.loan_file_id)
               gen_random_uuid(), a.loan_file_id, a.actor_user_id, 'processor', NULL, now(), now()
        FROM activity_logs a
        JOIN users u ON u.id = a.actor_user_id
        JOIN loan_files f ON f.id = a.loan_file_id
        WHERE a.activity_type = 'file_created'
          AND u.is_active AND u.deleted_at IS NULL
          AND u.company_id = f.company_id
          AND EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = u.id AND r.role = 'processor')
        ORDER BY a.loan_file_id, a.created_at
        """
    )

    op.execute(
        """
        CREATE VIEW readonly.loan_teams AS
        SELECT id, loan_file_id, user_id, team_role, added_by_user_id,
               created_at, updated_at, deleted_at
        FROM public.loan_teams
        """
    )
    op.execute(_GRANT)


def downgrade() -> None:
    """Back to the 36. Team-change timeline rows are deleted first, or the CHECK refuses them: an
    audit loss, the honest cost of removing a value the application has written."""
    op.execute("DROP VIEW IF EXISTS readonly.loan_teams")
    op.execute("DELETE FROM activity_logs WHERE activity_type = 'loan_team_changed'")
    _swap_check(_EXISTING)
    op.drop_table("loan_teams")
