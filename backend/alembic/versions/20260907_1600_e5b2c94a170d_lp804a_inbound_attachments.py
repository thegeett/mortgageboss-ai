"""LP-804a — the inventory of what arrived attached to an inbound message.

ONE ROW PER PART THAT LOOKS LIKE A FILE, recorded before anything decides whether it is safe. The
bytes are NOT copied here: the raw `.eml` in S3 already holds them, and a second copy of a borrower's
document is a second thing to secure, retain and eventually destroy. This table is the inventory —
what the part claimed to be, how big it is, what its bytes hash to, and how deep inside forwarded
wrappers it was found.

THE SAFETY COLUMNS SHIP EMPTY AND THAT IS THE POINT. `sniffed_content_type`, `scan_verdict`,
`safety_state` and `derived_storage_path` belong to LP-804b, which sniffs magic bytes, sanitises PDFs
and rasterises. They are created here so that ticket is a service plus a backfill rather than a
migration against a table with live rows — and so the DEFAULT is visible in the schema:
`safety_state = 'pending'`, which is neither safe nor unsafe. Nothing downstream may read a pending
attachment as a document, and the malware scan (INFRA-2) is asynchronous, so pending is a state that
genuinely persists rather than a momentary one.

UNIQUE (inbound_message_id, sha256) — CONTENT-ADDRESSED, not keyed on the filename. A borrower
forwarding a thread sends the same PDF under `statement.pdf`, `statement (1).pdf` and
`ATT00001.pdf`, and a processor should be offered it once.

THE READONLY VIEW DROPS BOTH FILENAMES AND THE STORAGE PATHS. `filename_original` is attacker-
controlled text a stranger wrote; the normalised form still carries whatever the sender chose to
call their own document, which on a mortgage file is routinely a name and a date. The view answers
how many attachments arrived, at what depth, of what claimed type, how big, and what safety and
disposition they reached — and none of the content.

`sha256` is EXPOSED. It is a content address with no preimage, it is how a scan verdict is matched
back to an object, and it is the only way to ask "did this same file arrive twice" from the readonly
side.

Hand-written, like every migration against this schema.

Revision ID: e5b2c94a170d
Revises: d1a8f37c0e59
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e5b2c94a170d"  # pragma: allowlist secret
down_revision: str | None = "d1a8f37c0e59"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SAFETY_STATES = ("pending", "safe", "quarantined", "unsupported")
_DISPOSITIONS = ("pending", "accepted", "rejected", "duplicate")

_VIEW = """
    CREATE VIEW readonly.inbound_attachments AS
    SELECT id, inbound_message_id, document_id,
           declared_content_type, sniffed_content_type,
           size_bytes, sha256, nesting_depth,
           scan_verdict, safety_state, disposition,
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
    op.create_table(
        "inbound_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("inbound_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename_original", sa.Text(), nullable=True),
        sa.Column("filename_normalized", sa.String(length=256), nullable=True),
        sa.Column("declared_content_type", sa.String(length=64), nullable=True),
        sa.Column("sniffed_content_type", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("nesting_depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scan_verdict", sa.String(length=64), nullable=True),
        sa.Column("safety_state", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("derived_storage_path", sa.Text(), nullable=True),
        sa.Column("disposition", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["inbound_message_id"], ["inbound_messages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "inbound_message_id", "sha256", name="uq_inbound_attachments_message_sha256"
        ),
    )
    op.create_index(
        "ix_inbound_attachments_inbound_message_id", "inbound_attachments", ["inbound_message_id"]
    )

    # ADR-037 — VARCHAR + CHECK for each enum, so a new state is a migration and not a type rewrite.
    for column, values in (("safety_state", _SAFETY_STATES), ("disposition", _DISPOSITIONS)):
        joined = ", ".join(f"'{value}'" for value in values)
        op.execute(
            f"ALTER TABLE inbound_attachments ADD CONSTRAINT ck_inbound_attachments_{column} "
            f"CHECK ({column} IN ({joined}))"
        )

    op.execute("DROP VIEW IF EXISTS readonly.inbound_attachments")
    op.execute(_VIEW)
    op.execute(_GRANT)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS readonly.inbound_attachments")
    op.drop_table("inbound_attachments")
