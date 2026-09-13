"""LP-853 — a message records whether its body is plain text or the processor's own HTML.

Revision ID: b8d1f6e40c25
Revises: a7e2b4c81f09
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8d1f6e40c25"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "a7e2b4c81f09"  # pragma: allowlist secret
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
    """Add `body_format`, backfill every existing row `plain`, and expose it.

    THE BACKFILL IS NOT A GUESS. Before this migration exactly two things wrote
    `communications.body`: `_regenerate`, from the template, and `send_draft`, storing what the
    processor sent. There has never been a save-without-sending path — `tests/api/
    test_no_draft_save_route.py` has failed the build over it since LP-849 — so every body that
    exists is plain text. `plain` is what these rows ARE, not a default chosen for them.

    NOT NULL WITH A SERVER DEFAULT, KEPT. The default is what makes the compatibility guarantee run
    in both directions: new code reading old rows is the easy half, and the half that fails harder
    is old code writing new rows, which is what a ROLLBACK produces. An INSERT from a build that
    predates this column omits `body_format` entirely, and without the server default that INSERT
    raises rather than degrading — a message that cannot be written is worse than one whose format
    has to be assumed, and `plain` is the correct assumption for anything the old code wrote.

    EXPOSED RAW in the readonly view, like `party` and unlike the free text on this table.
    `readonly.scrub` removes identifiers from prose; this is one of two fixed values and names
    nobody. It is also the column that answers "how often do processors rewrite what we drafted",
    which is a fact about how a company works.
    """
    op.add_column(
        "communications",
        sa.Column(
            "body_format",
            sa.String(length=32),
            nullable=False,
            server_default="plain",
        ),
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


def downgrade() -> None:
    """Drop the column, and with it every record of which bodies a processor wrote.

    STATED RATHER THAN SILENT: this is lossy in a way the upgrade is not. An HTML body stays in
    `body` and nothing afterwards can tell it apart from a generated one, so `_regenerate` will
    rewrite it on the next request. That is the pre-LP-853 behaviour, which is what a downgrade
    asks for, and it is the reason the save route goes away with the same deploy.
    """
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
    op.drop_column("communications", "body_format")
