"""Dev-only endpoints (LP-40) — present ONLY in non-production.

This router is mounted in ``main.py`` **only when** ``not settings.is_production``,
so in production its routes are absent (404). Dev tools are still **auth'd and
tenant-scoped** — touching real documents is no excuse to skip isolation.

The one endpoint here runs the deterministic PDF text-layer extractor
(``app/services/pdf_utils.py``) on a stored document so a developer can compare
the text layer against the AI's reading (LP-38/39). It is an experiment harness,
**not** a pipeline step: it does not modify the ``Document``, classify, extract,
or route anything to review.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies import CurrentUser
from app.core.database import DbSession
from app.services.documents import get_document_for_company
from app.services.pdf_utils import extract_text_from_pdf
from app.storage import get_storage_backend

dev_router = APIRouter(tags=["dev"])


class TextLayerExtractionResponse(BaseModel):
    """The deterministic text-layer extraction returned for developer inspection.

    ``text`` is returned (that is the whole point — for the developer to read);
    it is **never logged**. ``has_text`` is informational (empty layer → likely a
    scan). ``extraction_ok`` is False (with ``error_reason``) for a non-PDF,
    corrupt, or encrypted document.
    """

    text: str
    page_count: int
    has_text: bool
    extraction_ok: bool
    error_reason: str | None = None


@dev_router.post(
    "/documents/{document_id}/extract-text-layer",
    response_model=TextLayerExtractionResponse,
)
async def extract_text_layer(
    document_id: UUID, current_user: CurrentUser, db: DbSession
) -> TextLayerExtractionResponse:
    """Return a stored document's deterministic PDF text layer (dev comparison tool).

    Tenant-scoped via :func:`get_document_for_company` (a Company A user gets
    ``404`` for a Company B document). PDF only — a non-PDF document returns a
    clear ``extraction_ok=False`` response rather than an error. Reads the bytes
    from storage and runs the deterministic extractor; does **not** touch the
    ``Document`` or the AI pipeline.
    """
    document = await get_document_for_company(
        db, document_id=document_id, company_id=current_user.company_id
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    if document.mime_type != "application/pdf":
        return TextLayerExtractionResponse(
            text="",
            page_count=0,
            has_text=False,
            extraction_ok=False,
            error_reason="text-layer extraction supports PDF only",
        )

    content = await get_storage_backend().read(document.storage_path)
    result = await extract_text_from_pdf(content)
    return TextLayerExtractionResponse(
        text=result.text,
        page_count=result.page_count,
        has_text=result.has_text,
        extraction_ok=result.extraction_ok,
        error_reason=result.error_reason,
    )
