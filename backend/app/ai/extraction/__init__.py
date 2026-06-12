"""Extraction package — the per-type extractors + the dispatch registry (LP-39c).

Each document type has its own extractor (``extract_pay_stub`` / ``extract_w2`` /
``extract_bank_statement``) producing the LP-39a shape (typed core + grouped
catch-all, plus a transactions list for bank statements). The pipeline (LP-42
``process_document`` and the reprocess path) routes extraction through
:data:`EXTRACTORS` — adding a type later is "write an extractor + register it",
the clean form for Phase 2's ~100 types. An unregistered type is classified-only.

The result types share a structural :class:`ExtractionResult` interface (``data``
with ``model_dump``, ``status``, ``confidence``, ``reasoning``, token usage), so
the pipeline stores any of them uniformly via ``create_extraction_version``.
"""

from collections.abc import Awaitable, Callable
from typing import Protocol

from pydantic import BaseModel

from app.ai.extraction.bank_statement import extract_bank_statement
from app.ai.extraction.pay_stub import extract_pay_stub
from app.ai.extraction.w2 import extract_w2
from app.models.extraction import ExtractionStatus


class ExtractionResult(Protocol):
    """The common shape every extractor returns (structural — the pipeline reads these)."""

    status: ExtractionStatus
    confidence: float
    reasoning: str | None
    input_tokens: int | None
    output_tokens: int | None

    @property
    def data(self) -> BaseModel:  # serialized via model_dump(mode="json")
        ...


# An extractor: ``async (content: bytes, media_type: str) -> ExtractionResult``.
Extractor = Callable[[bytes, str], Awaitable[ExtractionResult]]

# document_type → extractor. Register a new type's extractor here (Phase 2).
EXTRACTORS: dict[str, Extractor] = {
    "pay_stub": extract_pay_stub,
    "w2": extract_w2,
    "bank_statement": extract_bank_statement,
}

__all__ = ["EXTRACTORS", "ExtractionResult", "Extractor"]
