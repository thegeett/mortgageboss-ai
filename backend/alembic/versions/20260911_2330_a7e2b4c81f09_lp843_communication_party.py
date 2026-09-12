"""LP-843 — a message records WHO it is for, separately from what rendered it.

Revision ID: a7e2b4c81f09
Revises: f4a1c9d2e7b3
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7e2b4c81f09"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "f4a1c9d2e7b3"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GRANT = """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON readonly.communications TO mbai_readonly';
        END IF;
    END $$;
"""


def upgrade() -> None:
    """Add `party`, backfill it from LP-841's template keys, and expose it.

    THE BACKFILL IS DERIVABLE, which is what makes it honest. LP-841 filed each party's draft under
    `document_request_<party>`, so the audience of every existing draft is recoverable from the key
    it was filed under — this is not guessing an audience, it is reading one that was already
    recorded in a field doing two jobs.

    The borrower's key is `initial_documentation_request` and not `document_request_borrower`: ADR-401
    pins that historical key, so it cannot be renamed and the backfill has to name it specially.

    EXPOSED RAW rather than scrubbed, unlike the free text on this table. `readonly.scrub` exists to
    remove identifiers from prose; `party` is one of eight fixed catalog values and scrubbing it
    would destroy the only thing it says while protecting nothing.
    """
    op.add_column("communications", sa.Column("party", sa.String(length=32), nullable=True))
    op.create_index("ix_communications_party", "communications", ["party"])
    op.execute(
        """
        UPDATE communications
           SET party = CASE template_key
                 WHEN 'initial_documentation_request' THEN 'borrower'
                 WHEN 'document_request_borrower'     THEN 'borrower'
                 WHEN 'document_request_lender'       THEN 'lender'
                 WHEN 'document_request_title'        THEN 'title'
                 WHEN 'document_request_employer'     THEN 'employer'
                 WHEN 'document_request_cpa'          THEN 'cpa'
                 WHEN 'document_request_agent'        THEN 'agent'
                 WHEN 'document_request_insurer'      THEN 'insurer'
                 WHEN 'document_request_processor'    THEN 'processor'
               END
         WHERE direction = 'outbound'
        """
    )
    op.execute("DROP VIEW IF EXISTS readonly.communications")
    op.execute(
        """
        CREATE VIEW readonly.communications AS
        SELECT id, loan_file_id, direction, channel, status, needs_item_id,
               initiated_by_user_id, external_message_id, inbound_message_id, sent_at,
               template_key, template_version, is_important, read_at, party,
               readonly.scrub(error_detail) AS error_detail,
               created_at, updated_at, deleted_at
        FROM public.communications
        """
    )
    op.execute(_GRANT)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS readonly.communications")
    op.execute(
        """
        CREATE VIEW readonly.communications AS
        SELECT id, loan_file_id, direction, channel, status, needs_item_id,
               initiated_by_user_id, external_message_id, inbound_message_id, sent_at,
               template_key, template_version, is_important, read_at,
               readonly.scrub(error_detail) AS error_detail,
               created_at, updated_at, deleted_at
        FROM public.communications
        """
    )
    op.execute(_GRANT)
    op.drop_index("ix_communications_party", table_name="communications")
    op.drop_column("communications", "party")
