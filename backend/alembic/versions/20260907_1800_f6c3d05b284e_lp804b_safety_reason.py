"""LP-804b — why an attachment was refused.

A STATE WITH NO REASON IS A DEAD END. "Quarantined" tells a processor nothing about whether to ask
the borrower to resend, to send a different format, or to send a copy without a password — and those
are three different conversations to have with a person who is already waiting on their loan.

EXPOSED IN THE READONLY VIEW, unlike everything else on this table that carries text. This column is
prose written by US — a fixed set of sentences from `attachment_safety.assess` — not by a sender. It
names no borrower and quotes no filename, and it is the one field that makes the safety states
legible from the analytics side: "how many quarantines, and for what" is unanswerable from a state
enum alone.

Rebuilding the view rather than adding a column to it: a view cannot be altered to add a column, and
a rebuild is where dropped content comes back by accident — so the filename and storage-path
exclusions are re-asserted in the test that executes this.

Hand-written, like every migration against this schema.

Revision ID: f6c3d05b284e
Revises: e5b2c94a170d
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6c3d05b284e"  # pragma: allowlist secret
down_revision: str | None = "e5b2c94a170d"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VIEW = """
    CREATE VIEW readonly.inbound_attachments AS
    SELECT id, inbound_message_id, document_id,
           declared_content_type, sniffed_content_type,
           size_bytes, sha256, nesting_depth,
           scan_verdict, safety_state, safety_reason, disposition,
           (derived_storage_path IS NOT NULL) AS has_derived,
           created_at, updated_at, deleted_at
    FROM public.inbound_attachments
    """

_GRANT = """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON readonly.inbound_attachments TO mbai_readonly';
        END IF;
    END
    $$;
    """


def upgrade() -> None:
    op.add_column("inbound_attachments", sa.Column("safety_reason", sa.Text(), nullable=True))
    op.execute("DROP VIEW IF EXISTS readonly.inbound_attachments")
    op.execute(_VIEW)
    op.execute(_GRANT)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS readonly.inbound_attachments")
    op.drop_column("inbound_attachments", "safety_reason")
    op.execute("""
        CREATE VIEW readonly.inbound_attachments AS
        SELECT id, inbound_message_id, document_id,
               declared_content_type, sniffed_content_type,
               size_bytes, sha256, nesting_depth,
               scan_verdict, safety_state, disposition,
               (derived_storage_path IS NOT NULL) AS has_derived,
               created_at, updated_at, deleted_at
        FROM public.inbound_attachments
        """)
