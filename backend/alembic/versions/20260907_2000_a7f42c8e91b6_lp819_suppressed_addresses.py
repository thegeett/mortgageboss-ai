"""LP-819 — addresses that must not be emailed again, and the activity type for a failed send.

TWO THINGS, AND THEY BELONG TOGETHER because a bounce is what produces both.

`suppressed_addresses` — a `5.x.x` per RFC 3463 means the mailbox does not exist, and sending again
produces another bounce. Enough of those damage a sending reputation shared by every borrower this
system writes to.

SCOPED PER COMPANY, even though "this mailbox does not exist" is a fact about the world. One
company's bounce must not block another's send — a borrower shopping two brokers is ordinary — and a
shared table would LEAK: "that address is suppressed" tells company B that somebody else has been
emailing their borrower. That is the same cross-tenant disclosure LP-811a's rate limit was corrected
for, and the cost of scoping is one company learning the same fact the hard way, once.

`ActivityType.COMMUNICATION_FAILED` — and this is the migration that has to be got right, because
`activity_type` is a VARCHAR + CHECK (ADR-037) and a swap DROPS the constraint and recreates it from
its OWN tuple. What the database accepts is the set of the swap applied LAST, not the union of every
swap. So the tuple below is the COMPLETE 32-value list, verified equal to the merged enum, and
written out in model order rather than derived from the live schema — a migration that reads its own
target from the database cannot be reviewed and cannot repair a database that is already wrong.

`tests/test_activity_type_migrations.py` is the guard, and it reads these files as TEXT: the test
database is built by `create_all`, which regenerates the CHECK from the current enum, so a database
test here would pass whatever the migrations said.

THE READONLY VIEW DROPS `diagnostic` AND EXPOSES THE REST. The diagnostic is the provider's own
words and routinely quotes the recipient's address back — a name and a mailbox, in free text no
scrub matches. `address` is dropped for the same reason: it identifies one borrower. What is left —
the reason, the status code, when — is what makes "how many hard bounces, and of what kind"
answerable without naming anybody.

Hand-written, like every migration against this schema.

Revision ID: a7f42c8e91b6
Revises: f6c3d05b284e
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7f42c8e91b6"  # pragma: allowlist secret
down_revision: str | None = "f6c3d05b284e"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_activity_logs_activitytype"

#: The COMPLETE value set, in model-definition order. Adding one here without adding it to the enum
#: (or the reverse) is what `tests/test_activity_type_migrations.py` refuses.
_NEW_VALUES = (
    "file_created",
    "file_updated",
    "file_deleted",
    "status_changed",
    "document_uploaded",
    "document_processed",
    "document_type_overridden",
    "document_replaced",
    "document_staleness_resolved",
    "field_reviewed",
    "field_review_reverted",
    "document_reprocessed",
    "finding_resolved",
    "finding_undone",
    "verification_run",
    "dti_overridden",
    "dti_line_added",
    "dti_line_removed",
    "dti_ungated",
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
    "communication_failed",
    "note_added",
)

_SUPPRESSION_REASONS = ("hard_bounce", "complaint", "manual")

_VIEW = """
    CREATE VIEW readonly.suppressed_addresses AS
    SELECT id, company_id, reason, status_code, suppressed_at, created_at, updated_at
    FROM public.suppressed_addresses
    """

_GRANT = """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON readonly.suppressed_addresses TO mbai_readonly';
        END IF;
    END
    $$;
    """


def _swap_check(values: tuple[str, ...]) -> None:
    joined = ", ".join(f"'{value}'" for value in values)
    op.execute(f"ALTER TABLE activity_logs DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE activity_logs ADD CONSTRAINT {_CONSTRAINT} "
        f"CHECK (activity_type IN ({joined}))"
    )


def upgrade() -> None:
    _swap_check(_NEW_VALUES)

    op.create_table(
        "suppressed_addresses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("address", sa.String(length=256), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("status_code", sa.String(length=16), nullable=True),
        sa.Column("diagnostic", sa.Text(), nullable=True),
        sa.Column("suppressed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id", "address", name="uq_suppressed_addresses_company_address"
        ),
    )
    op.create_index("ix_suppressed_addresses_company_id", "suppressed_addresses", ["company_id"])

    joined = ", ".join(f"'{value}'" for value in _SUPPRESSION_REASONS)
    op.execute(
        "ALTER TABLE suppressed_addresses ADD CONSTRAINT ck_suppressed_addresses_reason "
        f"CHECK (reason IN ({joined}))"
    )

    op.execute("DROP VIEW IF EXISTS readonly.suppressed_addresses")
    op.execute(_VIEW)
    op.execute(_GRANT)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS readonly.suppressed_addresses")
    op.drop_table("suppressed_addresses")
    # The CHECK is left carrying `communication_failed`. Removing it would REJECT rows already
    # written with that value, which is the failure mode this constraint's history is full of — an
    # over-wide constraint accepts everything the code can produce and refuses everything it cannot.
