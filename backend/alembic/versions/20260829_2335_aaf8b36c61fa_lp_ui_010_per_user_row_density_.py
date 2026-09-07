"""LP-UI-010 - per-user row density preference

Adds ``users.density``: compact / comfortable / relaxed, defaulting to compact.
An ergonomic preference held per USER (not per view, not per screen), driving
``[data-density]`` on the document and through it the ``--row-h`` / ``--row-px``
tokens every dense surface reads.

HAND-WRITTEN, deliberately. `alembic revision --autogenerate` proposed this
column plus eighteen unrelated operations — dropping the `finding_prose` table,
five `borrowers.current_*` columns, `properties.county`,
`documents.borrower_match_note`, `verifications.fact_snapshot` and the documents
FTS index — because the local development database has drifted from the models.
That drift is real and worth chasing separately; it is not this migration's, and
shipping it here would have destroyed data on every environment.

Revision ID: aaf8b36c61fa
Revises: c4a71fe28b93
Create Date: 2026-08-29 23:35:36.419338

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "aaf8b36c61fa"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "c4a71fe28b93"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DENSITY = sa.Enum(
    "compact",
    "comfortable",
    "relaxed",
    name="rowdensity",
    native_enum=False,
    create_constraint=True,
    length=32,
)


def upgrade() -> None:
    """Add the per-user density preference, defaulting every existing user to compact."""
    op.add_column(
        "users",
        sa.Column("density", _DENSITY, server_default="compact", nullable=False),
    )


def downgrade() -> None:
    """Drop the density preference. The stored choice is lost; it is a preference, not data."""
    op.drop_column("users", "density")
