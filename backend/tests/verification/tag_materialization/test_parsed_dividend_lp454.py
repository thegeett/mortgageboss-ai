"""LP-454 (step D.3) — the parsed-tag dividend: the TWO tags Phase A found POPULATED + clean in stored data.

Of LP-451's ~16 needs-parsed-tag candidates, only two are populated with clean values in the stored (pre-LP-446)
extractions: credit.report_date (CR-13, a date) and contract.emd_amount (PC-5, a number). The rest are either
LP-446-added fields absent from the pre-LP-446 stored data (unmeasurable without re-extraction — no budget) or on
document types absent from all three files (appraisal/title/AUS/condo/master policy) — so they were NOT declared
(ADR-354: schema presence ≠ populated data). ⚠️ Neither of these two FINISHES its rule (CR-13 also needs a Priya
window + a date recipe; PC-5 also needs the emd_sourced AI match) — they are honest scaffolding, not unblocks.

These pin: each tag materialises verbatim from its document field; an absent field → an absent tag (fail closed);
and the LP-450 guard accepts both references.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.tag_materialization.declarations import ProductionMode, load_declarations
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio


def _doc(cid: str, dtype: str, **fields: str) -> DocumentEntry:
    return DocumentEntry(
        content_id=cid,
        document_type=dtype,
        belongs_to=None,
        fields={k: Field.present(v, source=FieldSource.EXTRACTED) for k, v in fields.items()},
    )


def _snapshot(*docs: DocumentEntry) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        documents=DocumentsSection.present(list(docs)),
        mismo=MismoSection.present({}),
        tags=TagsSection.present({}),
    )


async def _tag_on(cid: str, tag: str, *docs: DocumentEntry) -> object | None:
    mat = await materialize_tags(
        _snapshot(*docs), only_groups=frozenset()
    )  # parsed + derived, NO AI
    t = mat.tags.by_subject.get(cid, {}).get(tag)
    return t.value if t is not None else None


# --------------------------------------------------------------------------- #
# The tags materialise verbatim from their document fields
# --------------------------------------------------------------------------- #
async def test_credit_report_date_materialises_from_the_field() -> None:
    value = await _tag_on(
        "cr", "credit.report_date", _doc("cr", "credit_report", report_date="2026-07-17")
    )
    assert str(value) == "2026-07-17"


async def test_contract_emd_amount_materialises_from_the_field() -> None:
    value = await _tag_on(
        "pa",
        "contract.emd_amount",
        _doc("pa", "purchase_agreement", earnest_money_amount="5000.00"),
    )
    assert str(value) == "5000.00"


# --------------------------------------------------------------------------- #
# Fail closed — an absent field → an absent tag (never a fabricated default)
# --------------------------------------------------------------------------- #
async def test_absent_field_yields_an_absent_tag() -> None:
    # A credit_report with NO report_date (and a purchase_agreement with no earnest_money_amount) → both tags
    # absent — the honest state on LF-6T3N/XU26 for one, and any file lacking the field.
    assert (
        await _tag_on("cr", "credit.report_date", _doc("cr", "credit_report", report_provider="X"))
        is None
    )
    assert (
        await _tag_on(
            "pa", "contract.emd_amount", _doc("pa", "purchase_agreement", sales_price="1")
        )
        is None
    )


# --------------------------------------------------------------------------- #
# Declarations + the LP-450 guard
# --------------------------------------------------------------------------- #
def test_declarations_are_parsed_document_tags() -> None:
    decls = load_declarations()
    for tag, data in (
        ("credit.report_date", "report_date"),
        ("contract.emd_amount", "earnest_money_amount"),
    ):
        assert decls[tag].mode is ProductionMode.PARSED
        assert decls[tag].subject == "document"
        assert decls[tag].data == data


def test_lp450_guard_accepts_both_references() -> None:
    from tests.verification.tag_materialization.test_parsed_declaration_fields import (
        _document_field_universe,
        _resolves,
    )

    decls = load_declarations()
    universe = _document_field_universe()
    assert _resolves(decls["credit.report_date"], universe) is True
    assert _resolves(decls["contract.emd_amount"], universe) is True
