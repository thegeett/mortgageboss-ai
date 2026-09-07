"""LP-821 — the evidence record, and the legal hold that ships before the purge job.

TWO HALVES OF ONE OBLIGATION. `phase4.md` §6 wants a communication log that is "append-only at the
application layer" and "must not be soft-deletable"; and, separately, a legal-hold flag shipped
BEFORE the purge job, because INFRA-1 builds the S3 lifecycle expiry — which IS the purge job — on
day one of the critical path. A record that cannot be edited is worth nothing if a lifecycle rule
deletes the object it describes.

`communication_evidence` IS A SECOND TABLE, not more columns on `communications`. That row is
soft-deletable and it is EDITED — `send_draft` overwrites `body` with the processor's edit, LP-820
refreshes `recipient` when an address is corrected. Both are right for the UX and disqualifying for
evidence.

NO `deleted_at` AND NO `updated_at` ON THE NEW TABLE. The first is §6's requirement outright. The
second is omitted because an `updated_at` on an append-only row can only ever lie: either it equals
`recorded_at` forever, or something updated a row that must not be updated.

WHAT HISTORICAL ROWS CAN AND CANNOT SUPPLY, recorded here so an audit does not have to discover it:
recipient, template + version, the body AS SENT, the inbound auth verdicts and the attachment
manifest are all still on the rows they were always on. The COMPOSED DRAFT is not — `send_draft`
overwrote it, so for anything sent before this migration it is gone rather than unstored, and no
backfill can produce it. The approver was written only into an activity log's detail.

THE READONLY VIEW DROPS EVERY BODY, THE SUBJECT, BOTH ADDRESSES AND THE MANIFEST. What is left — the
event, the template, the model, which guard fired, the scrubbed verdicts and the counts — answers
"how much was sent, under which template, with what firing" without reproducing a borrower's mail in
the analytics path. `readonly.communications` already drops the same four columns for the same
reason, and this table holds a second copy of them.

Hand-written, like every migration against this schema.

Revision ID: a6c3e8d47f21
Revises: f4d7b2e91c58
Create Date: 2026-09-09 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a6c3e8d47f21"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "f4d7b2e91c58"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENTS = ("sent", "delivery_failed", "received")

_EVIDENCE_VIEW = """
    CREATE VIEW readonly.communication_evidence AS
    SELECT id, loan_file_id, communication_id, event, recorded_at,
           approver_user_id, template_key, template_version,
           guardrail_fired, model_id, prompt_version,
           readonly.scrub(auth_verdicts::text)::jsonb AS auth_verdicts,
           jsonb_array_length(attachment_manifest) AS attachment_count,
           (body_composed IS NOT NULL) AS has_composed_draft,
           (body_as_sent IS DISTINCT FROM body_composed) AS was_edited
    FROM public.communication_evidence
    """

_GRANT = """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON readonly.communication_evidence TO mbai_readonly';
        END IF;
    END
    $$;
    """


def upgrade() -> None:
    op.create_table(
        "communication_evidence",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "loan_file_id",
            sa.UUID(),
            # RESTRICT, not CASCADE. Loan files are soft-deleted and never hard-deleted (ADR-044),
            # so this cannot fire — and if a hard delete were ever added, the evidence is the last
            # thing that should go with it.
            sa.ForeignKey("loan_files.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "communication_id",
            sa.UUID(),
            # SET NULL. The message row is soft-deletable by design; the evidence must survive its
            # subject rather than block a delete of it.
            sa.ForeignKey("communications.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sender", sa.String(128), nullable=True),
        sa.Column("recipient", sa.String(128), nullable=True),
        sa.Column(
            "approver_user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("template_key", sa.String(64), nullable=True),
        sa.Column("template_version", sa.String(64), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("body_as_sent", sa.Text(), nullable=True),
        sa.Column("body_composed", sa.Text(), nullable=True),
        sa.Column(
            "attachment_manifest",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("guardrail_fired", sa.String(128), nullable=True),
        sa.Column("model_id", sa.String(64), nullable=True),
        sa.Column("prompt_version", sa.String(64), nullable=True),
        sa.Column(
            "auth_verdicts", sa.dialects.postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.CheckConstraint(
            "event IN (" + ", ".join(f"'{event}'" for event in _EVENTS) + ")",
            name="ck_communication_evidence_event",
        ),
    )
    op.create_index(
        "ix_communication_evidence_loan_file_id", "communication_evidence", ["loan_file_id"]
    )
    op.create_index(
        "ix_communication_evidence_communication_id",
        "communication_evidence",
        ["communication_id"],
    )
    # ONE ROW PER (message, event). A send recorded twice is a duplicate an auditor has to
    # reconcile, and a retried send is exactly the case likely to produce one.
    op.create_index(
        "uq_communication_evidence_event",
        "communication_evidence",
        ["communication_id", "event"],
        unique=True,
    )

    op.add_column(
        "loan_files",
        sa.Column("legal_hold", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "loan_files", sa.Column("legal_hold_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("loan_files", sa.Column("legal_hold_reason", sa.Text(), nullable=True))
    # PARTIAL, on the held ones. A purge sweep asks "which of these must I skip", and on a company
    # with ten thousand files the answer is almost always a handful.
    op.execute("CREATE INDEX ix_loan_files_legal_hold ON loan_files (company_id) WHERE legal_hold")

    op.execute(_EVIDENCE_VIEW)
    op.execute(_GRANT)

    # `readonly.loan_files` gains the hold as a BOOLEAN and a time. The REASON is not exposed: it is
    # free prose a processor typed about a legal matter on one borrower's file, which is where a name
    # arrives in a shape no scrubber predicts.
    #
    # COPIED FROM LP-813's UPGRADE body, which is the shape the database has — LP-806 lost three
    # columns to copying a downgrade block, and the drift guard is what caught it.
    op.execute("DROP VIEW IF EXISTS readonly.loan_files")
    op.execute(
        """
        CREATE VIEW readonly.loan_files AS
        SELECT id, display_id, company_id, lender_id,
               loan_program, loan_purpose, loan_amount, status,
               note_amount, note_rate_percent, lien_priority, amortization_type,
               amortization_months, application_received_date, ai_needs_status,
               refinance_type, verification_stale, aggression_level_override,
               submitted_aggression_level,
               total_mortgaged_properties, rate_set_date, seller_paid_closing_costs,
               auto_accept_inbound,
               (underwriter_contact_id IS NOT NULL) AS has_named_underwriter,
               legal_hold, legal_hold_at,
               created_at, updated_at, deleted_at
        FROM public.loan_files
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
                EXECUTE 'GRANT SELECT ON readonly.loan_files TO mbai_readonly';
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS readonly.loan_files")
    # INLINE, not a module constant: the drift guard reads every `CREATE VIEW readonly.X` above the
    # rollback function as the LIVE definition. LP-813 hit that and the guard named it by file.
    op.execute(
        """
        CREATE VIEW readonly.loan_files AS
        SELECT id, display_id, company_id, lender_id,
               loan_program, loan_purpose, loan_amount, status,
               note_amount, note_rate_percent, lien_priority, amortization_type,
               amortization_months, application_received_date, ai_needs_status,
               refinance_type, verification_stale, aggression_level_override,
               submitted_aggression_level,
               total_mortgaged_properties, rate_set_date, seller_paid_closing_costs,
               auto_accept_inbound,
               (underwriter_contact_id IS NOT NULL) AS has_named_underwriter,
               created_at, updated_at, deleted_at
        FROM public.loan_files
        """
    )
    op.execute("DROP VIEW IF EXISTS readonly.communication_evidence")
    op.execute("DROP INDEX IF EXISTS ix_loan_files_legal_hold")
    op.drop_column("loan_files", "legal_hold_reason")
    op.drop_column("loan_files", "legal_hold_at")
    op.drop_column("loan_files", "legal_hold")
    op.drop_index("uq_communication_evidence_event", table_name="communication_evidence")
    op.drop_index("ix_communication_evidence_communication_id", table_name="communication_evidence")
    op.drop_index("ix_communication_evidence_loan_file_id", table_name="communication_evidence")
    op.drop_table("communication_evidence")
