"""housing.insurance_monthly — wired (LP-374): the DTI's last vocabulary orphan.

The tag was declared in `fact_tags.csv` (producer=AI) but nothing produced it → LP-373's guard exempted it.
This wires a DERIVED loan recipe reading the homeowners-insurance binder's extracted `annual_premium` ÷ 12
— the SAME field the DTI reads directly from the extraction (`services/dti.py`), so the tag AGREES with the
DTI's insurance line. It does NOT unblock the DTI (which never read this tag): the DTI already computes on a
file with a binder. This closes the orphan and serves the tag's own (inert) consumers DT-1/DT-5/IH-1.

FAIL-CLOSED (absent≠0): no binder / no premium / conflicting binders / non-positive premium → `unknown` WITH
A REASON, NEVER 0 (a 0 premium makes the DTI confidently too-low — the false-green the DTI gate prevents).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    Snapshot,
    TagsSection,
)
from app.verification.tag_materialization.declarations import ProductionMode, load_declarations
from app.verification.tag_materialization.derived import _UNKNOWN, _housing_insurance_monthly
from app.verification.tag_materialization.producer import materialize_tags
from app.verification.tag_materialization.subjects import LOAN_SUBJECT

pytestmark = pytest.mark.anyio


def _binder(premium: str | None, *, content_id: str = "ins1") -> DocumentEntry:
    """A homeowners_insurance document carrying (or omitting) an extracted annual_premium field. The
    snapshot stores field values as JSON scalars (strings) — build_document_fields stringifies the
    extracted Decimal — so the fixture mirrors that; the recipe coerces via Decimal(str(...))."""
    fields = (
        {"annual_premium": Field.present(premium, source=FieldSource.EXTRACTED)}
        if premium is not None
        else {}
    )
    return DocumentEntry(content_id=content_id, document_type="homeowners_insurance", fields=fields)


def _snapshot(docs: list[DocumentEntry]) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 17, tzinfo=UTC),
        documents=DocumentsSection.present(docs),
        tags=TagsSection.present({}),
    )


# --------------------------------------------------------------------------- #
# THE STRUCTURAL FIX — a binder materializes the tag as annual ÷ 12 (the right number)
# --------------------------------------------------------------------------- #
def test_binder_materializes_annual_over_twelve() -> None:
    value, reason = _housing_insurance_monthly(_snapshot([_binder("1200")]), "loan", None)
    assert value == "100"  # 1200 / 12
    assert "1200" in reason and "12" in reason


def test_non_whole_division_keeps_full_precision() -> None:
    value, _ = _housing_insurance_monthly(_snapshot([_binder("1300")]), "loan", None)
    assert Decimal(str(value)) == Decimal("1300") / Decimal(
        "12"
    )  # 108.333… — never rounded to 0/108


def test_declaration_is_derived_loan() -> None:
    decl = load_declarations()["housing.insurance_monthly"]
    assert decl.mode is ProductionMode.DERIVED and decl.subject == "loan"
    assert decl.data == "housing_insurance_monthly"


async def test_end_to_end_materialization_keys_the_loan_subject() -> None:
    # The DECLARATION wires it: materialize_tags produces housing.insurance_monthly under the loan subject.
    snap = await materialize_tags(_snapshot([_binder("1440")]), only_subjects=frozenset({"loan"}))
    tag = snap.tags.by_subject[LOAN_SUBJECT]["housing.insurance_monthly"]
    assert str(tag.value) == "120"  # 1440 / 12


# --------------------------------------------------------------------------- #
# FAIL-CLOSED — never 0; every degenerate case abstains WITH A REASON
# --------------------------------------------------------------------------- #
def test_no_binder_is_unknown_not_zero() -> None:
    value, reason = _housing_insurance_monthly(_snapshot([]), "loan", None)
    assert value == _UNKNOWN and value != "0"
    assert "no homeowners insurance binder" in reason


def test_binder_present_but_no_premium_is_unknown_not_zero() -> None:
    value, reason = _housing_insurance_monthly(_snapshot([_binder(None)]), "loan", None)
    assert value == _UNKNOWN and "no annual premium" in reason


def test_non_positive_premium_is_unknown_not_zero() -> None:
    # A binder extracted as $0 would make the DTI confidently too-low — abstain, do not emit 0.
    value, reason = _housing_insurance_monthly(_snapshot([_binder("0")]), "loan", None)
    assert value == _UNKNOWN and "non-positive" in reason


def test_conflicting_binders_abstain_and_name_the_ambiguity() -> None:
    # D2: two binders with different premiums → cannot tell which is current → unknown, never a guess.
    snap = _snapshot([_binder("1200", content_id="a"), _binder("1800", content_id="b")])
    value, reason = _housing_insurance_monthly(snap, "loan", None)
    assert value == _UNKNOWN
    assert "conflicting" in reason and "1200" in reason and "1800" in reason


def test_identical_duplicate_binders_do_not_conflict() -> None:
    # A declarations page + a renewal stating the SAME premium is not ambiguous → the one distinct value.
    snap = _snapshot([_binder("1200", content_id="a"), _binder("1200", content_id="b")])
    value, _ = _housing_insurance_monthly(snap, "loan", None)
    assert value == "100"


def test_never_emits_zero_across_all_degenerate_inputs() -> None:
    # The explicit NEVER-0 guarantee (the false-green the gate exists to prevent).
    for docs in ([], [_binder(None)], [_binder("0")], [_binder("-5")]):
        value, _ = _housing_insurance_monthly(_snapshot(docs), "loan", None)
        assert value == _UNKNOWN and value != "0"
