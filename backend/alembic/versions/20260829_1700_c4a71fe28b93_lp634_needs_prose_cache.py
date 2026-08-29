"""LP-634 — the Need List's own prose: a display column and its cache

The Need List explains almost nothing today: on LF-AWBB the six FLOOR needs — the deterministic ones,
the ones we are surest about — store no reasoning at all, and the finding-derived ones read "Required
by verification rule(s) CL-1, CR-13, DT-7, ID-5, IH-2, IH-3, PR-6". A composition pass writes the
sentence that says WHY, and this is where it remembers what it wrote.

A PURE CACHE, on the same terms as `finding_prose`: no foreign key, no loan file, no run. It exists for
DETERMINISM first — without it an unchanged need is worded differently every run, and a processor
re-reading the list sees movement where nothing moved.

Revision ID: c4a71fe28b93
Revises: e8c4a1f92b37
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4a71fe28b93"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "e8c4a1f92b37"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SCHEMA = "readonly"

# The view, with `explanation` beside `reasoning`. Both are model/rule-authored prose about a file's
# stated data, so both go through `scrub` exactly as `reasoning` already does.
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
           {_SCHEMA}.scrub(explanation) AS explanation,
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
    # The display sentence, separate from `reasoning` (the origin's own record, and this composer's
    # INPUT). One column for both would let the output feed back in as its own input.
    op.add_column("needs_items", sa.Column("explanation", sa.Text(), nullable=True))
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.needs_items")
    op.execute(_NEEDS_ITEMS_VIEW)
    op.execute(_GRANT)

    op.create_table(
        "needs_prose",
        sa.Column("fact_hash", sa.String(length=64), nullable=False),
        sa.Column("why", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("fact_hash", name=op.f("pk_needs_prose")),
    )
    # No readonly view: a cache row carries composed prose about ONE file's stated facts and has no
    # loan_file_id to scope a query by, so exposing it would offer a staging reader text they cannot
    # attribute. The composed reason is readable where it matters — on `needs_items.reasoning`, which
    # the readonly view already scrubs and exposes.


def downgrade() -> None:
    op.drop_table("needs_prose")
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.needs_items")
    op.drop_column("needs_items", "explanation")
    # Defined HERE rather than beside its successor at module level: the LP-509-B1 drift scanner reads
    # every CREATE VIEW above `def downgrade(` and lets the last win, so a rollback definition parked
    # up there would be read as the live view (bug-002's lesson, learned the same way).
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
               covered_by_document_id,
               {_SCHEMA}.scrub(coverage_note) AS coverage_note,
               coverage_reviewed,
               created_at, updated_at, deleted_at
        FROM public.needs_items
        """
    )
    op.execute(_GRANT)
