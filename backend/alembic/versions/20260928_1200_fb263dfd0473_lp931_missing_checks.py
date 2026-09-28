"""LP-931 — the three CHECK constraints the models declare and no migration ever created.

`communications.body_format`, `users.mail_client` and `validation_verdicts.kind` are `str_enum`
columns, so `create_all` gives each a CHECK and the suite has always had one. A migrated database has
none: LP-89 declared `kind` with a bare `sa.Enum(native_enum=False)`, whose `create_constraint`
defaults to False in SQLAlchemy 2, and LP-853 / LP-855 added the other two as plain `String` columns.
Each accepts any string on a migrated database today. `tests/test_migrated_checks_match_models.py`
found them and listed them in `_KNOWN_MISSING`; this migration is that list's follow-up.

RAW `op.execute`, NEVER `op.create_check_constraint`. `Base.metadata`'s naming convention prefixes a
constraint name AGAIN when Alembic creates it, which is how LP-904's CHECKs became
`ck_conditions_ck_conditions_...` (LP-912). A literal `ALTER TABLE ... ADD CONSTRAINT` is named exactly
what it says, and the names below are the ones `create_all` emits (`ck_<table>_<enum class>`).

THE VALUES ARE LITERALS, NOT READ FROM THE ENUMS. A migration is a record of what was installed on the
day it ran; importing the enum would make this file install whatever the enum says on the day it is
replayed. The migrated-vs-models guard is what keeps the two equal.

EXISTING ROWS ARE CHECKED FIRST, AND A BAD ONE STOPS THE MIGRATION. Postgres would refuse the ADD
CONSTRAINT anyway, but with a message naming only the constraint. The check below names every
offending value and its count, and says nothing was changed. It never rewrites a row: which value a
bad row should have held is a decision for a person, not for a migration.

Revision ID: fb263dfd0473
Revises: a7c31e6d94b2
Create Date: 2026-09-28 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fb263dfd0473"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "a7c31e6d94b2"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (table, column, constraint name as `create_all` emits it, permitted values)
_CHECKS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("communications", "body_format", "ck_communications_bodyformat", ("plain", "html")),
    (
        "users",
        "mail_client",
        "ck_users_mailclient",
        ("gmail", "outlook_work", "outlook_personal", "mailto"),
    ),
    (
        "validation_verdicts",
        "kind",
        "ck_validation_verdicts_verdictkind",
        ("validated", "corrected", "flagged_remove", "add_new"),
    ),
)


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    bind = op.get_bind()

    # NULL is not a violation: a CHECK passes on NULL, and `mail_client` is nullable by design (no
    # choice made yet). `body_format` and `kind` are NOT NULL, so they cannot hold one.
    offending: list[str] = []
    for table, column, _name, values in _CHECKS:
        rows = bind.execute(
            sa.text(
                f"SELECT {column} AS value, count(*) AS n FROM {table} "
                f"WHERE {column} IS NOT NULL AND {column} NOT IN ({_in_list(values)}) "
                f"GROUP BY {column} ORDER BY {column}"
            )
        ).all()
        offending.extend(f"  {table}.{column} = {row.value!r}: {row.n} row(s)" for row in rows)

    if offending:
        raise RuntimeError(
            "LP-931 refused to add its CHECK constraints, and changed nothing: these rows hold a "
            "value outside the permitted set.\n"
            + "\n".join(offending)
            + "\nDecide what each should hold and correct it by hand, then run the migration again. "
            "The read-only query that lists them is in docs/tickets/LP-931.md."
        )

    for table, column, name, values in _CHECKS:
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({column} IN ({_in_list(values)}))"
        )


def downgrade() -> None:
    for table, _column, name, _values in reversed(_CHECKS):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
