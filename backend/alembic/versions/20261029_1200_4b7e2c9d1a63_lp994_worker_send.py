"""LP-994 — sending runs in the worker.

`communications.status` gains `sending`: the worker has claimed the row and may be calling the mail
provider. Written before the call, so a crash leaves `sending`, never a second email.

`communications.send_requested_at`: when a person clicked Send with `transmit=true`. The worker only
sends a row that has it, which is what keeps LP-815's automatic replies (`queued`, never requested
by anybody) from going out. NULL on every existing row, which is correct: nothing was ever sent this
way before.

`communications.raw_storage_path`: where the exact copy of the sent email is
(`outbound/<communication_id>.eml` in the mail storage).

`send_requested_at` is exposed raw in `readonly.communications`: a time, names nobody, and LP-998
reads it to check a staging send. `raw_storage_path` is NOT exposed: it points at the whole sent
email (body, upload link), the reason `inbound_messages.raw_storage_path` is excluded too. The view
is copied from LP-853's UPGRADE body (the live shape) plus the one column.

Hand-written, like every migration against this schema.

Revision ID: 4b7e2c9d1a63
Revises: 2d577c6ed90c
Create Date: 2026-10-29 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4b7e2c9d1a63"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "2d577c6ed90c"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES_AFTER = ("draft", "queued", "sending", "sent", "delivered", "failed", "received")
_STATUSES_BEFORE = ("draft", "queued", "sent", "delivered", "failed", "received")

_GRANT = """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON readonly.communications TO mbai_readonly';
        END IF;
    END $$;
"""


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def _status_check(values: tuple[str, ...]) -> None:
    op.execute("ALTER TABLE communications DROP CONSTRAINT ck_communications_communicationstatus")
    op.execute(
        "ALTER TABLE communications ADD CONSTRAINT ck_communications_communicationstatus "
        f"CHECK ({_in('status', values)})"
    )


def upgrade() -> None:
    _status_check(_STATUSES_AFTER)
    op.add_column(
        "communications",
        sa.Column("send_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("communications", sa.Column("raw_storage_path", sa.Text(), nullable=True))
    op.execute("DROP VIEW IF EXISTS readonly.communications")
    op.execute(
        """
        CREATE VIEW readonly.communications AS
        SELECT id, loan_file_id, direction, channel, status, needs_item_id,
               initiated_by_user_id, external_message_id, inbound_message_id, sent_at,
               template_key, template_version, is_important, read_at, party, body_format,
               send_requested_at,
               readonly.scrub(error_detail) AS error_detail,
               created_at, updated_at, deleted_at
        FROM public.communications
        """
    )
    op.execute(_GRANT)


def downgrade() -> None:
    """Back to the LP-853 view and the status list without `sending`.

    Rows the older code cannot describe are rewritten, not left to fail the constraint:
    - `sending`: the email may have gone, so it becomes `failed` with a "Not confirmed" note a person
      can read, never `queued` (which nothing would send, and which would read as an automatic reply).
    - `queued` with `send_requested_at`: a person's Send the worker had not taken yet. Without the
      column it would look like an automatic reply, so it becomes `failed`, "Not sent". Its needs stay
      requested; the processor sees the failed message and sends again.
    """
    op.execute(
        "UPDATE communications SET status = 'failed', "
        "error_detail = coalesce(error_detail, 'Not confirmed: rolled back while sending. "
        "Check before sending again.') WHERE status = 'sending'"
    )
    op.execute(
        "UPDATE communications SET status = 'failed', "
        "error_detail = 'Not sent: rolled back before the worker sent it.' "
        "WHERE status = 'queued' AND send_requested_at IS NOT NULL"
    )
    op.execute("DROP VIEW IF EXISTS readonly.communications")
    op.execute(
        """
        CREATE VIEW readonly.communications AS
        SELECT id, loan_file_id, direction, channel, status, needs_item_id,
               initiated_by_user_id, external_message_id, inbound_message_id, sent_at,
               template_key, template_version, is_important, read_at, party, body_format,
               readonly.scrub(error_detail) AS error_detail,
               created_at, updated_at, deleted_at
        FROM public.communications
        """
    )
    op.execute(_GRANT)
    op.drop_column("communications", "raw_storage_path")
    op.drop_column("communications", "send_requested_at")
    _status_check(_STATUSES_BEFORE)
