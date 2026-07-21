"""LP-381 — statement page counts (unblock AS-9): the printed "of N" + the DETERMINISTIC actual page total.

AS-9 ("missing pages") compares the page count the statement PRINTS ("Page 1 of 5") against the pages actually
present. These pin: page_count_present is computed DETERMINISTICALLY from the PDF (never a model read — a
model miscount must never fabricate completeness) and is absent for non-PDFs; page_count_declared is the
model's read of the printed "of N"; and the emitted field names MATCH AS-9's declared tag data (the LP-333/369
silent-death trap closed for this field).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pymupdf
import pytest
from app.ai.extraction import model_call
from app.ai.extraction.bank_statement import extract_bank_statement
from app.services.pdf_utils import pdf_page_count
from app.verification.tag_materialization.declarations import load_declarations

pytestmark = pytest.mark.anyio

# A bank-statement extraction JSON with the model's page_count_declared (the printed "of 5").
_JSON = json.dumps(
    {
        "typed_core": {
            "bank_name": {"value": "First Bank", "page": 1, "snippet": "First Bank"},
            "ending_balance": {"value": "100.00", "page": 1, "snippet": "Ending 100.00"},
            "page_count_declared": {"value": 5, "page": 1, "snippet": "Page 1 of 5"},
        },
        "transactions": [
            {
                "date": "2026-06-01",
                "description": "Deposit",
                "amount": "100.00",
                "transaction_type": "deposit",
            }
        ],
        "additional_sections": [],
        "confidence": 0.9,
        "reasoning": "checking statement",
    }
)


def _pdf(pages: int) -> bytes:
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    for _ in range(pages):
        doc.new_page()  # type: ignore[no-untyped-call]
    data: bytes = doc.tobytes()  # type: ignore[no-untyped-call]
    doc.close()  # type: ignore[no-untyped-call]
    return data


def _mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        model_call,
        "complete",
        AsyncMock(
            return_value=type(
                "R",
                (),
                {
                    "text": _JSON,
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "model": "m",
                    "stop_reason": "end_turn",
                },
            )()
        ),
    )


# --------------------------------------------------------------------------- #
# pdf_page_count — deterministic, from the file, never raises
# --------------------------------------------------------------------------- #
async def test_pdf_page_count_is_the_real_page_total() -> None:
    assert await pdf_page_count(_pdf(3)) == 3
    assert await pdf_page_count(_pdf(1)) == 1
    assert await pdf_page_count(b"not a pdf") is None  # unreadable → None, never raises


# --------------------------------------------------------------------------- #
# The extractor sets present DETERMINISTICALLY and declared from the model
# --------------------------------------------------------------------------- #
async def test_extractor_sets_present_from_the_pdf_and_declared_from_the_model(monkeypatch) -> None:
    _mock(monkeypatch)
    result = await extract_bank_statement(_pdf(3), "application/pdf")
    # present = the ACTUAL PDF page total (3), computed deterministically — NOT the model's "of 5".
    assert result.data.page_count_present.value == 3
    # declared = the model's read of the printed "of N".
    assert result.data.page_count_declared.value == 5


async def test_present_is_absent_for_a_non_pdf_statement(monkeypatch) -> None:
    _mock(monkeypatch)
    # a JPEG statement: no deterministic PDF page total → present stays absent → AS-9 honestly couldnt_checks.
    result = await extract_bank_statement(b"\xff\xd8\xff dummy-jpeg", "image/jpeg")
    assert result.data.page_count_present.value is None


# --------------------------------------------------------------------------- #
# The name-match — the emitted field names ARE the tags' declared `data` (LP-333/369 trap closed)
# --------------------------------------------------------------------------- #
def test_page_count_tag_field_names_match_the_extractor() -> None:
    from app.ai.extraction.bank_statement import BankStatementExtraction

    fields = set(BankStatementExtraction().model_dump())
    decls = load_declarations()
    for tag in ("stmt.page_count_declared", "stmt.page_count_present"):
        assert decls[tag].data in fields  # the tag's `data` field name is emitted by the extractor
