"""LP-75 finding verification dimensions (confidence, resolution, source location)

Revision ID: b8d3f06a1c54
Revises: f4a9c1e7b203
Create Date: 2026-06-27 11:30:00.000000

Extends the LP-66 ``findings`` table with the verification dimensions (LP-75):

* ``confidence`` — a probability in [0, 1] (the aggression dial's substrate);
  non-null, server-default ``1.0`` (deterministic findings are certain), with a
  range CHECK ``ck_findings_confidence_range``.
* ``source_page`` / ``source_snippet`` — the page + verbatim snippet trust anchor
  (nullable).
* ``applied_record`` — JSON record of what an APPLIED finding incorporated into
  the structured data (nullable).

It also widens two enum CHECKs (constraint-swap, like the activity-type
migration): ``resolution_status`` gains ``applied`` + ``overridden`` (the
verification resolutions, LP-75), and ``origin`` gains ``document_analysis`` (the
third generator in the uniform shape). Constraint names match what the models'
``str_enum`` / CheckConstraint produce so a fresh ``create_all`` and this
migration converge.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8d3f06a1c54"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "f4a9c1e7b203"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RESOLUTION_CONSTRAINT = "ck_findings_findingresolutionstatus"
_RESOLUTION_OLD = ("open", "resolved", "accepted_risk", "waived")
_RESOLUTION_NEW = ("open", "applied", "overridden", "resolved", "accepted_risk", "waived")

_ORIGIN_CONSTRAINT = "ck_findings_findingorigin"
_ORIGIN_OLD = ("deterministic_rule", "ai_cross_source")
_ORIGIN_NEW = ("deterministic_rule", "ai_cross_source", "document_analysis")

_CONFIDENCE_CONSTRAINT = "ck_findings_confidence_range"


def _swap_check(constraint: str, column: str, values: tuple[str, ...]) -> None:
    joined = ", ".join(f"'{value}'" for value in values)
    op.execute(f"ALTER TABLE findings DROP CONSTRAINT {constraint}")
    op.execute(f"ALTER TABLE findings ADD CONSTRAINT {constraint} CHECK ({column} IN ({joined}))")


def upgrade() -> None:
    """Add the verification-dimension columns and widen the two enum CHECKs."""
    op.add_column(
        "findings",
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
    )
    op.add_column("findings", sa.Column("source_page", sa.Integer(), nullable=True))
    op.add_column("findings", sa.Column("source_snippet", sa.Text(), nullable=True))
    op.add_column("findings", sa.Column("applied_record", sa.JSON(), nullable=True))
    op.execute(
        f"ALTER TABLE findings ADD CONSTRAINT {_CONFIDENCE_CONSTRAINT} "
        f"CHECK (confidence >= 0 AND confidence <= 1)"
    )
    _swap_check(_RESOLUTION_CONSTRAINT, "resolution_status", _RESOLUTION_NEW)
    _swap_check(_ORIGIN_CONSTRAINT, "origin", _ORIGIN_NEW)


def downgrade() -> None:
    """Revert the enum CHECKs and drop the added columns."""
    # Revert the widened CHECKs first (no rows should use the new values on a
    # genuine downgrade; this restores the original constraint definitions).
    _swap_check(_ORIGIN_CONSTRAINT, "origin", _ORIGIN_OLD)
    _swap_check(_RESOLUTION_CONSTRAINT, "resolution_status", _RESOLUTION_OLD)
    op.execute(f"ALTER TABLE findings DROP CONSTRAINT {_CONFIDENCE_CONSTRAINT}")
    op.drop_column("findings", "applied_record")
    op.drop_column("findings", "source_snippet")
    op.drop_column("findings", "source_page")
    op.drop_column("findings", "confidence")
