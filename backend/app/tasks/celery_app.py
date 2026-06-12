"""Celery application — the background task queue (LP-41).

Infrastructure only: this builds the configured Celery app (Redis broker +
result backend, from settings) on which the real document-processing tasks
(``app/tasks/document_processing.py``, LP-42) will run. Creating this app object
does **not** require a live Redis connection — the broker is only contacted when
a task is enqueued or a worker starts, so it imports cleanly in the API process
and in tests.

Serialization is **JSON only** (``accept_content=["json"]``) — pickle is
deliberately disabled, since a pickle deserializer is a remote-code-execution
risk if the broker is ever compromised. Times are UTC.
"""

from celery import Celery

from app.core.config import settings

# Modules Celery imports so their @task definitions register. LP-42 appends its
# own module ("app.tasks.document_processing") here.
_TASK_MODULES = ["app.tasks.health"]

celery_app = Celery(
    "mortgageboss",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=_TASK_MODULES,
)

celery_app.conf.update(
    # Safe serialization — JSON only, never pickle (RCE risk).
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Time handling.
    timezone="UTC",
    enable_utc=True,
    # Mark tasks STARTED (not just PENDING→SUCCESS) so progress is observable.
    task_track_started=True,
    # Time limits sized for a document task (PDF read + up to two AI calls).
    # Soft limit raises inside the task for graceful handling; hard limit kills it.
    # Generous for V1; tune once real task latencies are known.
    task_soft_time_limit=120,
    task_time_limit=180,
)
