"""LP-74 finding origin (two-generator seam)

Revision ID: f4a9c1e7b203
Revises: e7c2f9a14b60
Create Date: 2026-06-27 10:00:00.000000

Adds a non-null ``origin`` column to ``findings`` (LP-74): which generator
produced the finding — ``deterministic_rule`` (the LP-74 rule engine) or
``ai_cross_source`` (the LP-78 AI layer, which feeds the same shared model). A
bounded VARCHAR + CHECK (ADR-037), with a server default of ``deterministic_rule``
so existing rows back-fill as engine findings, and an index (the column is
queried/filtered).

The CHECK uses the literal name the model's ``str_enum`` produces
(``ck_findings_findingorigin``) and the index the naming convention produces
(``ix_findings_origin``) so a fresh ``create_all`` and this migration converge.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4a9c1e7b203"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "e7c2f9a14b60"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_findings_findingorigin"
_INDEX = "ix_findings_origin"
_VALUES = ("deterministic_rule", "ai_cross_source")
_DEFAULT = "deterministic_rule"


def upgrade() -> None:
    """Add the non-null origin column (server-default back-fill), CHECK + index."""
    op.add_column(
        "findings",
        sa.Column(
            "origin",
            sa.String(length=32),
            nullable=False,
            server_default=_DEFAULT,
        ),
    )
    joined = ", ".join(f"'{value}'" for value in _VALUES)
    op.execute(f"ALTER TABLE findings ADD CONSTRAINT {_CONSTRAINT} CHECK (origin IN ({joined}))")
    op.create_index(_INDEX, "findings", ["origin"])


def downgrade() -> None:
    """Drop the index, the CHECK, and the column."""
    op.drop_index(_INDEX, table_name="findings")
    op.execute(f"ALTER TABLE findings DROP CONSTRAINT {_CONSTRAINT}")
    op.drop_column("findings", "origin")
