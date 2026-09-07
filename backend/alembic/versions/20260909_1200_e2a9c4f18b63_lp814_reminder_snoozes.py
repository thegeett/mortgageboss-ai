"""LP-814 — the decision a processor made about a reminder.

SUGGESTIONS ARE COMPUTED, NOT STORED, so there is no `reminder_suggestions` table. The three rules
read `requested_at`, the needs list and the activity log; the answer is a function of those, and
materialising it would mean a second copy that goes stale the moment a document arrives — a
processor nudged about something that turned up an hour ago.

WHAT IS STORED IS THE DECISION. "Not now" and "not ever" are the only facts a query cannot derive,
because a person chose them. They share one row: a dismissal is a snooze with no end, and two tables
would make "is this suppressed?" two questions, the second of which is the one somebody forgets.

THE UNIQUE INDEX CARRIES `NULLS NOT DISTINCT`. `subject_id` is NULL for a rule about the file itself
("nothing has happened here for a week"), and without it every such snooze would be a fresh row and
none of them would suppress anything — Postgres's default treating NULLs as distinct, biting in the
direction LP-803's review had it biting in the other.

THE READONLY VIEW KEEPS EVERYTHING EXCEPT `note`. The rest is a rule name, an id and two timestamps,
which answers "how often is this suggestion put off" without naming anybody; the note is free prose a
processor typed about one borrower's file, which is where a name arrives in a shape no scrubber
predicts — the same argument `dti_custom_lines.note` is excluded on.

Hand-written, like every migration against this schema.

Revision ID: e2a9c4f18b63
Revises: d81b6e4c25f7
Create Date: 2026-09-09 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2a9c4f18b63"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "d81b6e4c25f7"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = ("needs_item_pending", "no_reply", "file_untouched")

_VIEW = """
    CREATE VIEW readonly.reminder_snoozes AS
    SELECT id, loan_file_id, kind, subject_id, snoozed_until,
           (note IS NOT NULL) AS has_note,
           created_at, updated_at, deleted_at
    FROM public.reminder_snoozes
    """

_GRANT = """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON readonly.reminder_snoozes TO mbai_readonly';
        END IF;
    END
    $$;
    """


def upgrade() -> None:
    op.create_table(
        "reminder_snoozes",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "loan_file_id",
            sa.UUID(),
            sa.ForeignKey("loan_files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=True),
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        # VARCHAR + CHECK rather than a native enum (ADR-037): adding a rule is one migration that
        # recreates the constraint from its own complete tuple, not an ALTER TYPE.
        sa.CheckConstraint(
            "kind IN (" + ", ".join(f"'{kind}'" for kind in _KINDS) + ")",
            name="ck_reminder_snoozes_kind",
        ),
    )
    op.create_index("ix_reminder_snoozes_loan_file_id", "reminder_snoozes", ["loan_file_id"])
    # NULLS NOT DISTINCT — see the module docstring. Raw SQL because the Alembic helper has no
    # parameter for it and a plain unique index here is the bug rather than a lesser version of it.
    op.execute(
        "CREATE UNIQUE INDEX uq_reminder_snoozes_subject "
        "ON reminder_snoozes (loan_file_id, kind, subject_id) NULLS NOT DISTINCT"
    )

    op.execute(_VIEW)
    op.execute(_GRANT)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS readonly.reminder_snoozes")
    op.execute("DROP INDEX IF EXISTS uq_reminder_snoozes_subject")
    op.drop_index("ix_reminder_snoozes_loan_file_id", table_name="reminder_snoozes")
    op.drop_table("reminder_snoozes")
