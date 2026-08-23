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
def test_two_documents_sharing_an_address_always_share_a_verdict() -> None:
    """bug-001 — THIS TEST PREVIOUSLY ASSERTED THE OPPOSITE, and the behaviour it pinned was wrong.

    It required EVERY later document to disagree before demoting, meaning to stop one mis-extracted
    recent address demoting correct older ones. It asserted only `w23`, and that hid the split: under
    that rule `w24` (the LATEST document stating NC) was demoted anyway, because nothing after it
    agreed — so the guard only ever saved the EARLIEST copy while losing the newest one.

    On a real file that produced two W-2s stating 2369 Tangerine Lane with opposite labels, one
    `superseded_residence` and one `current_residence`, and the surviving one went on feeding ID-4 a
    discrepancy that was really a house move.

    The question is now asked once per ADDRESS, so a shared address cannot receive two answers.

    THE RESIDUAL RISK IS REAL AND UNCHANGED: no date-based rule can tell a typo on the newest
    document from a genuine move, and this one reads it as a move. What changed is that it now does
    so CONSISTENTLY, instead of splitting one address across two verdicts."""
    snap = _snap(
        [
            (_doc("w23", "w2", date_field=("tax_year", "2023")), _NC, "residence"),
            (_doc("w24", "w2", date_field=("tax_year", "2024")), _NC, "residence"),
            (_doc("newer", "pay_stub", date_field=("pay_date", "2025-04-04")), _MA, "residence"),
        ]
    )
    assert _role(snap, "w23") == _role(snap, "w24") == "superseded_residence"
    assert _role(snap, "newer") == "current_residence"


def test_the_newest_document_stating_an_address_is_what_dates_it() -> None:
    """The mechanism, stated directly: an address is as recent as the LAST document to state it, so a
    later document agreeing keeps the whole group current rather than only itself."""
    snap = _snap(
        [
            (_doc("old", "w2", date_field=("tax_year", "2023")), _NC, "residence"),
            (_doc("recent", "pay_stub", date_field=("pay_date", "2026-04-04")), _NC, "residence"),
            (
                _doc("middle", "bank_statement", date_field=("statement_period_end", "2024-06-30")),
                _MA,
                "residence",
            ),
        ]
    )
    # NC is last stated in 2026, after the 2024 document that says MA → nothing supersedes it.
    assert _role(snap, "old") == "current_residence"
    assert _role(snap, "recent") == "current_residence"
    # MA is last stated in 2024, and 2026 says NC → superseded.
    assert _role(snap, "middle") == "superseded_residence"


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


def test_the_real_file_two_w2s_one_move_and_an_investment_property() -> None:
    """bug-001, reproduced from LF-ABRS.

    The borrower lived at Tangerine Lane (both W-2s), moved to Cumming in Jul 2025 (the 2026 pay
    stub and bank statements), and is refinancing a property in Naples they do not live in. ID-4 saw
    three "current" addresses and reported a discrepancy; two of the three were not current at all.

    This pins the half that was mine: BOTH W-2s now read as the old address, together."""
    tangerine = "2369 Tangerine Lane, Naples, FL 34120"
    cumming = "4070 Preserve Crossing Lane, Cumming, GA 30040"
    snap = _snap(
        [
            (_doc("w24", "w2", date_field=("tax_year", "2024")), tangerine, "residence"),
            (_doc("w25", "w2", date_field=("tax_year", "2025")), tangerine, "residence"),
            (_doc("stub", "pay_stub", date_field=("pay_date", "2026-08-02")), cumming, "residence"),
            (
                _doc("bank", "bank_statement", date_field=("statement_period_end", "2026-07-15")),
                cumming,
                "residence",
            ),
        ]
    )

    assert _role(snap, "w24") == "superseded_residence"
    assert _role(snap, "w25") == "superseded_residence"
    assert _role(snap, "stub") == "current_residence"
    assert _role(snap, "bank") == "current_residence"


# --------------------------------------------------------------------------- #
# bug-001 — the collateral is not a home.
#
# A mortgage statement and an insurance binder for the subject property carry the PROPERTY's address:
# that is who the servicer bills and what the policy covers. On an owner-occupied loan it is also the
# borrower's home. On an INVESTMENT property it is not a home at all — and on LF-ABRS those two
# documents supplied two of ID-4's three "current residence" addresses while the borrower lived in
# another state.
# --------------------------------------------------------------------------- #
_SUBJECT = "220 39th Avenue Northwest, Naples, FL 34120-3361"
_HOME = "4070 Preserve Crossing Lane, Cumming, GA 30040"


