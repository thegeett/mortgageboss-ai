"""LP-UI-033 — a processor's verdict on one extracted field.

The reviewer's keyboard loop (`Enter` accept, `R` reject, `E` correct) needs
somewhere to put the decision. This is it: one row per (extraction, field), beside
the extracted value rather than on top of it.

WHY NOT WRITE THE CORRECTION INTO `extracted_data`. Because "what did the model
actually say?" is the question every accuracy investigation starts from — the
LP-508 distrust ledger is entirely that question — and overwriting the value to
record a correction destroys the evidence to store the verdict.

WHY KEYED ON THE EXTRACTION RATHER THAN THE DOCUMENT. A re-extraction produces a
new version with possibly different values. A verdict recorded against the old one
must not silently vouch for the new, so the ON DELETE CASCADE from `extractions`
means a superseded version's reviews go with it and the fields return to
unreviewed. That costs a processor a second pass; the alternative costs an
underwriter a wrong file.

THE UNIQUE INDEX INCLUDES `deleted_at`, which makes it a partial-uniqueness
approximation rather than a true partial index: two soft-deleted rows with the
same timestamp would collide. That cannot happen through the service (a revert
soft-deletes exactly one live row), and the ordinary Postgres alternative — a
partial index `WHERE deleted_at IS NULL` — is used here instead, matching
`uq_extractions_document_id_current`.

Hand-written. `--autogenerate` proposes eighteen destructive operations against
this schema, so every migration here is written by hand.

Revision ID: c3f81a24e7b9
Revises: b7c14e29d3af
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

_SCHEMA = "readonly"

# EXPOSED, less the two columns a person types into.
#
# `corrected_value` is whatever the processor typed, on whatever field they were
# correcting — correct an SSN field and the correction IS an SSN. `note` is free
# prose about a specific borrower's document. Both are dropped rather than
# scrubbed: scrubbing catches the shapes it knows, and a corrected value is by
# construction the one place a raw identifier arrives by hand.
#
# What remains answers the questions this table exists for: how often fields are
# corrected, which fields get rejected, who reviewed what and when. That is the
# useful half, and none of it is borrower content.
_VIEW = f"""
    CREATE VIEW {_SCHEMA}.field_reviews AS
    SELECT id, extraction_id, field_key, verdict, reviewed_by_user_id,
           (corrected_value IS NOT NULL) AS has_corrected_value,
           (note IS NOT NULL) AS has_note,
           created_at, updated_at, deleted_at
    FROM public.field_reviews
    """

_GRANT = f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON {_SCHEMA}.field_reviews TO mbai_readonly';
        END IF;
    END
    $$;
    """

revision: str = "c3f81a24e7b9"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "b7c14e29d3af"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CONSTRAINT = "ck_activity_logs_activitytype"

# `activity_type` is a VARCHAR + CHECK (ADR-037), so two new values are a constraint
# swap. The set is written out in model-definition order rather than read from the
# database: a migration that derives its own target from the live schema cannot be
# reviewed, and cannot run against a database that is already wrong.
_OLD_ACTIVITY_TYPES = (
    "file_created",
    "file_updated",
    "file_deleted",
    "status_changed",
    "document_uploaded",
    "document_processed",
    "document_type_overridden",
    "document_replaced",
    "document_staleness_resolved",
    "finding_resolved",
    "finding_undone",
    "verification_run",
    "dti_overridden",
    "ltv_overridden",
    "calculator_overridden",
    "lender_overlay_updated",
    "needs_item_created",
    "needs_item_satisfied",
    "needs_item_confirmed",
    "needs_item_adjusted",
    "needs_item_dismissed",
    "needs_item_waived",
    "communication_sent",
    "communication_received",
    "note_added",
)
_NEW_ACTIVITY_TYPES = (
    *_OLD_ACTIVITY_TYPES[:9],
    "field_reviewed",
    "field_review_reverted",
    *_OLD_ACTIVITY_TYPES[9:],
)


def _swap_check(values: tuple[str, ...]) -> None:
    joined = ", ".join(f"'{value}'" for value in values)
    op.execute(f"ALTER TABLE activity_logs DROP CONSTRAINT {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE activity_logs ADD CONSTRAINT {_CONSTRAINT} "
        f"CHECK (activity_type IN ({joined}))"
    )


def upgrade() -> None:
    _swap_check(_NEW_ACTIVITY_TYPES)
    op.create_table(
        "field_reviews",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "extraction_id",
            sa.UUID(),
            sa.ForeignKey("extractions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("field_key", sa.String(100), nullable=False),
        sa.Column("verdict", sa.String(50), nullable=False),
        sa.Column("corrected_value", sa.String(1000), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "reviewed_by_user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_field_reviews_extraction_id", "field_reviews", ["extraction_id"])
    # One LIVE verdict per field per extraction; any number of reverted ones.
    op.create_index(
        "uq_field_reviews_extraction_field_active",
        "field_reviews",
        ["extraction_id", "field_key"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.execute(_VIEW)
    op.execute(_GRANT)


def downgrade() -> None:
    _swap_check(_OLD_ACTIVITY_TYPES)
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.field_reviews")
    op.drop_index("uq_field_reviews_extraction_field_active", table_name="field_reviews")
    op.drop_index("ix_field_reviews_extraction_id", table_name="field_reviews")
    op.drop_table("field_reviews")
