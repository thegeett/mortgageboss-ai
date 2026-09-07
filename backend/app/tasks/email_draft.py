"""Email-draft composition (LP-809 review) — the model call, OFF the request path.

`add_needs_to_draft` regenerates the draft body every time a need joins it, and both request-docs
routes call that synchronously inside a processor's click. While the framing was composed there, the
click carried an Anthropic round-trip — and one that missed its cache every time, because
`DraftFacts.cache_key` is built from the requested labels and every add changes them. CLAUDE.md is
explicit that long work runs on Celery, not in the request.

So the split: `_cached_framing` reads a stored composition and never calls the model, and this task
does the composing afterwards. The draft is a COMPLETE email in between — the plain template carries
v1's exact wording — so a worker that is slow, or down, or never runs at all costs the file its
composed framing and nothing else.

Enqueued after the commit, by the routes that changed the draft. Two enqueues for one draft are
harmless: `compose_open_draft_prose` returns False without composing once the cache is warm.
"""

from uuid import UUID

import structlog
from celery import Task
from sqlalchemy import select

from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.services.email_draft import compose_open_draft_prose
from app.tasks.base import run_async, task_session
from app.tasks.celery_app import celery_app
from app.tasks.retry import MAX_RETRIES, retry_or_terminal

logger = structlog.get_logger(__name__)


async def _run_compose(loan_file_id: str) -> None:
    try:
        file_pk = UUID(loan_file_id)
    except ValueError:
        return
    async with task_session() as db:
        loan_file = await db.scalar(
            only_active(select(LoanFile).where(LoanFile.id == file_pk), LoanFile)
        )
        if loan_file is None:
            return
        if await compose_open_draft_prose(db, loan_file=loan_file):
            await db.commit()


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True, name="email_draft.compose_prose", max_retries=MAX_RETRIES
)
def compose_draft_prose(self: Task, loan_file_id: str) -> None:
    """Celery task: compose the framing for a file's open draft and re-render its body.

    NOTHING IS MARKED ON EXHAUSTION, and that is the difference from every other task here. The
    others record a visible terminal state because their failure leaves the file short of something
    a processor needs; this one's failure leaves a complete, sendable draft in the plain template's
    words. A `processing_error` nobody can act on would be noise on the communication page.
    """
    retry_or_terminal(
        self,
        lambda: run_async(_run_compose(loan_file_id)),
        on_exhausted=lambda exc: logger.warning(
            "draft_composition_exhausted", loan_file_id=loan_file_id, error=str(exc)
        ),
        event="draft_composition_exhausted",
    )
