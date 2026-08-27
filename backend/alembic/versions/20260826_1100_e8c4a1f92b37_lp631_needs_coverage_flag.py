"""LP-631 — the coverage flag: a need the file already answers

An AI-proposed need is immortal once written. LP-69 reasons at MISMO import, when the file has no
documents by construction, so every proposal is provisional — and the ingest path only ever creates a
row or refreshes its reasoning. Staging carries 32 such open proposals; LF-AWBB's asks for a lease
agreement documenting a liability its credit report already lists at the stated payment.

ADR-388: a need whose precondition has become false is FLAGGED, never closed. Three columns carry the
flag, mirroring LP-111's duplicate pair:

  * ``covered_by_document_id`` — the document that appears to already answer the need (SET NULL, so
    removing the document does not strand the flag).
  * ``coverage_note`` — WHY, in words a processor can check. A row saying only "possibly covered"
    asks them to redo the work; the note is the whole value of the flag.
  * ``coverage_reviewed`` — the processor has disposed of it, so no pass re-flags a judgement already
    made.

Additive; existing rows default to (null, null, false). No backfill.

Revision ID: e8c4a1f92b37
Revises: 9d3e4c17b520
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8c4a1f92b37"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "9d3e4c17b520"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "readonly"

# The view, with the three new columns. `coverage_note` is model/rule-authored prose naming a
# creditor and an amount, so it goes through `scrub` like every other free-text column; the two
# structural columns carry no identifier.
_NEEDS_ITEMS_VIEW = f"""
    CREATE VIEW {_SCHEMA}.needs_items AS
    SELECT id, loan_file_id, borrower_id,
           {_SCHEMA}.scrub(title) AS title,
           {_SCHEMA}.scrub(description) AS description,
           category, needs_type, origin, priority, status,
           satisfied_by_document_id, satisfied_at, requested_at,
           {_SCHEMA}.scrub(notes) AS notes,
           disposition,
           {_SCHEMA}.scrub(reasoning) AS reasoning,
           {_SCHEMA}.scrub(reason) AS reason,
           source_finding_id,
           {_SCHEMA}.scrub_json(source_facts) AS source_facts,
           duplicate_reviewed, duplicate_of_id,
           covered_by_document_id,
           {_SCHEMA}.scrub(coverage_note) AS coverage_note,
           coverage_reviewed,
           created_at, updated_at, deleted_at
    FROM public.needs_items
"""

_GRANT = f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON {_SCHEMA}.needs_items TO mbai_readonly';
        END IF;
    END
    $$;
"""


def upgrade() -> None:
    """Add the coverage-flag columns + the document FK + its index, and re-cut the readonly view."""
    op.add_column(
        "needs_items",
        sa.Column("coverage_reviewed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("needs_items", sa.Column("covered_by_document_id", sa.Uuid(), nullable=True))
    op.add_column("needs_items", sa.Column("coverage_note", sa.Text(), nullable=True))
    op.create_index(
        op.f("ix_needs_items_covered_by_document_id"),
        "needs_items",
        ["covered_by_document_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_needs_items_covered_by_document_id_documents"),
        "needs_items",
        "documents",
        ["covered_by_document_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Drop the server_default now that existing rows are populated — the model default drives inserts.
    op.alter_column("needs_items", "coverage_reviewed", server_default=None)

    # Staging must be able to see the flag, or the pass cannot be verified where it actually runs.
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.needs_items")
    op.execute(_NEEDS_ITEMS_VIEW)
    op.execute(_GRANT)


def downgrade() -> None:
    """Drop the coverage-flag columns (+ FK + index) and restore the pre-LP-631 view."""
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.needs_items")
    op.drop_constraint(
        op.f("fk_needs_items_covered_by_document_id_documents"), "needs_items", type_="foreignkey"
    )
    op.drop_index(op.f("ix_needs_items_covered_by_document_id"), table_name="needs_items")
    op.drop_column("needs_items", "coverage_note")
    op.drop_column("needs_items", "covered_by_document_id")
    op.drop_column("needs_items", "coverage_reviewed")
    # Defined HERE, not beside its successor at module level: the LP-509-B1 drift scanner reads every
    # CREATE VIEW above ``def downgrade(`` and lets the last win, so a rollback definition parked up
    # there would be read as the live view — reporting the three freshly exposed columns as unexposed.
    op.execute(
        f"""
        CREATE VIEW {_SCHEMA}.needs_items AS
        SELECT id, loan_file_id, borrower_id,
               {_SCHEMA}.scrub(title) AS title,
               {_SCHEMA}.scrub(description) AS description,
               category, needs_type, origin, priority, status,
               satisfied_by_document_id, satisfied_at, requested_at,
               {_SCHEMA}.scrub(notes) AS notes,
               disposition,
               {_SCHEMA}.scrub(reasoning) AS reasoning,
               {_SCHEMA}.scrub(reason) AS reason,
               source_finding_id,
               {_SCHEMA}.scrub_json(source_facts) AS source_facts,
               duplicate_reviewed, duplicate_of_id,
               created_at, updated_at, deleted_at
        FROM public.needs_items
        """
    )
    op.execute(_GRANT)
