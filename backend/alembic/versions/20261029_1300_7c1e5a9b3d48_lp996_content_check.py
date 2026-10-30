"""LP-996 — the pre-send content check's override, on the evidence record.

`communication_evidence.content_check_grounds`: the grounds the check found (`rate`, `commitment`,
`payment_routing`, comma-separated) when the processor sent anyway. `content_check_override_note`:
her note saying why. Both null on every other row, including every row before this migration.

Not `guardrail_fired`: that column is the AI drafter's guard.

`readonly.communication_evidence` exposes the grounds (a fixed vocabulary, names nobody) and NOT the
note, which is free text a processor typed about one borrower's email — excluded like the bodies.
The view is LP-821's upgrade body plus the one column.

Hand-written, like every migration against this schema.

Revision ID: 7c1e5a9b3d48
Revises: 4b7e2c9d1a63
Create Date: 2026-10-29 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c1e5a9b3d48"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "4b7e2c9d1a63"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GRANT = """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON readonly.communication_evidence TO mbai_readonly';
        END IF;
    END $$;
"""


def upgrade() -> None:
    op.add_column(
        "communication_evidence", sa.Column("content_check_grounds", sa.Text(), nullable=True)
    )
    op.add_column(
        "communication_evidence",
        sa.Column("content_check_override_note", sa.Text(), nullable=True),
    )
    op.execute("DROP VIEW IF EXISTS readonly.communication_evidence")
    op.execute(
        """
        CREATE VIEW readonly.communication_evidence AS
        SELECT id, loan_file_id, communication_id, event, recorded_at,
               approver_user_id, template_key, template_version,
               guardrail_fired, failure_reason, model_id, prompt_version,
               readonly.scrub(auth_verdicts::text)::jsonb AS auth_verdicts,
               jsonb_array_length(attachment_manifest) AS attachment_count,
               (body_composed IS NOT NULL) AS has_composed_draft,
               (body_as_sent IS DISTINCT FROM body_composed) AS was_edited,
               content_check_grounds
        FROM public.communication_evidence
        """
    )
    op.execute(_GRANT)


def downgrade() -> None:
    """Back to LP-821's view, then drop both columns. A recorded override note is lost."""
    op.execute("DROP VIEW IF EXISTS readonly.communication_evidence")
    op.execute(
        """
        CREATE VIEW readonly.communication_evidence AS
        SELECT id, loan_file_id, communication_id, event, recorded_at,
               approver_user_id, template_key, template_version,
               guardrail_fired, failure_reason, model_id, prompt_version,
               readonly.scrub(auth_verdicts::text)::jsonb AS auth_verdicts,
               jsonb_array_length(attachment_manifest) AS attachment_count,
               (body_composed IS NOT NULL) AS has_composed_draft,
               (body_as_sent IS DISTINCT FROM body_composed) AS was_edited
        FROM public.communication_evidence
        """
    )
    op.execute(_GRANT)
    op.drop_column("communication_evidence", "content_check_override_note")
    op.drop_column("communication_evidence", "content_check_grounds")
