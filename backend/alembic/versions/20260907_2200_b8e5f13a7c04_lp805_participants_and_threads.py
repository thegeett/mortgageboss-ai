"""LP-805 — who is on a loan file, and the conversations on it.

`loan_file_participants` IS THE ALLOWLIST THE TRUST DECISION NEEDS. `phase4.md` §2.3 makes quarantine
the default and auto-accept the narrow exception, and one of its conditions is *sender ∈ loan file
participants*. Without this table that condition is unsatisfiable and every message goes to triage —
which is safe, and is also the product not working.

FILE-OWNED, NOT COMPANY-OWNED (ADR-052), and here that is more than convention: the same email
address can be a participant on two companies' files, and a company-scoped table would make "is this
sender known?" a question with a cross-tenant answer.

`is_trusted_sender` IS SEPARATE FROM MEMBERSHIP. Being on the file is not being trusted to drop
documents into it — an estate agent is a participant and is not somebody whose attachments should
bypass review. Seeding sets membership and never sets trust.

THE READONLY VIEW DROPS `email` AND `name`. Both identify a person; a participant list is a list of
people. What is left — the role, whether they are trusted, when — answers "how many files have a
trusted sender" without naming anybody. `email_threads.participants` goes for the same reason, and
`subject_normalized` because a subject is prose a borrower wrote.

Hand-written, like every migration against this schema.

Revision ID: b8e5f13a7c04
Revises: a7f42c8e91b6
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b8e5f13a7c04"  # pragma: allowlist secret
down_revision: str | None = "a7f42c8e91b6"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLES = ("borrower", "co_borrower", "loan_officer", "agent", "title", "underwriter", "other")

_PARTICIPANTS_VIEW = """
    CREATE VIEW readonly.loan_file_participants AS
    SELECT id, loan_file_id, role, is_trusted_sender,
           created_at, updated_at, deleted_at
    FROM public.loan_file_participants
    """

_THREADS_VIEW = """
    CREATE VIEW readonly.email_threads AS
    SELECT id, loan_file_id,
           jsonb_array_length(participants) AS participant_count,
           created_at, updated_at, deleted_at
    FROM public.email_threads
    """

_GRANT = """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON readonly.loan_file_participants TO mbai_readonly';
            EXECUTE 'GRANT SELECT ON readonly.email_threads TO mbai_readonly';
        END IF;
    END
    $$;
    """


def upgrade() -> None:
    op.create_table(
        "loan_file_participants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("loan_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=True),
        sa.Column("email", sa.String(length=256), nullable=False),
        sa.Column("is_trusted_sender", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["loan_file_id"], ["loan_files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("loan_file_id", "email", name="uq_loan_file_participants_file_email"),
    )
    op.create_index(
        "ix_loan_file_participants_loan_file_id", "loan_file_participants", ["loan_file_id"]
    )
    op.create_index("ix_loan_file_participants_email", "loan_file_participants", ["email"])

    joined = ", ".join(f"'{value}'" for value in _ROLES)
    op.execute(
        "ALTER TABLE loan_file_participants ADD CONSTRAINT ck_loan_file_participants_role "
        f"CHECK (role IN ({joined}))"
    )

    op.create_table(
        "email_threads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("loan_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("root_message_id", sa.String(length=256), nullable=False),
        sa.Column("subject_normalized", sa.String(length=256), nullable=True),
        sa.Column("participants", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["loan_file_id"], ["loan_files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("loan_file_id", "root_message_id", name="uq_email_threads_file_root"),
    )
    op.create_index("ix_email_threads_loan_file_id", "email_threads", ["loan_file_id"])

    for statement in ("loan_file_participants", "email_threads"):
        op.execute(f"DROP VIEW IF EXISTS readonly.{statement}")
    op.execute(_PARTICIPANTS_VIEW)
    op.execute(_THREADS_VIEW)
    op.execute(_GRANT)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS readonly.email_threads")
    op.execute("DROP VIEW IF EXISTS readonly.loan_file_participants")
    op.drop_table("email_threads")
    op.drop_table("loan_file_participants")
