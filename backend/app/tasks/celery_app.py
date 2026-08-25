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

# Modules Celery imports so their @task definitions register. EVERY module under
# app/tasks/ that defines a @celery_app.task MUST be listed here, or the worker
# never imports it and the task is unregistered — enqueued messages are silently
# discarded (the LP-78 worker-seam bug). A test guards this invariant
# (tests/tasks/test_task_registration.py).
_TASK_MODULES = [
    "app.tasks.health",
    "app.tasks.document_processing",
    "app.tasks.needs",
    "app.tasks.cross_source",
    "app.tasks.verification_rules",  # LP-365 — the governed snapshot/rules pass
]

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
    # LP-629 — a child takes a task only when a slot is genuinely free.
    #
    # `worker_prefetch_multiplier` defaults to 4, so each child RESERVES four tasks and
    # holds them while a sibling sits idle. With this workload that is head-of-line
    # blocking measured in minutes, not milliseconds: a rule-engine pass runs ~405-445s
    # and a document extraction ~30s, so four reserved tasks behind one verification is
    # a 30-second upload waiting a quarter of an hour.
    #
    # Celery's own guidance for long tasks is a multiplier of 1. `worker_disable_prefetch`
    # is strictly better — it removes the reservation rather than shrinking it — and its
    # Redis-broker-only restriction is satisfied here.
    #
    # Deliberately WITHOUT `task_acks_late`. That is the usual companion, and it changes
    # delivery to at-least-once: a hard-killed task is redelivered and re-run. Re-running
    # a ~7-minute, ~$0.30 verification on a worker restart is a different proposition from
    # re-running a 30-second extraction, and a duplicate run is the same collision the
    # in-flight guard in `api/verification.py` exists to prevent. Its own decision, with
    # its own evidence.
    worker_disable_prefetch=True,
    # The DEFAULT time limits — for a task that does no AI work. Soft raises inside the task for
    # graceful handling; hard kills it.
    #
    # LP-625 — THESE ARE NOT SIZED FOR AN AI TASK, and the comment here used to say they were ("sized
    # for a document task (PDF read + up to two AI calls) … tune once real task latencies are known").
    # The latencies are known now: one bank-statement extraction call took 65s and its truncation
    # retry took longer again, so `documents.process_document` never finished inside 120s. It was
    # killed mid-retry and restarted from classification on a 2-minute cycle until MAX_RETRIES ran out
    # and the document was marked FAILED — a document that was extracting correctly, every time.
    #
    # A task that calls a model sets its OWN limit next to the measurement that justifies it:
    # `DOCUMENT_SOFT_LIMIT_SECONDS` (document_processing.py), `RULE_ENGINE_SOFT_LIMIT_SECONDS`
    # (verification_rules.py). Two AI tasks still inherit these defaults —
    # `verification.run_cross_source` (the sweep, ~65s measured, so it fits with little headroom) and
    # `needs.propose_ai_needs` — and both should be measured and given their own before they meet a
    # document that takes longer than today's.
    task_soft_time_limit=120,
    task_time_limit=180,
)
