"""LP-915 — the round comparison, saved on the round, and kept out of the readonly layer.

ONE COLUMN AND ONE VIEW REBUILD. `condition_rounds.comparison` holds what an import found when it
compared the new sheet against everything open before it: the five outcomes, the letter changes, and
the reworded pairs. It is computed once and saved, which is the spec's own requirement — "opening the
panel later shows the same result" — and recomputed only when a round's completeness changes (A7).

NO CHECK CONSTRAINT HERE, WHICH IS WHY THIS FILE IS SHORT. LP-912's migration is long because it had
to cope with `Base.metadata`'s naming convention re-prefixing every `op.create_check_constraint`, and
with LP-904's double-prefixed spellings. A JSONB column needs none of that. The one rule inherited
from it: no function in this module may have `swap` in its name, because
`tests/test_activity_type_migrations.py::_swap_helper_constraints` treats any such function as a
constraint swap and reads its body for `ck_` literals.

`comparison` IS NPI, AND THE VIEW EXPOSES A BOOLEAN RATHER THAN A COUNT. Most of the blob is analytic
— codes, counts, round ids, dates — but the **Reworded?** pairs carry the lender's wording on both
sides of the question, and the letter-changes block is derived from `header`, which LP-904 already
dropped. A JSONB column cannot be half-exposed, so `has_comparison` answers the analytic question
("was this round compared?") and nothing else travels. Deliberately NOT
`jsonb_array_length(comparison -> 'probably_cleared')`: `style_profiles` made exactly that trade and
its migration records choosing the guarantee over the metric, because a derived scalar still names the
column in the select list.

`readonly.condition_rounds` HAS NOT BEEN REBUILT SINCE LP-904, so the definition below is that one
plus a single column. `CREATE OR REPLACE VIEW` cannot change a column list, so this is DROP then
CREATE — which takes the privileges with the old view, hence the regrant INSIDE `upgrade()`.
`test_every_migration_that_recreates_a_readonly_view_regrants_it` slices the function body precisely
so a module constant that is never executed cannot satisfy it.

THE ROLLBACK'S COPY IS INLINE BELOW `def downgrade(`, never hoisted into a constant.
`_later_view_redefinitions()` reads every `CREATE VIEW readonly.X` ABOVE that line-anchored marker as
the LIVE definition, so a hoisted rollback would make the drift guard check a shape the database does
not have — a trap LP-1000 and LP-813 both fell into.

Revision ID: a7c31e6d94b2
Revises: f3a9c05d81e7
Create Date: 2026-09-27 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7c31e6d94b2"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "f3a9c05d81e7"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "condition_rounds",
        sa.Column("comparison", sa.dialects.postgresql.JSONB(), nullable=True),
    )

    # `has_comparison` sits with `has_raw_text` and `has_header`, which answer the same shape of
    # question about the other two columns the view drops.
    op.execute("DROP VIEW IF EXISTS readonly.condition_rounds")
    op.execute(
        """
        CREATE VIEW readonly.condition_rounds AS
        SELECT id, company_id, loan_file_id, lender_id,
               round_number, status, completeness, sheet_format,
               date_printed, round_date, expiry_dates,
               sources,
               (parse_report ->> 'reader') AS reader,
               (parse_report ->> 'reader_version') AS reader_version,
               COALESCE((parse_report ->> 'ai_used')::boolean, false) AS ai_used,
               COALESCE((parse_report ->> 'duplicates_dropped')::int, 0) AS duplicates_dropped,
               COALESCE(jsonb_array_length(parse_report -> 'warnings'), 0) AS warning_count,
               COALESCE(jsonb_array_length(parse_report -> 'unassigned_lines'), 0) AS unassigned_count,
               COALESCE(jsonb_array_length(draft_rows), 0) AS draft_row_count,
               (raw_text IS NOT NULL) AS has_raw_text,
               (header IS NOT NULL) AS has_header,
               (comparison IS NOT NULL) AS has_comparison,
               created_by_user_id, created_at, updated_at, deleted_at
        FROM public.condition_rounds
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
                EXECUTE 'GRANT SELECT ON readonly.condition_rounds TO mbai_readonly';
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    # INLINE, not a module constant — see the docstring. This is LP-904's definition, restored
    # verbatim: `has_comparison` is the only line that goes, because it is the only line that came.
    op.execute("DROP VIEW IF EXISTS readonly.condition_rounds")
    op.execute(
        """
        CREATE VIEW readonly.condition_rounds AS
        SELECT id, company_id, loan_file_id, lender_id,
               round_number, status, completeness, sheet_format,
               date_printed, round_date, expiry_dates,
               sources,
               (parse_report ->> 'reader') AS reader,
               (parse_report ->> 'reader_version') AS reader_version,
               COALESCE((parse_report ->> 'ai_used')::boolean, false) AS ai_used,
               COALESCE((parse_report ->> 'duplicates_dropped')::int, 0) AS duplicates_dropped,
               COALESCE(jsonb_array_length(parse_report -> 'warnings'), 0) AS warning_count,
               COALESCE(jsonb_array_length(parse_report -> 'unassigned_lines'), 0) AS unassigned_count,
               COALESCE(jsonb_array_length(draft_rows), 0) AS draft_row_count,
               (raw_text IS NOT NULL) AS has_raw_text,
               (header IS NOT NULL) AS has_header,
               created_by_user_id, created_at, updated_at, deleted_at
        FROM public.condition_rounds
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
                EXECUTE 'GRANT SELECT ON readonly.condition_rounds TO mbai_readonly';
            END IF;
        END
        $$;
        """
    )

    # AN EXACT INVERSE, unlike LP-912's. Nothing was revoked and no rows were deleted: a saved
    # comparison is derived data, so dropping the column loses only what a re-import would recompute.
    op.drop_column("condition_rounds", "comparison")
