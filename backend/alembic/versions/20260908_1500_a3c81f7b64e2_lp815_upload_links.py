"""LP-815 — the expiring upload link, and a fourth document provenance.

WHY THE LINK EXISTS. `phase4.md` §6: GLBA Safeguards 16 CFR 314.4(c)(3) requires customer
information to be encrypted in transit over external networks, so outbound email must not carry NPI
— it carries an authenticated, expiring link instead. Opportunistic STARTTLS is not a defensible
compensating control on its own.

THE TOKEN IS STORED AS A HASH, unlike `loan_files.inbox_token`. ADR-397 is explicit that an inbox
address is a bearer credential that never expires, and it has to be stored in the clear because a
borrower types it into their mail client. Nobody has to recognise an upload token, so the plaintext
lives only in the moment it is minted and in the message carrying it: what this table holds cannot
be used to reach anything.

THE READONLY VIEW DROPS `token_hash`, `recipient_email` AND `purpose`. The hash because exposing the
verifier of a capability through the analytics path is the opposite of the reason it is hashed;
the address because it names a borrower; `purpose` because it is prose that ends up naming one.

`documents.upload_source` gains `secure_link`. The CHECK is recreated from its own COMPLETE tuple
(ADR-037) rather than altered — a swap that lists three values because it forgot the fourth is the
failure this style exists to make visible.

Hand-written, like every migration against this schema.

Revision ID: a3c81f7b64e2
Revises: f2b6c48a17d9
Create Date: 2026-09-08 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3c81f7b64e2"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "f2b6c48a17d9"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The COMPLETE tuple, both times. Written out rather than derived from the enum so the migration
#: says what the database will hold on the day it ran, and does not change meaning when the enum does.
_SOURCES_AFTER = ("user_upload", "borrower_inbox", "mismo_import", "secure_link")
_SOURCES_BEFORE = ("user_upload", "borrower_inbox", "mismo_import")

#: `communications.status` gains `queued` — composed automatically, awaiting a transport. NOT
#: `draft`: a draft is the document request a processor reviews, there is a partial unique index
#: enforcing one open draft per (file, template), and `get_open_draft` reads by that status. An
#: automatic reply parked as a DRAFT would sit in a state whose meaning is "somebody still has to
#: look at this" with nobody ever asked.
_STATUSES_AFTER = ("draft", "queued", "sent", "delivered", "failed", "received")
_STATUSES_BEFORE = ("draft", "sent", "delivered", "failed", "received")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def _check(values: tuple[str, ...]) -> str:
    return _in("upload_source", values)


_LINKS_VIEW = """
    CREATE VIEW readonly.upload_links AS
    SELECT id, loan_file_id, expires_at, revoked_at, uses, max_uses, last_used_at,
           (recipient_email IS NOT NULL) AS was_addressed,
           created_at, updated_at, deleted_at
    FROM public.upload_links
    """

_GRANT = """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON readonly.upload_links TO mbai_readonly';
        END IF;
    END
    $$;
    """


def upgrade() -> None:
    op.create_table(
        "upload_links",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "loan_file_id",
            sa.UUID(),
            sa.ForeignKey("loan_files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recipient_email", sa.String(128), nullable=True),
        sa.Column("uses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_uses", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("uq_upload_links_token_hash", "upload_links", ["token_hash"], unique=True)
    op.create_index("ix_upload_links_loan_file_id", "upload_links", ["loan_file_id"])

    # RAW SQL, NOT `op.create_check_constraint`. This metadata carries a naming convention
    # (`ck_%(table_name)s_%(constraint_name)s`), so passing the constraint's real name to the helper
    # produces `ck_documents_ck_documents_uploadsource` — it built the wrong name and the DROP that
    # preceded it failed loudly, which is the good outcome. Naming it outright is what the existing
    # constraint's own name is.
    op.execute("ALTER TABLE documents DROP CONSTRAINT ck_documents_uploadsource")
    op.execute(
        "ALTER TABLE documents ADD CONSTRAINT ck_documents_uploadsource "
        f"CHECK ({_check(_SOURCES_AFTER)})"
    )

    op.execute("ALTER TABLE communications DROP CONSTRAINT ck_communications_communicationstatus")
    op.execute(
        "ALTER TABLE communications ADD CONSTRAINT ck_communications_communicationstatus "
        f"CHECK ({_in('status', _STATUSES_AFTER)})"
    )

    # LP-815 — `is_bulk`: from a mailing list or a bulk sender. A separate fact from `is_auto_reply`,
    # and the one that governs whether the nudge may reply at all.
    op.add_column(
        "inbound_messages",
        sa.Column("is_bulk", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # The view is rebuilt to carry it. COPIED FROM LP-803's UPGRADE body, which is the shape the
    # database has — its downgrade body is the pre-LP-803 shape, and LP-806 lost three columns to
    # exactly that mistake.
    op.execute("DROP VIEW IF EXISTS readonly.inbound_messages")
    op.execute(
        """
        CREATE VIEW readonly.inbound_messages AS
        SELECT id, company_id, loan_file_id,
               readonly.scrub(auth_verdicts::text)::jsonb AS auth_verdicts,
               routing_state, routing_signal, routing_confidence,
               is_dsn, is_auto_reply, is_bulk,
               (raw_storage_path IS NOT NULL) AS has_raw_stored,
               jsonb_array_length(to_addresses) AS recipient_count,
               received_at, created_at, updated_at, deleted_at
        FROM public.inbound_messages
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
                EXECUTE 'GRANT SELECT ON readonly.inbound_messages TO mbai_readonly';
            END IF;
        END
        $$;
        """
    )

    op.execute(_LINKS_VIEW)
    op.execute(_GRANT)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS readonly.inbound_messages")
    # Inline, not a module constant: the drift guard reads every `CREATE VIEW readonly.X` above the
    # rollback function as the LIVE definition, and would then check a shape the database does not
    # have. LP-813 hit that and the guard named it.
    op.execute(
        """
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
    )
    op.drop_column("inbound_messages", "is_bulk")

    # A queued auto-reply cannot be described by the older tuple. FAILED rather than DRAFT: it was
    # never sent and it is not something a person is being asked to review, which is what a draft
    # means and what the open-draft index would then enforce against it.
    op.execute("UPDATE communications SET status = 'failed' WHERE status = 'queued'")
    op.execute("ALTER TABLE communications DROP CONSTRAINT ck_communications_communicationstatus")
    op.execute(
        "ALTER TABLE communications ADD CONSTRAINT ck_communications_communicationstatus "
        f"CHECK ({_in('status', _STATUSES_BEFORE)})"
    )

    # A document that arrived by link cannot be described by the older tuple. Rewritten to the
    # closest true thing rather than left to fail the constraint: it WAS the borrower, and the
    # channel is the part the rollback loses.
    op.execute(
        "UPDATE documents SET upload_source = 'borrower_inbox' WHERE upload_source = 'secure_link'"
    )
    op.execute("ALTER TABLE documents DROP CONSTRAINT ck_documents_uploadsource")
    op.execute(
        "ALTER TABLE documents ADD CONSTRAINT ck_documents_uploadsource "
        f"CHECK ({_check(_SOURCES_BEFORE)})"
    )

    op.execute("DROP VIEW IF EXISTS readonly.upload_links")
    op.drop_index("ix_upload_links_loan_file_id", table_name="upload_links")
    op.drop_index("uq_upload_links_token_hash", table_name="upload_links")
    op.drop_table("upload_links")
