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
from app.ai.extraction.divorce_decree import extract_divorce_decree
from app.ai.extraction.drivers_license import extract_drivers_license
from app.ai.extraction.form_1099 import extract_1099
from app.ai.extraction.gift_letter import extract_gift_letter
from app.ai.extraction.hoa_statement import extract_hoa_statement
from app.ai.extraction.homeowners_insurance import extract_homeowners_insurance
from app.ai.extraction.investment_account import extract_investment_account
from app.ai.extraction.letter_of_explanation import extract_letter_of_explanation
from app.ai.extraction.mortgage_statement import extract_mortgage_statement
from app.ai.extraction.pay_stub import extract_pay_stub
from app.ai.extraction.profit_and_loss import extract_profit_and_loss
from app.ai.extraction.property_tax_bill import extract_property_tax_bill
from app.ai.extraction.purchase_agreement import extract_purchase_agreement
from app.ai.extraction.retirement_account import extract_retirement_account
from app.ai.extraction.tax_return import extract_tax_return
from app.ai.extraction.voe import extract_voe
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

# document_type → extractor. Register a new type's extractor here (Phase 2). The
# keys MUST match the catalog's Tier-1 slugs (app/documents/catalog.py) so the
# tier-aware routing (LP-58) dispatches each Tier-1 type to its extractor.
EXTRACTORS: dict[str, Extractor] = {
    # Phase 1 (LP-39).
    "pay_stub": extract_pay_stub,
    "w2": extract_w2,
    "bank_statement": extract_bank_statement,
    # LP-60 — Tier 1 income/employment cluster.
    "1099": extract_1099,
    "voe": extract_voe,
    "profit_and_loss": extract_profit_and_loss,
    "letter_of_explanation": extract_letter_of_explanation,
    # LP-61 — Tier 1 asset cluster.
    "investment_account": extract_investment_account,
    "retirement_account": extract_retirement_account,
    "gift_letter": extract_gift_letter,
    # LP-62 — Tier 1 property cluster.
    "purchase_agreement": extract_purchase_agreement,
    "homeowners_insurance": extract_homeowners_insurance,
    "mortgage_statement": extract_mortgage_statement,
    "property_tax_bill": extract_property_tax_bill,
    "hoa_statement": extract_hoa_statement,
    # LP-63 — Tier 1 borrower-info / legal cluster. (letter_of_explanation is the
    # general-LOE extractor from LP-60, reused — registered above.)
    "drivers_license": extract_drivers_license,
    "divorce_decree": extract_divorce_decree,
    # LP-64 — Tier 1 tax returns (the nested 1040 + schedules bundle). Completes
    # Tier 1: every Tier-1 catalog type now has an extractor.
    "tax_return": extract_tax_return,
}

__all__ = ["EXTRACTORS", "ExtractionResult", "Extractor"]
