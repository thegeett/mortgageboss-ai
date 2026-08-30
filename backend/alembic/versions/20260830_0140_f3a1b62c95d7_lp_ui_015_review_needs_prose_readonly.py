"""LP-UI-015 review - the readonly view needs_prose never got

Found by the drift guard's MISSING direction, added in the same review.
`test_no_model_column_drifts` walks views and checks their columns; nothing
walked TABLES and checked they have a view at all, so a whole new table was
invisible to it. `needs_prose` (LP-634, c4a71fe28b93) is the one table that
slipped through — `saved_views` would have been the second.

Exposed with `why` scrubbed, matching `needs_items`, whose `reasoning` and
`reason` are model-authored prose about the same subject and go through `scrub`
for the same reason: composed prose names a creditor and an amount.

Revision ID: f3a1b62c95d7
Revises: e2c9f47a80b1
Create Date: 2026-08-30 01:40:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a1b62c95d7"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "e2c9f47a80b1"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "readonly"

_VIEW = f"""
    CREATE VIEW {_SCHEMA}.needs_prose AS
    SELECT fact_hash,
           {_SCHEMA}.scrub(why) AS why,
           created_at
    FROM public.needs_prose
    """

_GRANT = f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON {_SCHEMA}.needs_prose TO mbai_readonly';
        END IF;
    END
    $$;
    """


def upgrade() -> None:
    """Expose the prose cache, with its one free-text column scrubbed."""
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.needs_prose")
    op.execute(_VIEW)
    op.execute(_GRANT)


def downgrade() -> None:
    """Drop it again."""
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.needs_prose")
