"""LP-806 — the auto-accept flag, and correspondence as a third answer.

`loan_files.auto_accept_inbound` — DEFAULT FALSE, and `phase4.md` §2.3 is why: "quarantine is the
default, not the exception. A processor already reviews every document; one click to accept a
first-time sender costs almost nothing and closes the entire class of 'a stranger dropped a document
into a loan file.'"

It is the LAST of four conditions rather than the only one. LP-805's `decide_disposition` already
requires a certain route, DMARC PASS, virus PASS and `is_trusted_sender` on that specific file.
Turning this on does not lower any of those; it permits the outcome they were already computing, and
until it exists nothing can auto-accept at all.

`inbound_attachments.disposition` GAINS `correspondence`. Not every accepted attachment is a borrower
document: a lender's conditional-approval PDF satisfies no need and would be classified against a
166-type BORROWER taxonomy — which would either mis-file it or drop it in the long-tail bucket and
then ask a processor why their file has an unrecognised document. Correspondence attaches it to the
file and the timeline without entering classify → extract → needs.

THE CHECK IS SWAPPED WITH THE COMPLETE VALUE SET, not appended to. A swap DROPS the constraint and
recreates it from its own tuple, so what the database accepts is the set of the swap applied LAST —
the same discipline the `activity_type` constraint's history is full of.

`readonly.loan_files` IS REBUILT to carry `auto_accept_inbound`. It is a boolean setting with no
borrower content, and it is the one column that answers "how many files have auto-accept on" — which
is the question anyone auditing this feature will ask first.

A REBUILD IS ALSO WHERE COLUMNS SILENTLY DISAPPEAR, and this one nearly did. The first version of
this migration copied the `CREATE VIEW` from LP-627 — from its DOWNGRADE block, which recreates the
PRE-LP-627 shape — and so dropped `total_mortgaged_properties`, `rate_set_date` and
`seller_paid_closing_costs`, three columns that migration had just added. The drift guard caught it
by naming exactly those three. `tests/test_readonly_query.py`'s own docstring warns about this: only
the upgrade body describes the live database, and a downgrade in the same file is also a
`CREATE ... VIEW`. Reading a view definition means reading the right half of the right file.

A REBUILD IS EQUALLY WHERE DROPPED CONTENT COMES BACK BY ACCIDENT, because the new definition is
written fresh rather than altered. `inbox_token`, `loan_officer_name` and `loan_officer_email` were dropped
by C7 and stay dropped; `inbox_token` is additionally in the test's NEVER_EXPOSED list, which asserts
over the view TEXT across every migration, so re-adding it here would fail rather than pass quietly.
The test that executes this view asserts the absences as well as the addition.

Hand-written, like every migration against this schema.

Revision ID: c9d3a71b8e52
Revises: b8e5f13a7c04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9d3a71b8e52"  # pragma: allowlist secret
down_revision: str | None = "b8e5f13a7c04"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_inbound_attachments_disposition"
_DISPOSITIONS = ("pending", "accepted", "correspondence", "rejected", "duplicate")


def _swap_disposition_check(values: tuple[str, ...]) -> None:
    joined = ", ".join(f"'{value}'" for value in values)
    op.execute(f"ALTER TABLE inbound_attachments DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE inbound_attachments ADD CONSTRAINT {_CONSTRAINT} "
        f"CHECK (disposition IN ({joined}))"
    )


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
           created_at, updated_at, deleted_at
    FROM public.loan_files
    """

_GRANT = """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON readonly.loan_files TO mbai_readonly';
        END IF;
    END
    $$;
    """


def upgrade() -> None:
    op.add_column(
        "loan_files",
        sa.Column("auto_accept_inbound", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _swap_disposition_check(_DISPOSITIONS)

    op.execute("DROP VIEW IF EXISTS readonly.loan_files")
    op.execute(_LOAN_FILES_VIEW)
    op.execute(_GRANT)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS readonly.loan_files")
    op.drop_column("loan_files", "auto_accept_inbound")
    op.execute("""
        CREATE VIEW readonly.loan_files AS
        SELECT id, display_id, company_id, lender_id,
               loan_program, loan_purpose, loan_amount, status,
               note_amount, note_rate_percent, lien_priority, amortization_type,
               amortization_months, application_received_date, ai_needs_status,
               refinance_type, verification_stale, aggression_level_override,
               submitted_aggression_level,
               total_mortgaged_properties, rate_set_date, seller_paid_closing_costs,
               created_at, updated_at, deleted_at
        FROM public.loan_files
        """)
    # The constraint keeps `correspondence`. Removing it would REJECT rows already written with that
    # value, which is the failure mode an over-narrow CHECK produces on a downgrade — and an
    # over-wide constraint accepts everything the code can produce and refuses everything it cannot.
