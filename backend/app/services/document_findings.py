"""Document findings — the shared recording + query mechanism (LP-66).

A :class:`~app.models.document_finding.DocumentFinding` is a single-document
observation that may affect the loan (an obligation, a property interest, …). The
**same** recording function, :func:`create_document_finding`, is used by every
source — the Tier 3 generic analyzer's ``key_findings`` AND the Tier 1
divorce-decree extractor's obligations — so findings are **uniform across tiers**
(LP-67 + Phase 3 consume them identically regardless of which tier surfaced them).

Distinct from :mod:`app.services.findings`, which resolves the Phase 3 verification
:class:`~app.models.finding.Finding` (a different model — see
:mod:`app.models.document_finding`).

Findings are tenant-scoped transitively (via ``document -> loan_file -> company``);
:func:`list_findings_for_loan_file` is the scoped read for a loan file.
"""

from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.extraction.divorce_decree import DivorceDecreeExtraction
from app.models.document import Document
from app.models.document_finding import (
    DocumentFinding,
    DocumentFindingStatus,
    DocumentFindingType,
)
from app.models.helpers import only_active

logger = structlog.get_logger(__name__)


def coerce_finding_type(value: str | None) -> DocumentFindingType:
    """Map a free-string finding type (from the generic analyzer) to the enum.

    Unknown / absent → ``OTHER`` (the catch-all), so a novel observation is never
    forced into a wrong slot and never crashes the pipeline.
    """
    if not value:
        return DocumentFindingType.OTHER
    try:
        return DocumentFindingType(value.strip().lower())
    except ValueError:
        return DocumentFindingType.OTHER


async def create_document_finding(
    db: AsyncSession,
    *,
    document: Document,
    finding_type: DocumentFindingType,
    description: str,
    amount: Decimal | None = None,
    frequency: str | None = None,
    details: dict[str, Any] | None = None,
    status: DocumentFindingStatus = DocumentFindingStatus.OPEN,
) -> DocumentFinding:
    """Record one finding against a document — the SHARED mechanism (LP-66).

    Used by both the Tier 3 analyzer and the Tier 1 divorce-decree wiring, so every
    finding has the same shape. Tenant-scoped via the document. Flushes (not
    commits) so the caller controls the transaction. Metadata-only log (the
    description/details can quote document PII).
    """
    finding = DocumentFinding(
        document_id=document.id,
        finding_type=finding_type,
        description=description,
        amount=amount,
        frequency=frequency,
        details=details or {},
        status=status,
    )
    db.add(finding)
    await db.flush()
    logger.info(
        "document_finding_recorded",
        document_id=str(document.id),
        finding_type=finding_type,  # a category, not PII
    )
    return finding


async def record_findings_from_extraction(db: AsyncSession, document: Document, data: Any) -> int:
    """Translate a Tier 1 extraction's captured data into findings (LP-66).

    Closes the LP-63 deferral: a divorce decree's support obligations (captured in
    its typed core) become :class:`DocumentFinding`\\ s via the SAME
    :func:`create_document_finding` the Tier 3 analyzer uses — uniform findings
    across tiers. Other extraction types record nothing here today (extend as more
    finding-bearing types are added). Returns the number of findings recorded.
    """
    if isinstance(data, DivorceDecreeExtraction):
        return await _record_divorce_decree_findings(db, document, data)
    return 0


async def _record_divorce_decree_findings(
    db: AsyncSession, document: Document, data: DivorceDecreeExtraction
) -> int:
    """A divorce decree's support obligations → ``obligation`` findings."""
    count = 0
    for ob in data.support_obligations:
        kind = ob.obligation_type or "support"
        freq = f" ({ob.frequency})" if ob.frequency else ""
        await create_document_finding(
            db,
            document=document,
            finding_type=DocumentFindingType.OBLIGATION,
            description=f"{kind} obligation from divorce decree{freq}",
            amount=ob.amount,
            frequency=ob.frequency,
            details={
                "payer": ob.payer,
                "obligation_type": ob.obligation_type,
                "source": "divorce_decree",
            },
        )
        count += 1
    return count


async def list_findings_for_loan_file(
    db: AsyncSession, *, loan_file_id: UUID
) -> list[DocumentFinding]:
    """All active findings for a loan file (via its documents), newest first.

    Tenant scoping is the caller's job: resolve the loan file scoped to the company
    first (the API uses ``ScopedLoanFile`` → 404 cross-company), then pass its id
    here. Findings are reachable only through their company's loan file.
    """
    stmt = (
        select(DocumentFinding)
        .join(Document, DocumentFinding.document_id == Document.id)
        .where(Document.loan_file_id == loan_file_id)
        .order_by(DocumentFinding.created_at.desc())
    )
    stmt = only_active(stmt, DocumentFinding)
    stmt = only_active(stmt, Document)
    result = await db.scalars(stmt)
    return list(result.all())
