"""Guard: every Celery task module is registered with the app (worker-seam).

The LP-78 cross-source bug was a *worker seam* a normal unit test misses: the task
module existed and was decorated, but it was never added to the Celery app's
``include`` list, so the worker never imported it — the task was unregistered and
enqueued messages were silently discarded. Green unit tests said nothing.

This closes the whole class, not just that one instance: it scans ``app/tasks/``
for files that define a ``@celery_app.task`` decorator and asserts each is in
``_TASK_MODULES`` (so the worker imports it), and that the registered task names
are actually present on the Celery app. Any future task module that forgets
registration fails here.
"""

from pathlib import Path

import app.tasks
from app.tasks.celery_app import _TASK_MODULES, celery_app

_TASKS_DIR = Path(app.tasks.__file__).parent


def _modules_defining_tasks() -> list[str]:
    """Dotted module paths under app/tasks/ that define a @celery_app.task.

    Matches only real decorator lines (a stripped line starting with
    ``@celery_app.task``), so comments/docstrings mentioning the decorator (e.g.
    in ``base.py`` / ``celery_app.py``) are not false positives.
    """
    modules: list[str] = []
    for path in sorted(_TASKS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        defines_task = any(
            line.strip().startswith("@celery_app.task") for line in path.read_text().splitlines()
        )
        if defines_task:
            modules.append(f"app.tasks.{path.stem}")
    return modules


def test_every_task_module_is_in_the_include_list() -> None:
    """Each module defining a task must be in _TASK_MODULES (or the worker drops it)."""
    defining = _modules_defining_tasks()
    assert defining, "expected to find task-defining modules under app/tasks/"
    missing = [module for module in defining if module not in _TASK_MODULES]
    assert not missing, (
        "task modules define @celery_app.task but are NOT in _TASK_MODULES — the "
        f"worker will never register them (enqueued messages discarded): {missing}"
    )


def test_known_tasks_are_registered_on_the_app() -> None:
    """Importing the include list registers the tasks on the Celery app."""
    for module in _TASK_MODULES:
        __import__(module)
    # The tasks the system enqueues by name must be registered.
    for name in (
        "verification.run_cross_source",  # the LP-78 task that was missing
        "needs.propose_ai_needs",
        "documents.process_document",
    ):
        assert name in celery_app.tasks, f"task not registered with the worker: {name}"