def _with_property(snap: Snapshot, occupancy: str) -> Snapshot:
    from app.verification.snapshot.model import MismoSection

    return snap.model_copy(
        update={
            "mismo": MismoSection.present(
                {
                    "property.occupancy": Field.present(occupancy, source=FieldSource.PARSED),
                    "property.address_line": Field.present(
                        "220 39th Avenue Northwest", source=FieldSource.PARSED
                    ),
                    "property.city": Field.present("Naples", source=FieldSource.PARSED),
                    "property.state": Field.present("FL", source=FieldSource.PARSED),
                    "property.postal_code": Field.present("34120-3361", source=FieldSource.PARSED),
                }
            )
        }
    )


def test_an_investment_propertys_address_is_not_the_borrowers_residence() -> None:
    snap = _with_property(
        _snap(
            [
                (
                    _doc("stmt", "mortgage_statement", date_field=("issue_date", "2026-07-01")),
                    _SUBJECT,
                    "residence",
                ),
                (
                    _doc("stub", "pay_stub", date_field=("pay_date", "2026-08-02")),
                    _HOME,
                    "residence",
                ),
            ]
        ),
        "investment",
    )

    assert _role(snap, "stmt") == "not_residence"
    assert _role(snap, "stub") == "current_residence"


def test_on_an_owner_occupied_loan_the_same_address_IS_the_residence() -> None:
    """The whole point is occupancy, not the document type. A servicer's statement for a home the
    borrower lives in states their address, and excluding it would shrink the comparison for no
    reason."""
    snap = _with_property(
        _snap(
            [
                (
                    _doc("stmt", "mortgage_statement", date_field=("issue_date", "2026-07-01")),
                    _SUBJECT,
                    "residence",
                ),
            ]
        ),
        "primary_residence",
    )

    assert _role(snap, "stmt") == "current_residence"


def test_a_second_home_is_still_a_home() -> None:
    """`second` is a property the borrower does live in, part of the year — only `investment` says
    they do not."""
    snap = _with_property(
        _snap(
            [
                (
                    _doc("stmt", "mortgage_statement", date_field=("issue_date", "2026-07-01")),
                    _SUBJECT,
                    "residence",
                ),
            ]
        ),
        "second_home",
    )

    assert _role(snap, "stmt") == "current_residence"


def test_an_unreadable_occupancy_never_excludes_an_address() -> None:
    """An occupancy we cannot read is not evidence the borrower is absent. Fail-open: a missing or
    unmapped occupancy leaves the address in the comparison."""
    snap = _with_property(
        _snap(
            [
                (
                    _doc("stmt", "mortgage_statement", date_field=("issue_date", "2026-07-01")),
                    _SUBJECT,
                    "residence",
                ),
            ]
        ),
        "something_the_map_does_not_know",
    )

    assert _role(snap, "stmt") == "current_residence"


def test_only_the_subject_propertys_own_address_is_excluded() -> None:
    """A different address on an investment file is still the borrower's home — the exclusion is
    about WHICH address, not about the loan being an investment."""
    snap = _with_property(
        _snap(
            [
                (
                    _doc("stub", "pay_stub", date_field=("pay_date", "2026-08-02")),
                    _HOME,
                    "residence",
                ),
            ]
        ),
        "investment",
    )

    assert _role(snap, "stub") == "current_residence"


def test_an_undated_document_naming_the_investment_property_is_still_excluded() -> None:
    """bug-001 — the placement bug, pinned.

    The check ran AFTER the date guard, and a mortgage statement carries no field in
    `_ADDRESS_AS_OF_FIELDS` — so it returned `current_residence` there and never reached the
    investment check, while the insurance binder (which has `document_issue_date`) was correctly
    excluded. Two documents naming the same investment property, one excluded and one not.

    An investment property was never the borrower's residence. That is not a question about WHEN."""
    snap = _with_property(
        _snap(
            [
                # No date field at all — exactly the mortgage statement's shape.
                (_doc("stmt", "mortgage_statement"), _SUBJECT, "residence"),
                (
                    _doc("stub", "pay_stub", date_field=("pay_date", "2026-08-02")),
                    _HOME,
                    "residence",
                ),
            ]
        ),
        "investment",
    )

    assert _role(snap, "stmt") == "not_residence"


def test_a_zip_plus_four_does_not_hide_the_collateral() -> None:
    """The real pair: the MISMO carries 34120-3361 (hyphenated by bug-001's own migration) and the
    mortgage statement prints the 5-digit form. Same property."""
    snap = _with_property(
        _snap(
            [
                (
                    _doc("stmt", "mortgage_statement"),
                    "220 39th Avenue Northwest, Naples, FL 34120",
                    "residence",
                )
            ]
        ),
        "investment",
    )

    assert _role(snap, "stmt") == "not_residence"


def test_an_unlinked_document_naming_the_investment_property_is_still_excluded() -> None:
    """The other guard it used to sit behind. Whose document it is does not change whether the
    address is a home."""
    entry = _doc("stmt", "mortgage_statement", borrower=None)
    snap = _with_property(_snap([(entry, _SUBJECT, "residence")]), "investment")

    assert _role(snap, "stmt") == "not_residence"
