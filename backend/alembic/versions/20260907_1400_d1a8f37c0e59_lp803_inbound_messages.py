"""LP-803 — inbound messages, as received and not yet understood.

THE ROW EXISTS BEFORE ANYONE KNOWS WHOSE IT IS. Ingest pulls the raw `.eml`, records what SES said,
and stops. Which loan file — and therefore which company — is LP-805's, in the one resolver allowed
to derive `company_id` from a resolved loan file. So both columns are NULLABLE here and both are
filled by routing. `phase4.md` describes this table as company-owned; the standing tenancy rule is
what forces the departure, because ingest cannot resolve without becoming a second place that does.

NULLS NOT DISTINCT ON THE DEDUP INDEX, and it is the whole ticket. Postgres treats NULLs as distinct
in a unique index by default, so an unrouted message — company_id NULL, which is the state EVERY
message starts in — would never collide with another, and the same delivery twice would produce two
rows. The ticket's own acceptance criterion is "the same message delivered twice produces exactly
one row", and the default behaviour fails it in precisely the state that matters.

WHY THE SCOPE IS (company_id, ingest_key) rather than ingest_key alone. `ingest_key` falls back to
the `Message-ID` header, which the SENDER writes. Globally unique, anyone could suppress another
company's message by forging a collision. Scoped per company they cannot. The window where that is
not yet true is the unrouted set, and it is narrow: the key prefers the SES message id, which SES
assigns and a sender cannot choose, so the header fallback is reached only when there is no SES id —
which today means the dev injector.

THE READONLY VIEW DROPS SUBJECT, ADDRESSES AND THE STORAGE PATH. A subject line is written by a
borrower about their own loan; `from_address` and `to_addresses` identify people. The view answers
the operational questions — how many arrived, how they authenticated, what routing did with them,
how many were bounces — and none of the content. `readonly.communications` already drops the same
family for the outbound direction (C7: "the envelope is enough to debug the comms pipeline; the
content never is").

NO SUBQUERY IN THE SELECT LIST, EITHER. The first version counted recipients with
`cardinality(ARRAY(SELECT ...))`, which is valid SQL and silently defeated the drift guard: that
check finds the select list by taking the LAST `SELECT` before the first `FROM`, so a nested one
truncated the list and every column in this table read as unexposed. `jsonb_array_length` says the
same thing with no subquery. A guard that can be disabled by ordinary SQL is worth knowing about —
recorded here rather than worked around quietly.

NO `has_subject` BOOLEAN, and the omission is deliberate rather than an oversight.
`tests/test_readonly_query.py` asserts over the view TEXT that certain columns are never NAMED in any
select list — crude on purpose, because a per-column check is satisfied by a column appearing in a
predicate about itself. `(subject IS NOT NULL) AS has_subject` names it, so the boolean goes rather
than the guarantee. Same call, for the same reason, as LP-822's dropped exemplar count.

`auth_verdicts` is EXPOSED, scrubbed. It is a closed vocabulary of SES verdict strings, and it is the
one field an operator genuinely needs when asking why a message went to triage.

Hand-written, like every migration against this schema.

Revision ID: d1a8f37c0e59
Revises: c9f1a4b73e08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d1a8f37c0e59"  # pragma: allowlist secret
down_revision: str | None = "c9f1a4b73e08"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROUTING_STATES = ("pending", "routed", "unrouted", "quarantined", "rejected")

_VIEW = """
    CREATE VIEW readonly.inbound_messages AS
    SELECT id, company_id, loan_file_id,
           readonly.scrub(auth_verdicts::text)::jsonb AS auth_verdicts,
           routing_state, routing_signal, routing_confidence,
           is_dsn, is_auto_reply,
           (raw_storage_path IS NOT NULL) AS has_raw_stored,
           jsonb_array_length(to_addresses) AS recipient_count,
           received_at, created_at, updated_at, deleted_at
    FROM public.inbound_messages
    """

_GRANT = """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON readonly.inbound_messages TO mbai_readonly';
        END IF;
    END
    $$;
    """


def upgrade() -> None:
    op.create_table(
        "inbound_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("loan_file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ingest_key", sa.String(length=64), nullable=False),
        sa.Column("ses_message_id", sa.String(length=256), nullable=True),
        sa.Column("message_id", sa.String(length=256), nullable=True),
        sa.Column("in_reply_to", sa.String(length=256), nullable=True),
        sa.Column("references", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("from_address", sa.String(length=256), nullable=True),
        sa.Column("to_addresses", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_storage_path", sa.Text(), nullable=True),
        sa.Column("auth_verdicts", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("routing_state", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("routing_signal", sa.String(length=64), nullable=True),
        sa.Column("routing_confidence", sa.Float(), nullable=True),
        sa.Column("is_dsn", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_auto_reply", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["loan_file_id"], ["loan_files.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inbound_messages_company_id", "inbound_messages", ["company_id"])
    op.create_index("ix_inbound_messages_loan_file_id", "inbound_messages", ["loan_file_id"])
    op.create_index("ix_inbound_messages_routing_state", "inbound_messages", ["routing_state"])

    # Raw DDL: NULLS NOT DISTINCT is the point of this index and alembic's helper cannot express it.
    op.execute(
        "CREATE UNIQUE INDEX uq_inbound_messages_ingest_key "
        "ON inbound_messages (company_id, ingest_key) NULLS NOT DISTINCT"
    )

    # ADR-037 — VARCHAR + CHECK for an enum, so a new state is a migration and not a type rewrite.
    joined = ", ".join(f"'{value}'" for value in _ROUTING_STATES)
    op.execute(
        "ALTER TABLE inbound_messages ADD CONSTRAINT ck_inbound_messages_routingstate "
        f"CHECK (routing_state IN ({joined}))"
    )

    op.execute("DROP VIEW IF EXISTS readonly.inbound_messages")
    op.execute(_VIEW)
    op.execute(_GRANT)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS readonly.inbound_messages")
    op.drop_table("inbound_messages")
