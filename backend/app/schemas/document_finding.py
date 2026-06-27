"""DocumentFinding response schema (LP-66).

A read view of a single-document observation (:class:`DocumentFinding`) — the
feedstock the implications engine (LP-67) + Phase 3 consume. The full tier-aware
display is LP-72; this is the API shape findings are surfaced through.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.document_finding import DocumentFindingStatus, DocumentFindingType


class DocumentFindingResponse(BaseModel):
    """One document finding (an obligation, property interest, …)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    finding_type: DocumentFindingType
    description: str
    amount: Decimal | None
    frequency: str | None
    details: dict[str, Any]
    status: DocumentFindingStatus
    created_at: datetime
