"""LP-452 (step D.1) / LP-509-B1 — property.type: the loan's subject-property type, from MISMO.

One tag declaration gating five rules (CO-1/CO-3/CO-5/IH-7/PR-3), which each must know condo vs SFR vs PUD
before they can scope. Absent source → the tag is ABSENT (fail closed), never a default.

LP-509-B1 CHANGED TWO THINGS, both because the tag never resolved on a real file. It was `parsed`, a verbatim
passthrough of the MISMO `property.type` fact, and that fact is null on every stored file — including the real
LF-WCHG export, whose PropertyType element is empty. So all five rules abstained, and four of them produced a
live finding asking a processor to determine a property type the file already described.

  1. It is now `derived`. The recipe still PREFERS a stated type; it derives one from the export's project
     indicators (PropertyInProjectIndicator / PUDIndicator / FinancedUnitCount / ConstructionMethodType) only
     when none is stated. `in_project` is the decisive condo signal; `attachment_type` deliberately is not.
  2. A stated value is MAPPED rather than passed through. The DB's PropertyType enum and this tag's declared
     vocabulary are different value spaces, so the passthrough emitted values outside the tag's own enum.

These pin: a stated type maps into the vocabulary (and an unmappable one abstains); an absent source yields an
absent tag; each derivation branch, including every one that must abstain rather than default.
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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("condo", "condo"),
        ("single_family", "sfr"),
        ("multi_family", "2-4unit"),
        ("manufactured", "manufactured"),
        # LP-509-B1: "townhouse" and "other" do not correspond to ONE value in this tag's
        # vocabulary and now ABSTAIN. A townhouse may be a condo, a PUD or fee-simple depending on
        # how the project is organised, and that distinction is exactly what the condo rules turn
        # on — mapping it to any one of them would be a guess presented as a fact.
        ("townhouse", None),
        ("other", None),
    ],
)
async def test_a_stated_type_maps_into_this_tags_vocabulary(raw: str, expected: str | None) -> None:
    """LP-509-B1 — the stated type is MAPPED, where it used to pass through verbatim.

    The passthrough was a value-space bug that had never fired: `properties.property_type` holds the
    DB's PropertyType enum (single_family / townhouse / multi_family / …) while this tag declares
    sfr / condo / pud / 2-4unit / manufactured / coop / unknown. A stated "single_family" was
    emitted as "single_family" — a value outside the tag's own declared enum. It went unnoticed
    because the column is null on every stored file.
    """
    value = await _property_type({"property.type": Field.present(raw, source=FieldSource.PARSED)})
    assert value == expected


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


def test_declaration_is_a_derived_loan_tag() -> None:
    """LP-509-B1 — parsed -> derived. The recipe still PREFERS the stated type; it derives only
    when the file states none, so the descriptive contract is intact."""
    decl = load_declarations()["property.type"]
    assert decl.mode is ProductionMode.DERIVED
    assert decl.subject == "loan"
    assert decl.data == "property_type"  # the recipe name in derived._RECIPES


# --------------------------------------------------------------------------- #
# LP-509-B1 — derivation from the MISMO project indicators, when no type is stated.
#
# LF-WCHG's export states an EMPTY PropertyType while carrying PropertyInProjectIndicator=false,
# PUDIndicator=false, FinancedUnitCount=1 and ConstructionMethodType=SiteBuilt. With the tag absent,
# CO-1, CO-3, CO-4 and IH-7 each reported "the property type has not been determined" — four
# findings asking a processor to supply what the file already contained.
# --------------------------------------------------------------------------- #
def _indicators(**facts: str) -> dict[str, Field]:
    return {
        key.replace("__", "."): Field.present(v, source=FieldSource.PARSED)
        for key, v in facts.items()
    }


async def test_the_lf_wchg_shape_derives_sfr() -> None:
    """The exact indicator set on the real file."""
    value = await _property_type(
        _indicators(
            property__in_project="false",
            property__is_pud="false",
            property__financed_unit_count="1",
            property__construction_method="SiteBuilt",
            property__attachment_type="Detached",
        )
    )
    assert value == "sfr"


async def test_in_project_false_is_what_rules_out_a_condo_not_detached() -> None:
    """⚠️ The distinction this derivation turns on.

    Fannie Mae recognises DETACHED CONDOMINIUMS, so "AttachmentType: Detached" is NOT evidence that
    a property is not a condo — reading it that way would clear the condo rules on exactly the files
    they exist for. `PropertyInProjectIndicator` is the decisive signal: a condominium is by
    definition a property in a project. Detached-with-no-project-indicator must therefore ABSTAIN.
    """
    assert (
        await _property_type(
            _indicators(property__attachment_type="Detached", property__financed_unit_count="1")
        )
        is None
    )


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        # In a project: a condo, a co-op and a project PUD all are — cannot be narrowed. Abstain.
        ({"property__in_project": "true"}, None),
        # Not in a project and a PUD → pud.
        ({"property__in_project": "false", "property__is_pud": "true"}, "pud"),
        # Not in a project, not a PUD, 3 financed units → 2-4unit.
        (
            {
                "property__in_project": "false",
                "property__is_pud": "false",
                "property__financed_unit_count": "3",
            },
            "2-4unit",
        ),
        # A manufactured home is decided by construction method before any project question.
        ({"property__construction_method": "Manufactured"}, "manufactured"),
        # Each missing link abstains rather than defaulting.
        ({"property__in_project": "false"}, None),  # no PUD indicator
        (
            {"property__in_project": "false", "property__is_pud": "false"},
            None,
        ),  # no unit count
    ],
)
async def test_derivation_branches(facts: dict[str, str], expected: str | None) -> None:
    assert await _property_type(_indicators(**facts)) == expected


async def test_an_unparseable_indicator_abstains_and_is_never_read_as_false() -> None:
    """Tri-state: absent or unreadable is NOT false. Reading it as false would assert "not in a
    project" — and so "not a condo" — about a file that never said so."""
    assert await _property_type(_indicators(property__in_project="maybe")) is None
