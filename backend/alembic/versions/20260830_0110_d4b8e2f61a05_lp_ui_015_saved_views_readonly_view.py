"""LP-UI-015 - expose saved_views in the readonly schema

A new base table with no ``readonly.*`` view is not caught by
``test_no_model_column_drifts`` — that guard walks the columns of tables which
already HAVE a view, so a whole table can go missing silently. The decision is
still worth making now rather than the first time someone tries to query it.

Exposed, and everything on it. By the same reasoning the LP-UI-010 review used
for ``users.density``: ``EXCLUDED`` is for credentials and identifiers, and a
saved view holds neither. ``name`` is a label a processor chose ("Blocked to
submit"), ``filters`` is a validated payload of statuses and a search string,
and ``sort`` and ``is_shared`` are enums. There is no borrower content in any of
it.

``search`` inside ``filters`` is the one field a person types freely, so it goes
through ``readonly.scrub_json()`` with the rest of the JSON — the same treatment
every other JSON column gets, and it matches on the shape of the value rather
than on a field name.

Revision ID: d4b8e2f61a05
Revises: c1e5a97b3d42
Create Date: 2026-08-30 01:10:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4b8e2f61a05"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "c1e5a97b3d42"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "readonly"

_VIEW = f"""
    CREATE VIEW {_SCHEMA}.saved_views AS
    SELECT id, company_id, owner_user_id, name,
           {_SCHEMA}.scrub_json(filters) AS filters,
           sort, is_shared, created_at, updated_at, deleted_at
    FROM public.saved_views
    """

_GRANT = f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON {_SCHEMA}.saved_views TO mbai_readonly';
        END IF;
    END
    $$;
    """


def upgrade() -> None:
    """Create the view and grant the read-only role SELECT on it."""
    op.execute(_VIEW)
    op.execute(_GRANT)


def downgrade() -> None:
    """Drop the view. The grant goes with it."""
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.saved_views")
