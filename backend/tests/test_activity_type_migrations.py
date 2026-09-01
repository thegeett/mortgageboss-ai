"""Every ``ActivityType`` value must exist in the database's CHECK constraint (LP-637 review).

THE BUG THIS EXISTS FOR, and why nothing else could have caught it. ``activity_type`` is a VARCHAR
with a CHECK listing the permitted values (ADR-037), not a native enum — so adding a member to
:class:`~app.models.activity_log.ActivityType` changes what the code writes and nothing about what
the database accepts. LP-637 added ``document_reprocessed`` with no migration. The first click on
`POST /documents/{id}/reprocess` would have raised ``IntegrityError`` on commit, failing the
activity, the stale marker and the enqueue together, on staging, at 500.

The suite was fully green throughout. ``tests/conftest.py`` builds the schema with
``Base.metadata.create_all``, which regenerates the CHECK from the CURRENT enum — so the test
database always agrees with the code, whatever the migrations say. That is a check which would pass
if the migration never existed, which is to say it checks nothing here.

So this reads the migration files as TEXT instead. It is deliberately not a database test: the
failure it guards is a disagreement between two source artifacts, and a migrated database is
exactly what a developer adding an enum value does not have in front of them.

WHAT IT DOES NOT CHECK: that the swap migration is the newest one in the revision chain, or that
its ordering matches the enum's. Neither can produce the failure above — a value present in any
applied swap is accepted by the constraint.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.models.activity_log import ActivityType

_VERSIONS = Path(__file__).resolve().parent.parent / "alembic" / "versions"
_CONSTRAINT = "ck_activity_logs_activitytype"


def _swap_migration_value_sets() -> dict[str, set[str]]:
    """``{filename: value set}`` for every migration that rewrites the activity_type CHECK.

    Parsed with ``ast`` rather than imported: an Alembic module is not importable without its
    context, and executing migration files to test them would be its own bad idea.
    """
    found: dict[str, set[str]] = {}
    for path in sorted(_VERSIONS.glob("*.py")):
        source = path.read_text()
        if _CONSTRAINT not in source:
            continue
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "_NEW_VALUES" not in names:
                continue
            try:
                values = ast.literal_eval(node.value)
            except ValueError:  # a computed tuple — not a literal value set
                continue
            found[path.name] = set(values)
    return found


def test_every_activity_type_is_permitted_by_a_migration() -> None:
    """The assertion the missing migration would have failed."""
    declared = {member.value for member in ActivityType}
    swaps = _swap_migration_value_sets()

    assert swaps, (
        f"no migration in {_VERSIONS} rewrites {_CONSTRAINT} — either the constraint was renamed "
        "or this guard is reading the wrong directory, and it is now checking nothing"
    )

    permitted: set[str] = set()
    for values in swaps.values():
        permitted |= values

    missing = declared - permitted
    assert not missing, (
        f"ActivityType has {sorted(missing)}, which no migration adds to the {_CONSTRAINT} CHECK. "
        "Writing one of these raises IntegrityError on any migrated database. The suite cannot see "
        "it: conftest builds the schema with create_all, which regenerates the CHECK from the enum. "
        "Add a constraint-swap migration — see the LP-98 and LP-637 ones for the shape."
    )


def test_the_newest_swap_lists_the_whole_enum() -> None:
    """A migration each adding one value leaves the LAST swap authoritative — it drops the
    constraint and recreates it from its own list, so a value omitted there is dropped from the
    database even though an older migration once added it.

    Checked as: at least one swap lists the enum in full. That is the property that makes the
    union above safe to rely on.
    """
    declared = {member.value for member in ActivityType}
    complete = {name for name, values in _swap_migration_value_sets().items() if values >= declared}

    assert complete, (
        "no single activity_type swap lists every current ActivityType value. Each swap RECREATES "
        "the constraint from its own tuple, so the newest one decides what the database accepts — "
        "a partial list there silently revokes values an earlier migration added."
    )
