"""The migration chain must have exactly one head (bug found by a staging deploy, 2026-09-05).

WHY THIS IS A TEST AND NOT A HABIT. Merging `raspberrypi-work` merged the migration FILES without
merging the CHAIN: both branches had added a revision after their common ancestor, so two revisions
each claimed to be head. Nothing catches that on the way in — a git merge has no opinion about
Alembic's DAG, and `tests/conftest.py` builds its schema with `Base.metadata.create_all` and never
runs a migration at all, so the entire suite passed while `alembic upgrade head` was unrunnable.

It surfaced where it is most expensive: a staging deploy, at the migration step, after both images
had been built and pushed. The deploy stopped safely — nothing had been written — but the cost was a
full build cycle and a failed release.

This is cheap, needs no database, and fails the moment a second head appears.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_there_is_exactly_one_migration_head() -> None:
    """`alembic upgrade head` is ambiguous with more than one, and refuses to run.

    The fix for a legitimate fork is a merge revision (`alembic merge <a> <b>`), which is a no-op
    mergepoint joining the two chains — not deleting or re-parenting either side's migration.
    """
    root = Path(__file__).resolve().parent.parent
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()

    assert len(heads) == 1, (
        f"{len(heads)} migration heads: {sorted(heads)}. `alembic upgrade head` cannot resolve "
        "this and every deploy will fail at the migration step. If two branches each added a "
        "revision, join them with `alembic merge` rather than re-parenting either one."
    )
