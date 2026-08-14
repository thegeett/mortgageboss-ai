"""add consistency document-finding type (LP-474)

Revision ID: c9d3f1a6b2e4
Revises: 9f0a5f88b6f8
Create Date: 2026-08-11 15:00:00.000000

Adds one value to the ``document_findings.finding_type`` enum (LP-474): ``consistency``, for a
deterministic self-consistency accuracy flag (two extracted values that must differ came out equal).
The enum is a VARCHAR + CHECK (ADR-037), so this is a constraint swap — drop the
``ck_document_findings_documentfindingtype`` CHECK and recreate it with the expanded value set.
No data changes.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9d3f1a6b2e4"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "9f0a5f88b6f8"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_document_findings_documentfindingtype"

# The full enum value set, in model-definition order, with the new value (consistency) right before
# the ``other`` catch-all.
_NEW_VALUES = (
    "obligation",
    "property_interest",
    "income_related",
    "discrepancy_candidate",
    "consistency",
    "other",
)

# The original set (without the new value) for downgrade.
_OLD_VALUES = tuple(v for v in _NEW_VALUES if v != "consistency")


def _swap_check(values: tuple[str, ...]) -> None:
    """Drop and recreate the finding_type CHECK with ``values`` (literal constraint name)."""
    joined = ", ".join(f"'{value}'" for value in values)
    op.execute(f"ALTER TABLE document_findings DROP CONSTRAINT {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE document_findings ADD CONSTRAINT {_CONSTRAINT} "
        f"CHECK (finding_type IN ({joined}))"
    )


def upgrade() -> None:
    """Replace the finding_type CHECK with the expanded value set (adds ``consistency``)."""
    _swap_check(_NEW_VALUES)


def downgrade() -> None:
    """Restore the finding_type CHECK to the original value set."""
    _swap_check(_OLD_VALUES)
