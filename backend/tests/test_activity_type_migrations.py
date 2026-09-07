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

WHAT IT DOES NOT CHECK: that a swap's ordering matches the enum's. Order is cosmetic — the
constraint is an ``IN`` list.

AN EARLIER VERSION OF THIS DOCSTRING ALSO WAIVED CHAIN POSITION, on the reasoning that "a value
present in any applied swap is accepted by the constraint". That is false, and it is the reasoning
that let LP-UI-033 reach staging. A swap DROPS the constraint and recreates it from its own tuple,
so what the database accepts is the set of the swap applied LAST — not the union of every swap. A
value added by an earlier migration and omitted by a later one is revoked, and if a row already
carries it the ``ADD CONSTRAINT`` is rejected and the upgrade dies. That is what
``test_parallel_swaps_permit_identical_value_sets`` below is for.
"""

from __future__ import annotations

import ast
from itertools import combinations
from pathlib import Path

from app.models.activity_log import ActivityType

_VERSIONS = Path(__file__).resolve().parent.parent / "alembic" / "versions"
_CONSTRAINT = "ck_activity_logs_activitytype"


_UNRESOLVED = object()


def _resolve(node: ast.AST | None, env: dict[str, object]) -> object:
    """Best-effort constant folding for the tuple forms these migrations actually use.

    NOT `ast.literal_eval` alone. Every value set here is built from module constants —
    ``(*_OLD[:9], "field_reviewed", ...)`` in one file, ``(*_BASE, "x", "y")`` in another — and
    `literal_eval` raises on all of them. The first version of this guard caught the exception and
    moved on, so those migrations were skipped in silence and the guard covered a subset of the
    directory while reporting success. That is how LP-UI-033 shipped a swap that revoked four live
    values. Anything unresolvable is now reported, not skipped.
    """
    if node is None:
        return _UNRESOLVED
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        pass
    if isinstance(node, ast.Name):
        return env.get(node.id, _UNRESOLVED)
    if isinstance(node, ast.Tuple):
        out: list[object] = []
        for element in node.elts:
            if isinstance(element, ast.Starred):
                inner = _resolve(element.value, env)
                if not isinstance(inner, tuple):
                    return _UNRESOLVED
                out.extend(inner)
                continue
            value = _resolve(element, env)
            if value is _UNRESOLVED:
                return _UNRESOLVED
            out.append(value)
        return tuple(out)
    if isinstance(node, ast.Subscript):
        base = _resolve(node.value, env)
        if not isinstance(base, tuple):
            return _UNRESOLVED
        if isinstance(node.slice, ast.Slice):
            lower = _resolve(node.slice.lower, env) if node.slice.lower else None
            upper = _resolve(node.slice.upper, env) if node.slice.upper else None
            if lower is _UNRESOLVED or upper is _UNRESOLVED:
                return _UNRESOLVED
            return base[slice(lower, upper)]  # type: ignore[arg-type]
        index = _resolve(node.slice, env)
        return base[index] if isinstance(index, int) else _UNRESOLVED
    return _UNRESOLVED


def _module_constants(tree: ast.Module, env: dict[str, object]) -> None:
    """Fold module-level assignments into ``env``, in source order."""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        else:
            continue
        value = _resolve(node.value, env)
        if value is not _UNRESOLVED:
            for name in names:
                env[name] = value


def _upgrade_swap_values(tree: ast.Module, env: dict[str, object]) -> object:
    """The tuple `upgrade()` hands to the swap helper.

    Read from the CALL rather than from a constant of an agreed name. Four different names are in
    use across this directory (`_NEW_VALUES`, `_NEW_ACTIVITY_TYPES`, `_ACTIVITY_NEW`, ...), and a
    guard keyed on a name is one rename away from silently checking nothing — which is exactly what
    happened. The call site is the thing that decides what the database gets.
    """
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name != "upgrade":
            continue
        for call in ast.walk(node):
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and "swap" in call.func.id
                and call.args
            ):
                return _resolve(call.args[0], env)
    return _UNRESOLVED


def _swap_migration_value_sets() -> dict[str, set[str]]:
    """``{filename: value set}`` for every migration that rewrites the activity_type CHECK.

    Parsed with ``ast`` rather than imported: an Alembic module is not importable without its
    context, and executing migration files to test them would be its own bad idea.

    Raises rather than skipping when a file touches the constraint and its upgrade value cannot be
    resolved. A guard that quietly covers part of a directory is worse than no guard, because it
    reports the same green either way.
    """
    found: dict[str, set[str]] = {}
    unreadable: list[str] = []
    for path in sorted(_VERSIONS.glob("*.py")):
        source = path.read_text()
        if _CONSTRAINT not in source:
            continue
        tree = ast.parse(source)
        env: dict[str, object] = {}
        _module_constants(tree, env)
        values = _upgrade_swap_values(tree, env)
        if not isinstance(values, tuple) or not all(isinstance(v, str) for v in values):
            unreadable.append(path.name)
            continue
        found[path.name] = {str(v) for v in values}

    assert not unreadable, (
        "these migrations rewrite " + _CONSTRAINT + " but this guard cannot work out which values "
        "their upgrade() installs, so every assertion below silently excluded them:\n  "
        + "\n  ".join(unreadable)
        + "\nExpress the value set as module-level constants built from literals, or teach "
        "_resolve() the form used."
    )
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


def _revision_graph() -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    """``({revision: parents}, {revision: filename})`` across every migration, swap or not.

    Ancestry needs the whole chain, not just the swaps: two swaps are "parallel" precisely when
    neither reaches the other through migrations that do not touch this constraint.
    """
    parents: dict[str, tuple[str, ...]] = {}
    filenames: dict[str, str] = {}
    for path in sorted(_VERSIONS.glob("*.py")):
        module: dict[str, object] = {}
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                name, value = node.target.id, node.value
            elif (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                name, value = node.targets[0].id, node.value
            else:
                continue
            if name in ("revision", "down_revision") and value is not None:
                try:
                    module[name] = ast.literal_eval(value)
                except ValueError:
                    continue
        revision = module.get("revision")
        if not isinstance(revision, str):
            continue
        down = module.get("down_revision")
        if down is None:
            resolved: tuple[str, ...] = ()
        elif isinstance(down, str):
            resolved = (down,)
        elif isinstance(down, (tuple, list)):
            resolved = tuple(str(item) for item in down)  # a merge migration
        else:
            continue
        parents[revision] = resolved
        filenames[revision] = path.name
    return parents, filenames


def _ancestors(revision: str, parents: dict[str, tuple[str, ...]]) -> set[str]:
    """Every revision reachable by walking down from ``revision``."""
    seen: set[str] = set()
    queue = list(parents.get(revision, ()))
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        queue.extend(parents.get(current, ()))
    return seen


def _swap_revisions() -> dict[str, set[str]]:
    """``{revision: value set}`` for the swaps, keyed by revision rather than filename."""
    _, filenames = _revision_graph()
    by_filename = _swap_migration_value_sets()
    return {
        revision: by_filename[name] for revision, name in filenames.items() if name in by_filename
    }


def test_parallel_swaps_permit_identical_value_sets() -> None:
    """Two swaps on lineages that have not merged must permit exactly the same values.

    THE FAILURE. `mbai-ui-improvement` and `bedrock_integration_with_rules_staging` each added
    activity types, each rewriting the constraint from a tuple that predated the other's values.
    Alembic may run either lineage first, so the second one to run REVOKES what the first added.
    On staging — which had run the LP-643 lineage for weeks and held `document_reprocessed` and
    `dti_*` rows — LP-UI-033's swap was rejected outright:

        CheckViolationError: check constraint "ck_activity_logs_activitytype"
        of relation "activity_logs" is violated by some row

    and because Alembic wraps the upgrade in one transaction, the whole deploy rolled back at the
    migration step. The merge migration DID repair the constraint, but it runs after the swap that
    cannot get past the data, so it never executed.

    WHY IDENTICAL AND NOT MERELY OVERLAPPING. If A must permit everything B adds, and B must permit
    everything A adds, the two sets are equal. So the rule is stated the way it is checked.

    The fix for a failure here is never to reorder migrations — it is to write the UNION into both
    tuples, which is what every diverged swap in this directory now carries.
    """
    parents, filenames = _revision_graph()
    swaps = _swap_revisions()

    assert swaps, "no swap revisions resolved — this guard is checking nothing"

    mismatches: list[str] = []
    for left, right in combinations(sorted(swaps), 2):
        if left in _ancestors(right, parents) or right in _ancestors(left, parents):
            continue  # one precedes the other; a lineage may widen as it goes
        if swaps[left] == swaps[right]:
            continue
        mismatches.append(
            f"{filenames[left]} ({len(swaps[left])} values) and {filenames[right]} "
            f"({len(swaps[right])} values) are on parallel lineages but disagree: "
            f"only in {filenames[left]}: {sorted(swaps[left] - swaps[right]) or '-'}; "
            f"only in {filenames[right]}: {sorted(swaps[right] - swaps[left]) or '-'}"
        )

    assert not mismatches, (
        "parallel activity_type swaps permit different value sets. Whichever runs second will "
        "revoke the other's values, and any existing row carrying one makes the ADD CONSTRAINT "
        "fail — stopping the upgrade before the merge migration that would repair it.\n  "
        + "\n  ".join(mismatches)
    )
