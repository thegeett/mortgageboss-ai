"""LP-616 — id.address_role: a residence a later document replaced stops being "current".

THE REAL CASE. Two staging loan files, same borrower, same MISMO, same eight documents, created
independently, agreeing on 45 of 46 governed rules. The one disagreement was ID-4, and it came from
the two 2023 W-2s carrying the borrower's old Massachusetts address:

    LF-3CVT   2023 W-2s typed `prior`     -> filtered out -> ID-4 satisfied
    LF-T9HD   2023 W-2s typed `residence` -> kept         -> ID-4 open (red)

LF-T9HD is the one FOLLOWING THE SPEC — `id.current_address_type`'s prompt says it reports what the
document INDICATES, that "prior" means the document EXPLICITLY marks the address former, and that
staleness "is checked DOWNSTREAM by comparing sources". A W-2 marks nothing. Nothing downstream
checked. This is that check.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult
from app.verification.rule_engine.consistency import evaluate_consistency_rule
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.derived import _id_address_role

pytestmark = pytest.mark.anyio

_B = uuid4()
_OTHER_B = uuid4()
_MA = "298 Sewall Street, Apt A, Boylston, MA 01505"
_NC = "1013 Whispering Creek Court, Knightdale, NC 27545"


def _tag(value: str, produced_by: TagProducedBy = TagProducedBy.AI) -> Tag:
    return Tag(
        value=value,
        confidence=0.9,
        reasoning="fixture",
        source_facts=("raw",),
        produced_by=produced_by,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _doc(
    cid: str,
    doc_type: str,
    *,
    date_field: tuple[str, str] | None = None,
    borrower: object = _B,
) -> DocumentEntry:
    fields = (
        {date_field[0]: Field.present(date_field[1], source=FieldSource.EXTRACTED)}
        if date_field
        else {}
    )
    return DocumentEntry(
        content_id=cid,
        document_type=doc_type,
        belongs_to=((BorrowerRef(borrower_id=borrower, name="Aditya"),) if borrower else None),
        fields=fields,
    )


def _snap(docs: list[tuple[DocumentEntry, str, str]]) -> Snapshot:
    """[(entry, address, current_address_type)] -> a snapshot with the id.* tags co-located."""
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 21, tzinfo=UTC),
        documents=DocumentsSection.present([d for d, _, _ in docs]),
        tags=TagsSection.present(
            {
                d.content_id: {
                    "id.address_normalized": _tag(addr),
                    "id.current_address_type": _tag(kind),
                }
                for d, addr, kind in docs
            }
        ),
    )


def _role(snap: Snapshot, cid: str) -> str:
    entry = next(e for e in snap.documents.entries if e.content_id == cid)
    value, _reason = _id_address_role(snap, cid, entry)
    return str(value)


# --------------------------------------------------------------------------- #
# The real file
# --------------------------------------------------------------------------- #
def test_the_2023_w2_address_is_superseded_by_the_2024_and_2025_documents() -> None:
    snap = _snap(
        [
            (_doc("w23a", "w2", date_field=("tax_year", "2023")), _MA, "residence"),
            (_doc("w23b", "w2", date_field=("tax_year", "2023")), _MA, "residence"),
            (_doc("w24", "w2", date_field=("tax_year", "2024")), _NC, "residence"),
            (_doc("stub", "pay_stub", date_field=("pay_date", "2025-04-04")), _NC, "residence"),
        ]
    )
    assert _role(snap, "w23a") == "superseded_residence"
    assert _role(snap, "w23b") == "superseded_residence"
    assert _role(snap, "w24") == "current_residence"
    assert _role(snap, "stub") == "current_residence"


async def test_id4_is_satisfied_once_the_moved_from_address_is_excluded() -> None:
    """End to end: the LF-T9HD shape that shipped a red finding now reads as one consistent address,
    and the fuzzy judge is never consulted — there is no residue left to judge."""
    calls: list[str] = []

    async def _reasoner(ctx: str) -> RuleJudgmentResult:
        calls.append(ctx)
        return RuleJudgmentResult(RuleJudgment("disagree", 0.9, "x"), 1, 1, "stub", False)

    snap = _snap(
        [
            (_doc("w23a", "w2", date_field=("tax_year", "2023")), _MA, "residence"),
            (_doc("w23b", "w2", date_field=("tax_year", "2023")), _MA, "residence"),
            (_doc("w24", "w2", date_field=("tax_year", "2024")), _NC, "residence"),
            (
                _doc("dl", "drivers_license", date_field=("issue_date", "2024-08-30")),
                _NC,
                "residence",
            ),
            (_doc("stub", "pay_stub", date_field=("pay_date", "2025-04-04")), _NC, "residence"),
        ]
    )
    # The role tag is what the gather_exclude reads, so materialize it onto each subject.
    tags = {
        cid: dict(snap.tags.by_subject[cid])
        | {"id.address_role": _tag(_role(snap, cid), TagProducedBy.DERIVED)}
        for cid in snap.tags.by_subject
    }
    snap = snap.model_copy(update={"tags": TagsSection.present(tags)})

    results = await evaluate_consistency_rule(load_rule_spec("ID-4"), snap, reasoner=_reasoner)

    assert [r.verdict for r in results] == [Verdict.SATISFIED]
    assert calls == []  # no AI call: nothing differs once the 2023 address is out


# --------------------------------------------------------------------------- #
# The guards — each one is a way this could hide a real discrepancy
# --------------------------------------------------------------------------- #
def test_one_later_document_agreeing_blocks_the_demotion() -> None:
    """EVERY later document must disagree. Otherwise a single mis-extracted address on the newest
    document would demote every correct older one and hide a real discrepancy."""
    snap = _snap(
        [
            (_doc("w23", "w2", date_field=("tax_year", "2023")), _NC, "residence"),
            (_doc("w24", "w2", date_field=("tax_year", "2024")), _NC, "residence"),  # agrees
            (_doc("typo", "pay_stub", date_field=("pay_date", "2025-04-04")), _MA, "residence"),
        ]
    )
    assert _role(snap, "w23") == "current_residence"


def test_same_year_documents_never_demote_each_other() -> None:
    """A mid-year move. Year granularity is deliberate (tax_year is a year, a pay date is a day), so
    a same-year disagreement stays with ID-4's judge rather than being decided here."""
    snap = _snap(
        [
            (_doc("a", "w2", date_field=("tax_year", "2024")), _MA, "residence"),
            (_doc("b", "pay_stub", date_field=("pay_date", "2024-11-01")), _NC, "residence"),
        ]
    )
    assert _role(snap, "a") == "current_residence"
    assert _role(snap, "b") == "current_residence"


