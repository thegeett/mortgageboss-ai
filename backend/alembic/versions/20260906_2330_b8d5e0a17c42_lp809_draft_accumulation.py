"""LP-809 — a document request that accumulates instead of multiplying.

THE PROBLEM THIS TABLE SOLVES. A processor requests documents on Tuesday, three more findings land
on Wednesday, and the borrower should receive ONE email listing everything rather than four emails
over two days each asking for one thing. So a draft's contents are a SET of needs that grows and
shrinks, and its body is regenerated from that set. ``communications.needs_item_id`` cannot express
that — it holds one need, which is the right shape for a sent single-purpose message and the wrong
one for a draft still collecting. It is unchanged.

BOTH SIDES CASCADE, deliberately differing from ``needs_item_id``'s SET NULL. That column preserves
the historical fact that a SENT message concerned a need that has since gone. A draft has no history
to preserve, and a need that no longer exists must not still be listed in an email.

THE PARTIAL UNIQUE INDEX is what makes "the open draft" a thing that exists. Without it, two
near-simultaneous requests each find no draft, each create one, and the file has two half-populated
drafts with no basis for choosing between them — the same shape as the duplicate needs items LP-801's
review found, reached by another route. Scoped to ``(loan_file_id, template_key)`` rather than to
drafts in general because a file may legitimately hold more than one kind of draft: LP-818 adds
needs-less REPLY drafts, and one per thread is the shape that will want. When it lands, this index
needs revisiting — a reply draft has no template key to distinguish it by, and NULL keys do not
collide in a unique index, so LP-818 will pass through this constraint without being governed by it.
Recorded here rather than discovered there.

``template_key`` / ``template_version`` on ``communications``: `phase4.md` §6 requires the record to
capture "template + version" beside the rendered body, because that record is evidence. LP-817 pins
each version to a content hash (ADR-401) so a version names exactly one set of words — which is only
worth anything if the version used is stored. No other M1 ticket has a migration to add them
(LP-811 is explicitly migration-free, LP-810's is the prose cache), so they belong here, with the
ticket that first renders a template into a communication.

READONLY VIEWS. ``communication_needs_items`` holds two foreign keys and nothing else — no free
text, no content — so it is exposed whole. ``readonly.communications`` is rebuilt to carry the two
new columns: a template key and a version name a file in this repo and reveal nothing about a
borrower, and leaving them out would make it impossible to ask which template a file's mail went out
under. The body, subject, sender and recipient stay dropped, exactly as C7 left them.

Hand-written, like every migration against this schema.

Revision ID: b8d5e0a17c42
Revises: e4a1c7d90b3f
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b8d5e0a17c42"  # pragma: allowlist secret
down_revision: str | None = "e4a1c7d90b3f"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COMMUNICATIONS_VIEW = """
    CREATE VIEW readonly.communications AS
    SELECT id, loan_file_id, direction, channel, status, needs_item_id,
           initiated_by_user_id, external_message_id, sent_at,
           template_key, template_version,
           readonly.scrub(error_detail) AS error_detail,
           created_at, updated_at, deleted_at
    FROM public.communications
    """

_JOIN_VIEW = """
    CREATE VIEW readonly.communication_needs_items AS
    SELECT communication_id, needs_item_id, created_at, updated_at
    FROM public.communication_needs_items
    """

_GRANT = """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON readonly.communications TO mbai_readonly';
            EXECUTE 'GRANT SELECT ON readonly.communication_needs_items TO mbai_readonly';
        END IF;
    END
    $$;
    """


def upgrade() -> None:
    op.add_column("communications", sa.Column("template_key", sa.String(length=64), nullable=True))
    op.add_column(
        "communications", sa.Column("template_version", sa.String(length=64), nullable=True)
    )
    op.create_table(
        "communication_needs_items",
        sa.Column("communication_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("needs_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["communication_id"], ["communications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["needs_item_id"], ["needs_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("communication_id", "needs_item_id"),
    )
    op.create_index(
        "ix_communication_needs_items_needs_item_id",
        "communication_needs_items",
        ["needs_item_id"],
    )
    # One open draft per (file, template kind). PARTIAL so it governs drafts only — a file
    # accumulates hundreds of sent messages and they must not collide with each other.
    op.create_index(
        "uq_communications_open_draft",
        "communications",
        ["loan_file_id", "template_key"],
        unique=True,
        postgresql_where=sa.text("status = 'draft' AND deleted_at IS NULL"),
    )
    op.execute("DROP VIEW IF EXISTS readonly.communications")
    op.execute(_COMMUNICATIONS_VIEW)
    op.execute("DROP VIEW IF EXISTS readonly.communication_needs_items")
    op.execute(_JOIN_VIEW)
    op.execute(_GRANT)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS readonly.communication_needs_items")
    op.execute("DROP VIEW IF EXISTS readonly.communications")
    op.drop_index("uq_communications_open_draft", table_name="communications")
    op.drop_index(
        "ix_communication_needs_items_needs_item_id", table_name="communication_needs_items"
    )
    op.drop_table("communication_needs_items")
    op.drop_column("communications", "template_version")
    op.drop_column("communications", "template_key")
    # The view goes back to its pre-LP-809 shape, without the two columns the table no longer has.
    op.execute("""
        CREATE VIEW readonly.communications AS
        SELECT id, loan_file_id, direction, channel, status, needs_item_id,
               initiated_by_user_id, external_message_id, sent_at,
               readonly.scrub(error_detail) AS error_detail,
               created_at, updated_at, deleted_at
        FROM public.communications
        """)
