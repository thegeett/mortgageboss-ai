"""LP-UI-010 review - expose users.density in the readonly view

``users.density`` landed in aaf8b36c61fa without being added to
``readonly.users``. ``test_no_model_column_drifts`` catches exactly that and was
already red: a model column must be exposed by its view or listed in the test's
``EXCLUDED`` map, never neither, so that the decision is made when it is cheap.

Exposed rather than excluded. ``EXCLUDED["users"]`` holds credentials and
identifiers — ``hashed_password``, ``email``, ``first_name``, ``last_name`` —
and density is neither: it is a bounded three-value ergonomic preference with no
identifying content, and its sibling ``default_aggression_level`` (the other
per-user preference enum) has been in the view since C7.

Recreated rather than ``CREATE OR REPLACE``: Postgres only lets a replace APPEND
columns, which would have stranded ``density`` after ``deleted_at`` instead of
beside the preference it belongs with. Follows LP-631's shape — drop, recreate,
re-grant, because a dropped view takes its grant with it.

A separate revision rather than an edit to aaf8b36c61fa, which is already
committed: an edited migration is only correct in the world where nothing has
applied it yet, and this is correct in both.

Revision ID: b7f4a2d19c63
Revises: aaf8b36c61fa
Create Date: 2026-08-30 00:15:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7f4a2d19c63"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "aaf8b36c61fa"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "readonly"

# DROPPED: hashed_password (a credential), email, first_name, last_name.
_USERS_VIEW = f"""
    CREATE VIEW {_SCHEMA}.users AS
    SELECT id, company_id, role, is_active, default_aggression_level, density,
           created_at, updated_at, deleted_at
    FROM public.users
    """

_GRANT = f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON {_SCHEMA}.users TO mbai_readonly';
        END IF;
    END
    $$;
    """


def upgrade() -> None:
    """Rebuild `readonly.users` with the density preference exposed."""
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.users")
    op.execute(_USERS_VIEW)
    op.execute(_GRANT)


def downgrade() -> None:
    """Restore the pre-density view.

    The old definition is INSIDE this function on purpose. The drift guard reads
    later migrations as text and takes everything before `def downgrade(` as the
    live view — so a rollback definition hoisted to module level is read as the
    current one, and the guard then reports a freshly exposed column as
    unexposed. Its own docstring warns about this; a module-level constant walks
    straight past the warning.
    """
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.users")
    op.execute(f"""
        CREATE VIEW {_SCHEMA}.users AS
        SELECT id, company_id, role, is_active, default_aggression_level,
               created_at, updated_at, deleted_at
        FROM public.users
        """)
    op.execute(_GRANT)
