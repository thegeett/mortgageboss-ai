"""LP-818 — reply, mark important, and read state.

REPLY WAS BLOCKED BY THE DATA MODEL, NOT BY A MISSING BUTTON. §C.5 says it: LP-809 creates a draft
plus a `communication_needs_items` join, and LP-811's send endpoint requires a `draft_id`. A reply to
*"is page 4 really needed?"* has no needs behind it, so it could not become a draft, so it could not
be sent. The needs-less draft is a service-level shape (a `Communication` with a NULL `template_key`,
which the one-open-draft index already treats as distinct) and needs no column — what needs columns
is everything a reply IS.

`in_reply_to_message_id` SEPARATES TWO MEANINGS THAT WERE SHARING ONE COLUMN. `external_message_id`
means "this message's own id" — LP-805's rung 2 matches a borrower's `References` against it — and
LP-815's nudge was writing the id of the message it was ANSWERING there. That routed correctly by
accident, because a reply's `References` carries the borrower's own id as well; it would break the
moment anything stored a genuinely generated outbound id, because rung 2 would then match a thread
to a row holding a borrower's id under the wrong meaning. The nudge is corrected in this ticket.

`is_important` is a PROCESSOR'S OWN JUDGEMENT. Nothing computes it and no model suggests it.

`read_at` is a TIMESTAMP, not a boolean: "unread" and "read four days ago" are the same boolean and
different facts, and the second is what says a message was seen and left.

THE READONLY VIEW TAKES `is_important` AND `read_at` AND NOT `in_reply_to_message_id`. The first two
are facts about how a company works — how much gets flagged, how long mail sits unread — and answer
that without naming anybody. The third is a sender-written `Message-ID`, which identifies one message
from one person, and `external_message_id` beside it is already exposed for dedup analysis; adding a
second copy of the same class of identifier buys nothing.

Hand-written, like every migration against this schema.

Revision ID: d81b6e4c25f7
Revises: c5f9a3b71d80
Create Date: 2026-09-09 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d81b6e4c25f7"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "c5f9a3b71d80"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Hoisted so a test can EXECUTE it rather than read it, the pattern LP-812's review established for
#: the backfill it found two bugs in: a one-shot UPDATE runs once, against data nobody has, and is
#: unfalsifiable afterwards.
#:
#: EXCLUDES SOFT-DELETED ROWS ON BOTH SIDES — the omission LP-812's backfill had in both directions
#: at once, where one half was too permissive and the other too strict from a single missing
#: predicate.
_BACKFILL_NUDGE_REPLY_TO = """
    UPDATE communications AS c
    SET in_reply_to_message_id = c.external_message_id,
        external_message_id = NULL
    WHERE c.template_key = 'borrower_secure_upload_nudge'
      AND c.direction = 'outbound'
      AND c.external_message_id IS NOT NULL
      AND c.in_reply_to_message_id IS NULL
      AND c.deleted_at IS NULL
    """


def upgrade() -> None:
    op.add_column(
        "communications", sa.Column("in_reply_to_message_id", sa.String(128), nullable=True)
    )
    op.add_column(
        "communications",
        sa.Column("is_important", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("communications", sa.Column("read_at", sa.DateTime(timezone=True), nullable=True))
    # The unread badge counts inbound messages with no `read_at`. Partial, because every OTHER row on
    # a busy file is read or outbound and has no business in that index.
    op.execute(
        "CREATE INDEX ix_communications_unread ON communications (loan_file_id) "
        "WHERE direction = 'inbound' AND read_at IS NULL AND deleted_at IS NULL"
    )

    # LP-815's nudge stored the id it was ANSWERING in `external_message_id`. Moved to the column
    # that means that, and cleared, so rung 2 stops matching a borrower's own id against a row whose
    # column means "this message's id".
    op.execute(_BACKFILL_NUDGE_REPLY_TO)

    # Rebuilt to carry the two analytic columns. COPIED FROM LP-812's UPGRADE body, which is the
    # shape the database has — LP-806 lost three columns to copying a downgrade block.
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
    # rollback function as the LIVE definition. LP-813 hit that and the guard named it by file.
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
    # The nudge's id moves back, so a rollback leaves rung 2 exactly as it found it.
    op.execute(
        """
        UPDATE communications
        SET external_message_id = in_reply_to_message_id
        WHERE template_key = 'borrower_secure_upload_nudge'
          AND in_reply_to_message_id IS NOT NULL
          AND external_message_id IS NULL
          AND deleted_at IS NULL
        """
    )
    op.execute("DROP INDEX IF EXISTS ix_communications_unread")
    op.drop_column("communications", "read_at")
    op.drop_column("communications", "is_important")
    op.drop_column("communications", "in_reply_to_message_id")
