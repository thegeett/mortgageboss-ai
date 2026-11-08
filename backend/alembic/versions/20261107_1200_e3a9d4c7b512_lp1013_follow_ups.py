"""LP-1013 — automatic follow-ups on an outbound email.

On `communications`:

- `follow_up_status` (`off` by default, `on`, `paused`, `finished`, `stopped`), with its CHECK.
- `follow_up_interval_days` (default 3, 1-30) and `follow_up_max_auto` (default 2, 0-10): her two
  settings. `follow_up_auto_sent`: automatic reminders sent so far.
- `follow_up_clock_at`: when the interval counts from (the Send, the last reminder, or the reply on
  resume). `follow_up_paused_at`: when the recipient replied.
- `follow_up_of_id`: on a reminder, the email it follows up (SET NULL, indexed).
- `follow_up_time` and `follow_up_tz` (amendment, 11-07): the time of day a reminder goes, in an IANA
  time zone. Null while `off`; a CHECK requires both on any other status.

Every existing row gets `off` and the defaults, which is what it is: nothing followed up before.

All nine are exposed raw in `readonly.communications`: settings, counts, times and an id, naming
nobody. The view is LP-994's plus these columns.

Hand-written, like every migration against this schema.

Revision ID: e3a9d4c7b512
Revises: c4f7a92e1b36
Create Date: 2026-11-07 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3a9d4c7b512"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "c4f7a92e1b36"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = ("off", "on", "paused", "finished", "stopped")

_GRANT = """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON readonly.communications TO mbai_readonly';
        END IF;
    END $$;
"""


def upgrade() -> None:
    op.add_column(
        "communications",
        sa.Column("follow_up_status", sa.String(length=32), server_default="off", nullable=False),
    )
    op.execute(
        "ALTER TABLE communications ADD CONSTRAINT ck_communications_followupstatus "
        "CHECK (follow_up_status IN (" + ", ".join(f"'{v}'" for v in _STATUSES) + "))"
    )
    op.add_column(
        "communications",
        sa.Column("follow_up_interval_days", sa.Integer(), server_default="3", nullable=False),
    )
    op.add_column(
        "communications",
        sa.Column("follow_up_max_auto", sa.Integer(), server_default="2", nullable=False),
    )
    op.add_column(
        "communications",
        sa.Column("follow_up_auto_sent", sa.Integer(), server_default="0", nullable=False),
    )
    op.execute(
        "ALTER TABLE communications ADD CONSTRAINT "
        "ck_communications_follow_up_interval_days_range "
        "CHECK (follow_up_interval_days BETWEEN 1 AND 30)"
    )
    op.execute(
        "ALTER TABLE communications ADD CONSTRAINT ck_communications_follow_up_max_auto_range "
        "CHECK (follow_up_max_auto BETWEEN 0 AND 10)"
    )
    op.add_column(
        "communications",
        sa.Column("follow_up_clock_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "communications",
        sa.Column("follow_up_paused_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("communications", sa.Column("follow_up_time", sa.Time(), nullable=True))
    op.add_column("communications", sa.Column("follow_up_tz", sa.String(length=64), nullable=True))
    op.execute(
        "ALTER TABLE communications ADD CONSTRAINT ck_communications_follow_up_time_set "
        "CHECK (follow_up_status = 'off' "
        "OR (follow_up_time IS NOT NULL AND follow_up_tz IS NOT NULL))"
    )
    op.add_column("communications", sa.Column("follow_up_of_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_communications_follow_up_of_id_communications",
        "communications",
        "communications",
        ["follow_up_of_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_communications_follow_up_of_id", "communications", ["follow_up_of_id"])
    op.execute("DROP VIEW IF EXISTS readonly.communications")
    op.execute(
        """
        CREATE VIEW readonly.communications AS
        SELECT id, loan_file_id, direction, channel, status, needs_item_id,
               initiated_by_user_id, external_message_id, inbound_message_id, sent_at,
               template_key, template_version, is_important, read_at, party, body_format,
               send_requested_at,
               follow_up_status, follow_up_interval_days, follow_up_max_auto,
               follow_up_auto_sent, follow_up_clock_at, follow_up_paused_at, follow_up_of_id,
               follow_up_time, follow_up_tz,
               readonly.scrub(error_detail) AS error_detail,
               created_at, updated_at, deleted_at
        FROM public.communications
        """
    )
    op.execute(_GRANT)


def downgrade() -> None:
    """Back to LP-994's view and columns. Reminders already sent stay as ordinary sent emails."""
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
    # Dropping a column drops its own CHECK, foreign key and index. Named by hand rather than with
    # `op.drop_constraint`, which applies the naming convention again (`ck_communications_ck_...`,
    # the LP-912 trap) and fails.
    op.execute(
        "ALTER TABLE communications "
        "DROP COLUMN follow_up_tz, DROP COLUMN follow_up_time, "
        "DROP COLUMN follow_up_of_id, DROP COLUMN follow_up_paused_at, "
        "DROP COLUMN follow_up_clock_at, DROP COLUMN follow_up_auto_sent, "
        "DROP COLUMN follow_up_max_auto, DROP COLUMN follow_up_interval_days, "
        "DROP COLUMN follow_up_status"
    )
