"""LP-452 (step D.1) — the property.type parsed tag: the loan's subject-property type, promoted from MISMO.

One tag declaration gating five rules (CO-1/CO-3/CO-5/IH-7/PR-3), which each must know condo vs SFR vs PUD
before they can scope. DESCRIPTIVE: the RAW MISMO value passes through verbatim (produce_parsed_tag — never
normalised into a tidy vocabulary; whether a value "is a condo" is a rule's branch, not a re-labelling here).
Absent MISMO property.type → the tag is ABSENT (fail closed), never a default.

These pin: the tag materialises from MISMO property.type verbatim (a raw value is NOT re-typed); an absent
source yields an absent tag (never a fabricated default); the declaration is parsed/loan reading the MISMO key;
and the LP-450 guard accepts the new reference.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.tag_materialization.declarations import ProductionMode, load_declarations
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio

_LOAN = "loan"


def _snapshot(mismo: dict[str, Field]) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        documents=DocumentsSection.present([]),
        mismo=MismoSection.present(mismo),
        tags=TagsSection.present({}),
    )


async def _property_type(mismo: dict[str, Field]) -> object | None:
    mat = await materialize_tags(
        _snapshot(mismo), only_groups=frozenset()
    )  # parsed + derived, NO AI
    tag = mat.tags.by_subject.get(_LOAN, {}).get("property.type")
    return tag.value if tag is not None else None


@pytest.mark.parametrize("raw", ["condo", "single_family", "multi_family", "manufactured", "other"])
async def test_tag_materialises_from_mismo_verbatim(raw: str) -> None:
    # The RAW MISMO value passes through unchanged — NOT normalised into a tidy vocabulary (e.g.
    # single_family is NOT re-labelled "sfr"; multi_family is NOT "2-4unit"). Tags describe; rules judge.
    value = await _property_type({"property.type": Field.present(raw, source=FieldSource.PARSED)})
    assert value == raw


async def test_absent_source_yields_an_absent_tag__fail_closed() -> None:
    # No MISMO property.type on the file → the tag is ABSENT, never a fabricated default (e.g. "unknown").
    # This is the current state of every stored fixture (MISMO property_type is null on LF-6T3N/96SV/XU26).
    assert await _property_type({}) is None
    # a present-but-unrelated MISMO fact must not conjure a property type either
    assert (
        await _property_type(
            {"loan.program": Field.present("Conventional", source=FieldSource.PARSED)}
        )
        is None
    )


def test_declaration_is_a_parsed_loan_tag_reading_the_mismo_key() -> None:
    decl = load_declarations()["property.type"]
    assert decl.mode is ProductionMode.PARSED
    assert decl.subject == "loan"
    assert (
        decl.data == "property.type"
    )  # the MISMO fact key (mismo_section put("property.type", ...))


def test_lp450_guard_accepts_the_new_reference() -> None:
    # The LP-450 MISMO guard must accept property.type (it is a real MISMO loan key) — else a typo'd tag would
    # resolve silently to absent. Importing the guard's resolver directly (it is a pure function).
    from tests.verification.tag_materialization.test_parsed_declaration_fields import (
        _document_field_universe,
        _resolves,
    )

    decl = load_declarations()["property.type"]
    assert _resolves(decl, _document_field_universe()) is True
