"""LP-1006 — the hourly check of customer mail domains.

`check_all` runs `services.mail_domain.check_mail_domain` on every domain that has a zone and is not
`inactive`: it finishes setup on its own, marks a broken domain `problem`, and brings a fixed one back.

LOGS CARRY DOMAINS AND COUNTS ONLY.
"""

from collections import Counter

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company_mail_domain import CompanyMailDomain, MailDomainStatus
from app.services.domain_provider import (
    DomainProvider,
    DomainProviderNotAllowed,
    get_domain_provider,
)
from app.services.mail_domain import check_mail_domain
from app.tasks.base import BaseTask, run_async, task_session
from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)


async def _check_all(db: AsyncSession, provider: DomainProvider) -> dict[str, int]:
    """Check each domain, and log one summary line. One domain failing doesn't stop the others."""
    row_ids = (
        await db.scalars(
            select(CompanyMailDomain.id).where(
                CompanyMailDomain.zone_id.is_not(None),
                CompanyMailDomain.status != MailDomainStatus.INACTIVE,
            )
        )
    ).all()
    outcomes: Counter[str] = Counter()
    for row_id in row_ids:
        try:
            row = await db.get(CompanyMailDomain, row_id, populate_existing=True)
            if row is not None:
                outcomes[await check_mail_domain(db, row, provider)] += 1
        except Exception as exc:
            await db.rollback()
            logger.warning("mail_domain_check_crashed", error=type(exc).__name__)
            outcomes["error"] += 1
    logger.info("mail_domains_checked", total=len(row_ids), **outcomes)
    return dict(outcomes)


async def _run_check_all(provider: DomainProvider) -> dict[str, int]:
    async with task_session() as db:
        return await _check_all(db, provider)


@celery_app.task(base=BaseTask, name="mail_domains.check_all")  # type: ignore[untyped-decorator]
def check_all() -> dict[str, int]:
    """Beat, hourly (`celery_app.beat_schedule`)."""
    try:
        provider = get_domain_provider()
    except DomainProviderNotAllowed as exc:
        logger.warning("mail_domains_check_not_run", reason=str(exc))
        return {}
    return run_async(_run_check_all(provider))