def test_a_document_with_no_usable_date_is_never_demoted() -> None:
    snap = _snap(
        [
            (_doc("nodate", "w2"), _MA, "residence"),
            (_doc("stub", "pay_stub", date_field=("pay_date", "2025-04-04")), _NC, "residence"),
        ]
    )
    assert _role(snap, "nodate") == "current_residence"


def test_an_unlinked_document_is_never_demoted() -> None:
    """No borrower link means no way to tell WHOSE address it is — LF-WCHG had 16 of 16 documents
    unlinked, which silenced five ID rules entirely."""
    snap = _snap(
        [
            (_doc("w23", "w2", date_field=("tax_year", "2023"), borrower=None), _MA, "residence"),
            (_doc("stub", "pay_stub", date_field=("pay_date", "2025-04-04")), _NC, "residence"),
        ]
    )
    assert _role(snap, "w23") == "current_residence"


def test_another_borrowers_newer_document_does_not_demote_this_one() -> None:
    snap = _snap(
        [
            (_doc("mine", "w2", date_field=("tax_year", "2023")), _MA, "residence"),
            (
                _doc(
                    "theirs", "pay_stub", date_field=("pay_date", "2025-04-04"), borrower=_OTHER_B
                ),
                _NC,
                "residence",
            ),
        ]
    )
    assert _role(snap, "mine") == "current_residence"


def test_a_non_residence_address_is_typed_not_residence_and_needs_no_dates() -> None:
    snap = _snap(
        [(_doc("dl", "drivers_license", date_field=("issue_date", "2024-08-30")), _MA, "mailing")]
    )
    assert _role(snap, "dl") == "not_residence"


def test_a_genuinely_different_current_address_still_surfaces() -> None:
    """The demotion must not become a way to pass every file: two SAME-year residences that disagree
    are both current, so the discrepancy reaches the judge exactly as before."""
    snap = _snap(
        [
            (_doc("a", "pay_stub", date_field=("pay_date", "2025-04-04")), _MA, "residence"),
            (
                _doc("b", "bank_statement", date_field=("statement_period_end", "2025-03-25")),
                _NC,
                "residence",
            ),
        ]
    )
    assert _role(snap, "a") == "current_residence"
    assert _role(snap, "b") == "current_residence"


def test_expiration_and_birth_dates_are_not_read_as_the_address_date() -> None:
    """The date allowlist is deliberate: an expiry is in the future and a date of birth is not about
    the document. A licence carrying only those must not be demoted by them."""
    entry = DocumentEntry(
        content_id="dl",
        document_type="drivers_license",
        belongs_to=(BorrowerRef(borrower_id=_B, name="Aditya"),),
        fields={
            "expiration_date": Field.present("2030-02-28", source=FieldSource.EXTRACTED),
            "date_of_birth": Field.present("1990-08-23", source=FieldSource.EXTRACTED),
        },
    )
    snap = _snap(
        [
            (entry, _MA, "residence"),
            (_doc("stub", "pay_stub", date_field=("pay_date", "2025-04-04")), _NC, "residence"),
        ]
    )
    # No usable date on the licence -> not demoted (and certainly not by a 2030 expiry).
    assert _role(snap, "dl") == "current_residence"


async def test_the_declaration_actually_materializes_the_tag() -> None:
    """The producer above is only reachable if `tag_production.yaml` declares it and DERIVED runs
    after AI (LP-333). This goes through the real materializer rather than setting tags by hand."""
    from app.verification.tag_materialization.declarations import ProductionMode, load_declarations
    from app.verification.tag_materialization.producer import materialize_tags

    decl = load_declarations()["id.address_role"]
    assert decl.mode is ProductionMode.DERIVED and decl.subject == "document"

    snap = _snap(
        [
            (_doc("w23", "w2", date_field=("tax_year", "2023")), _MA, "residence"),
            (_doc("stub", "pay_stub", date_field=("pay_date", "2025-04-04")), _NC, "residence"),
        ]
    )
    # `only_groups=frozenset()` runs NO AI group, so the fixture's id.* tags stand and the derived
    # pass is what is under test (a keyless run would otherwise 401 them all to unknown).
    out = await materialize_tags(
        snap, only_subjects=frozenset({"document"}), only_groups=frozenset()
    )
    assert str(out.tags.by_subject["w23"]["id.address_role"].value) == "superseded_residence"
    assert str(out.tags.by_subject["stub"]["id.address_role"].value) == "current_residence"
