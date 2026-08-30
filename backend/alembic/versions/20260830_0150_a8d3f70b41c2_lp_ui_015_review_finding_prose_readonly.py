"""LP-UI-015 review - the readonly view finding_prose never got

The second table the drift guard's new direction found. `finding_prose`
(LP-634's composition cache) is registered only when a test that uses it
imports the model — `app.models.__init__` does not export it — so it was
invisible both to the guard and to a casual look at the package.

Exposed with both prose columns scrubbed, matching `needs_items.reasoning`:
model-authored prose about a finding names a creditor and an amount. The cache
key is a hash and carries nothing.

Revision ID: a8d3f70b41c2
Revises: f3a1b62c95d7
Create Date: 2026-08-30 01:50:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8d3f70b41c2"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "f3a1b62c95d7"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "readonly"

_VIEW = f"""
    CREATE VIEW {_SCHEMA}.finding_prose AS
    SELECT fact_hash,
           {_SCHEMA}.scrub(action) AS action,
           {_SCHEMA}.scrub(why) AS why,
           created_at
    FROM public.finding_prose
    """

_GRANT = f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON {_SCHEMA}.finding_prose TO mbai_readonly';
        END IF;
    END
    $$;
    """


def upgrade() -> None:
    """Expose the composition cache, with both prose columns scrubbed."""
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.finding_prose")
    op.execute(_VIEW)
    op.execute(_GRANT)


def downgrade() -> None:
    """Drop it again."""
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.finding_prose")
