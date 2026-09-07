"""LP-812 — one row per message on the timeline, and a way to its attachments.

THE DOUBLE-COUNT THIS SETTLES. LP-805 writes THREE rows for one arrival: an `inbound_message`, a
`Communication(INBOUND, RECEIVED)`, and an `ActivityLog(COMMUNICATION_RECEIVED)`. The build plan
noted that no ticket reconciled them and asked LP-812 to decide which is the timeline's.

The answer is the `Communication`: it already carries direction, status, subject, recipient and
`sent_at`, which is what a message row on a timeline needs. The activity entry describes that same
Communication, so the timeline excludes every `COMMUNICATION_*` type — see `services/timeline.py`
for the enforcement, which enumerates the enum rather than listing the three that exist today.

That leaves the Communication needing a path to the ATTACHMENT MANIFEST, which hangs off
`inbound_messages`. `external_message_id` could not serve: it holds the RFC 5322 `Message-ID`, which
is written by the SENDER, is nullable and is not unique — joining on it would attach a borrower's
documents to whatever else claimed the same id. So a real FK.

SET NULL rather than CASCADE. A retention purge that removed raw messages must leave the evidence
record standing: `phase4.md` §6 requires the communication log to be append-only at the application
layer, and a cascade here would delete the record of a message having arrived along with its bytes.

Hand-written, like every migration against this schema.

Revision ID: c5f9a3b71d80
Revises: b7e4d219af53
Create Date: 2026-09-08 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5f9a3b71d80"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "b7e4d219af53"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "communications",
        sa.Column(
            "inbound_message_id",
            sa.UUID(),
            sa.ForeignKey("inbound_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_communications_inbound_message_id", "communications", ["inbound_message_id"]
    )

    # BACKFILLED FROM THE SENDER-WRITTEN ID, and only where it is unambiguous. Every routed inbound
    # Communication written before this migration has `external_message_id` set from
    # `inbound_messages.message_id`, so the link is recoverable — but `message_id` is not unique, so
    # a match that finds more than one row is left NULL rather than guessed. A timeline row with no
    # manifest is a gap somebody can see; one attached to another borrower's documents is not.
    op.execute(
        """
        UPDATE communications AS c
        SET inbound_message_id = m.id
        FROM inbound_messages AS m
        WHERE c.direction = 'inbound'
          AND c.inbound_message_id IS NULL
          AND c.external_message_id IS NOT NULL
          AND m.message_id = c.external_message_id
          AND m.loan_file_id = c.loan_file_id
          AND (
            SELECT count(*) FROM inbound_messages AS d
            WHERE d.message_id = c.external_message_id AND d.loan_file_id = c.loan_file_id
          ) = 1
        """
    )

    # The view is rebuilt to carry it. COPIED FROM LP-809's UPGRADE body, which is the shape the
    # database has — LP-806 lost three columns to copying a downgrade block, and the drift guard is
    # what caught it.
    op.execute("DROP VIEW IF EXISTS readonly.communications")
    op.execute(
        """
        CREATE VIEW readonly.communications AS
        SELECT id, loan_file_id, direction, channel, status, needs_item_id,
               initiated_by_user_id, external_message_id, inbound_message_id, sent_at,
               template_key, template_version,
               readonly.scrub(error_detail) AS error_detail,
               created_at, updated_at, deleted_at
        FROM public.communications
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
                EXECUTE 'GRANT SELECT ON readonly.communications TO mbai_readonly';
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS readonly.communications")
    # INLINE, not a module constant: the drift guard reads every `CREATE VIEW readonly.X` above the
    # rollback function as the LIVE definition, and would then check a shape the database does not
    # have. LP-813 hit that and the guard named it by file.
    op.execute(
        """
        CREATE VIEW readonly.communications AS
        SELECT id, loan_file_id, direction, channel, status, needs_item_id,
               initiated_by_user_id, external_message_id, sent_at,
               template_key, template_version,
               readonly.scrub(error_detail) AS error_detail,
               created_at, updated_at, deleted_at
        FROM public.communications
        """
    )
    op.drop_index("ix_communications_inbound_message_id", table_name="communications")
    op.drop_column("communications", "inbound_message_id")
