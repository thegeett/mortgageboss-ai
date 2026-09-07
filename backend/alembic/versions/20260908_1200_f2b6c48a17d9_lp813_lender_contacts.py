"""LP-813 — a named underwriter, and the first way to create a lender.

TWO GAPS THAT LOOK UNRELATED AND ARE THE SAME ONE. `Lender.contact_email` has existed since LP-13,
its docstring says it is "for direct underwriter communication", and there was **no create or update
path for a lender anywhere in the product** — every lender in every environment came from the seed
script. So LP-805 seeds participants from three sources and one of them was always NULL on a real
installation, which means an underwriter's reply could never route.

And one address per lender is the wrong shape anyway: UWM has many underwriters, a file is with one
of them, and the one on this file is not the one on the next. `lender_contacts` holds the people;
`loan_files.underwriter_contact_id` says which of them this file is with.

NO `company_id` ON `lender_contacts`. It is reached only through its lender, which is company-owned,
so scoping is transitive — the shape ADR-052 gives file-owned children. Storing the company here as
well would make a contact whose company disagreed with its lender's a representable state that
nothing would notice.

THE READONLY VIEW DROPS `name`, `email`, `phone` AND `notes`. A contact is a person; what is left —
the role, whether they are active, the lender — answers "how many files have a named underwriter"
without identifying anybody. `notes` goes too, because free text an admin typed about a person is
exactly where a name ends up.

Hand-written, like every migration against this schema.

Revision ID: f2b6c48a17d9
Revises: e4a7c15d92b0
Create Date: 2026-09-08 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2b6c48a17d9"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "e4a7c15d92b0"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLES = ("underwriter", "account_executive", "closer", "other")

_LOAN_FILES_VIEW = """
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

_CONTACTS_VIEW = """
    CREATE VIEW readonly.lender_contacts AS
    SELECT id, lender_id, role, is_active,
           created_at, updated_at, deleted_at
    FROM public.lender_contacts
    """

_GRANT = """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON readonly.lender_contacts TO mbai_readonly';
        END IF;
    END
    $$;
    """


def upgrade() -> None:
    op.create_table(
        "lender_contacts",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "lender_id",
            sa.UUID(),
            sa.ForeignKey("lenders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("email", sa.String(128), nullable=True),
        sa.Column("phone", sa.String(64), nullable=True),
        sa.Column("role", sa.String(64), nullable=False, server_default="underwriter"),
        sa.Column("notes", sa.String(512), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        # VARCHAR + CHECK rather than a native enum (ADR-037), so adding a role is one migration
        # that recreates the constraint from its own complete tuple rather than an ALTER TYPE.
        sa.CheckConstraint(
            "role IN (" + ", ".join(f"'{role}'" for role in _ROLES) + ")",
            name="ck_lender_contacts_role",
        ),
    )
    op.create_index("ix_lender_contacts_lender_id", "lender_contacts", ["lender_id"])
    # Case-insensitive and partial: a contact with no email is a legitimate row (phone-only), and
    # several of those must not collide. Soft-deleted rows are excluded so an address can be reused
    # after somebody leaves.
    op.execute(
        "CREATE UNIQUE INDEX uq_lender_contacts_lender_email "
        "ON lender_contacts (lender_id, lower(email)) "
        "WHERE email IS NOT NULL AND deleted_at IS NULL"
    )

    op.add_column(
        "loan_files",
        sa.Column(
            "underwriter_contact_id",
            sa.UUID(),
            sa.ForeignKey("lender_contacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_loan_files_underwriter_contact_id", "loan_files", ["underwriter_contact_id"]
    )

    op.execute(_CONTACTS_VIEW)
    op.execute(_GRANT)

    # `readonly.loan_files` gains the new column, as a BOOLEAN rather than the id: whether a file
    # has a named underwriter is the analytic question, and the id would join straight back to a
    # person.
    #
    # THE BODY BELOW IS COPIED FROM THE UPGRADE OF THE MIGRATION THAT LAST DEFINED IT (LP-806), not
    # from its downgrade. LP-806 hit exactly that trap: a downgrade block recreates the PREVIOUS
    # shape, so copying it silently drops every column added since. The drift guard catches it, and
    # it is cheaper to read the right half of the file.
    op.execute("DROP VIEW IF EXISTS readonly.loan_files")
    op.execute(_LOAN_FILES_VIEW)
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
    # INLINE, NOT A MODULE CONSTANT. The drift guard reads every `CREATE VIEW readonly.X` above the
    # rollback function as the live definition, so a rollback body hoisted to a constant wins over
    # the real one and the guard then checks a shape the database does not have. It says so by name.
    #
    # And this is LP-806's UPGRADE body — the shape the database has today — not its downgrade body,
    # which is pre-LP-806 and would drop `auto_accept_inbound` on the way back.
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
               created_at, updated_at, deleted_at
        FROM public.loan_files
        """
    )
    op.execute("DROP VIEW IF EXISTS readonly.lender_contacts")
    op.drop_index("ix_loan_files_underwriter_contact_id", table_name="loan_files")
    op.drop_column("loan_files", "underwriter_contact_id")
    op.drop_index("uq_lender_contacts_lender_email", table_name="lender_contacts")
    op.drop_index("ix_lender_contacts_lender_id", table_name="lender_contacts")
    op.drop_table("lender_contacts")
