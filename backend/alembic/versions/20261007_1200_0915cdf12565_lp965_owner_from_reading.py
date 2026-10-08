"""LP-965 — the owner hint can come from the reading: `OwnerHintSource.READING`.

The code map used to fill `owner_hint` where the sheet named no owner. It is gone (ADR-419), so the
reading fills it instead, from its first item's performer, and says so with this source. No table
changes.

RAW SQL for the CHECK swap (ADR-037, LP-932). The downgrade turns such hints back to `unknown` / `none`:
a hint is a guess the next reading makes again, not a record of anything she did.

Revision ID: 0915cdf12565
Revises: 5d8b2f6a3c91
Create Date: 2026-10-07 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0915cdf12565"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "5d8b2f6a3c91"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OWNER_HINT_SOURCE_CK = "ck_conditions_ownerhintsource"

_BEFORE = ("prefix", "bucket", "code_map", "none", "manual")
_AFTER = (*_BEFORE, "reading")


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _swap(values: Sequence[str]) -> None:
    """Rewrite `ck_conditions_ownerhintsource` from `values`."""
    op.execute(f"ALTER TABLE conditions DROP CONSTRAINT IF EXISTS {_OWNER_HINT_SOURCE_CK}")
    op.execute(
        f"ALTER TABLE conditions ADD CONSTRAINT {_OWNER_HINT_SOURCE_CK} "
        f"CHECK ({_in('owner_hint_source', values)})"
    )


def upgrade() -> None:
    _swap(_AFTER)


def downgrade() -> None:
    op.execute(
        "UPDATE conditions SET owner_hint = 'unknown', owner_hint_source = 'none' "
        "WHERE owner_hint_source = 'reading'"
    )
    _swap(_BEFORE)
