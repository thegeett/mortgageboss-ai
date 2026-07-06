"""LP-79 aggression dial — per-file + user-default thoroughness columns

Revision ID: b7f2c1d4e890
Revises: a1c4e7b9f320
Create Date: 2026-06-28 17:00:00.000000

Adds the aggression dial's persistence (LP-79) — a per-file CONFIDENCE CUTOFF
over the already-computed findings (LP-78), with a user-level default + a per-file
override, and the active level recorded at submission for auditability:

* ``users.default_aggression_level`` — the user's default thoroughness (a bounded
  VARCHAR + CHECK; ``balanced`` server-default so existing rows are valid).
* ``loan_files.aggression_level_override`` — a per-file override (null = use the
  user default).
* ``loan_files.submitted_aggression_level`` — the active level recorded when the
  file was marked ready to submit ("cleared at <level> thoroughness"; null until).

Constraint names match what the models produce (``str_enum`` with explicit names on
the two loan_files columns, since the same enum backs both) so a fresh
``create_all`` and this migration converge.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7f2c1d4e890"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "a1c4e7b9f320"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VALUES = ("conservative", "balanced", "thorough")
_JOINED = ", ".join(f"'{value}'" for value in _VALUES)

_USERS_CK = "ck_users_aggressionlevel"
_FILE_OVERRIDE_CK = "ck_loan_files_aggression_level_override"
_FILE_SUBMITTED_CK = "ck_loan_files_submitted_aggression_level"


def upgrade() -> None:
    """Add the user default + the per-file override / submitted-level columns."""
    op.add_column(
        "users",
        sa.Column(
            "default_aggression_level",
            sa.String(length=32),
            nullable=False,
            server_default="balanced",
        ),
    )
    op.execute(
        f"ALTER TABLE users ADD CONSTRAINT {_USERS_CK} "
        f"CHECK (default_aggression_level IN ({_JOINED}))"
    )

    op.add_column(
        "loan_files",
        sa.Column("aggression_level_override", sa.String(length=32), nullable=True),
    )
    op.execute(
        f"ALTER TABLE loan_files ADD CONSTRAINT {_FILE_OVERRIDE_CK} "
        f"CHECK (aggression_level_override IN ({_JOINED}))"
    )

    op.add_column(
        "loan_files",
        sa.Column("submitted_aggression_level", sa.String(length=32), nullable=True),
    )
    op.execute(
        f"ALTER TABLE loan_files ADD CONSTRAINT {_FILE_SUBMITTED_CK} "
        f"CHECK (submitted_aggression_level IN ({_JOINED}))"
    )


def downgrade() -> None:
    """Drop the dial columns + their CHECK constraints."""
    op.execute(f"ALTER TABLE loan_files DROP CONSTRAINT {_FILE_SUBMITTED_CK}")
    op.drop_column("loan_files", "submitted_aggression_level")
    op.execute(f"ALTER TABLE loan_files DROP CONSTRAINT {_FILE_OVERRIDE_CK}")
    op.drop_column("loan_files", "aggression_level_override")
    op.execute(f"ALTER TABLE users DROP CONSTRAINT {_USERS_CK}")
    op.drop_column("users", "default_aggression_level")
