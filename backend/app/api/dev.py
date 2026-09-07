"""Dev-only endpoints (LP-40) — present ONLY in non-production.

This router is mounted in ``main.py`` **only when** ``not settings.is_production``,
so in production its routes are absent (404). Dev tools are still **auth'd and
tenant-scoped** — touching real documents is no excuse to skip isolation.

LP-803 adds a second: the raw-message injector (§H1). It takes an ``.eml`` and runs it through the
same ingest the SQS consumer would, so everything downstream of ``inbound.ingest_message`` is
testable on a laptop with no AWS at all. Without it LP-804 and LP-805 are written blind and debugged
in staging.

The first endpoint here runs the deterministic PDF text-layer extractor
(``app/services/pdf_utils.py``) on a stored document so a developer can compare
the text layer against the AI's reading (LP-38/39). It is an experiment harness,
**not** a pipeline step: it does not modify the ``Document``, classify, extract,
or route anything to review.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.api.dependencies import CurrentUser
from app.core.database import DbSession
from app.services.documents import get_document_for_company
from app.services.inbound_ingest import process_raw_message
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


class InjectedMessageResponse(BaseModel):
    """What the injector did with the `.eml` it was handed.

    ``created`` is False when the message was already ingested — which is not an error and is the
    behaviour the ticket's "Done when" turns on. Injecting the same file twice is the cheapest way to
    check the dedup contract by hand.
    """

    inbound_message_id: str
    created: bool
    ingest_key: str


@dev_router.post("/inbound/inject", response_model=InjectedMessageResponse)
async def inject_raw_message(
    db: DbSession,
    current_user: CurrentUser,
    file: Annotated[UploadFile, File(description="A raw RFC 5322 message (.eml)")],
    ses_message_id: Annotated[str | None, Form()] = None,
    dmarc_verdict: Annotated[str | None, Form()] = None,
) -> InjectedMessageResponse:
    """Ingest an `.eml` exactly as the SQS consumer would (LP-803, §H1). Dev only.

    ``ses_message_id`` and ``dmarc_verdict`` stand in for the SES receipt, which does not exist off
    AWS. They are FORM FIELDS rather than derived from the message, and that is the point: the
    verdicts must come from the receipt and never from a header in the body, so the injector cannot
    offer a shortcut that the real path does not have. Passing a `dmarcVerdict` of GRAY here is how
    the GRAY-stays-GRAY behaviour is exercised without waiting for a real message to be graded.

    ``store_raw=True`` writes the bytes through the configured storage backend and records that
    path. The first version passed ``raw_storage_path=None`` on the reasoning that nothing came from
    S3 so nothing should be recorded — true, and the consequence was that everything downstream of
    ingest was dead locally: accept-into-file and the attachment preview both re-derive the bytes
    from the stored message rather than keeping a second copy, so a NULL path means an injected
    message can be listed and never opened or accepted. Storing it locally is not a fiction; it is
    the same object SES would have written, in the backend this environment actually uses.

    The path is built from the new row's uuid (`raw_storage_path_for`) and never from a header or a
    filename.

    Mounted only when ``not settings.is_production`` (see `main.py`), and still auth'd — a dev tool
    is not an excuse to skip the tenant gate, even one that writes an unrouted row belonging to
    nobody yet.
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="The uploaded file was empty"
        )
    receipt = {"dmarcVerdict": {"status": dmarc_verdict}} if dmarc_verdict else None
    result = await process_raw_message(
        db,
        raw=raw,
        raw_storage_path=None,
        ses_message_id=ses_message_id,
        receipt=receipt,
        store_raw=True,
    )
    await db.commit()
    return InjectedMessageResponse(
        inbound_message_id=result.message_id,
        created=result.created,
        ingest_key=result.ingest_key,
    )
