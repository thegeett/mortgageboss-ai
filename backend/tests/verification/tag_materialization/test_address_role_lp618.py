"""LP-618 — the address-role demotion, and the three ways it removed evidence it should have kept.

The demotion is ONE-DIRECTIONAL: it takes a document out of ID-4's compare set and can never put one
in. So every defect here has the same shape — evidence removed — and the same consequence: a check
that would have been SATISFIED, or would have fired a real discrepancy, returns couldnt_check instead.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.derived import _addresses_agree, _id_address_role

_A = str(uuid4())
_B = str(uuid4())


def _tag(value: str) -> Tag:
    return Tag(
        value=value,
        confidence=0.9,
        reasoning="fixture",
        source_facts=("raw",),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _doc(cid: str, *, date_field: str, date_value: str, borrowers: list[str]) -> DocumentEntry:
    return DocumentEntry(
        content_id=cid,
        document_type="w2" if date_field == "tax_year" else "uniform_residential_loan_application",
        fields={date_field: Field.present(date_value, source=FieldSource.EXTRACTED)},
        belongs_to=tuple(BorrowerRef(borrower_id=b, name=f"Borrower {b[:4]}") for b in borrowers),
    )


def _snapshot(docs: list[DocumentEntry], addresses: dict[str, str]) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 21, tzinfo=UTC),
        documents=DocumentsSection.present(docs),
        tags=TagsSection.present(
            {
                cid: {
                    "id.current_address_type": _tag("residence"),
                    "id.address_normalized": _tag(addr),
                }
                for cid, addr in addresses.items()
            }
        ),
    )


# --------------------------------------------------------------------------------------------- #
# The compare must be at least as tolerant as the rule it feeds
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("298 Sewall Street Apt A, Boylston MA 01505", "298 Sewall St #A, Boylston MA 01505-1234"),
        ("12 North Main Street", "12 N Main St"),
        ("100 Elm Rd Unit 5", "100 Elm Road Apartment 5"),
    ],
)
def test_benign_address_variance_is_agreement(left: str, right: str) -> None:
    """ID-4 is `compare_mode: fuzzy` with a judge whose job is calling exactly this benign.

    An EXACT compare here demoted a document the rule would have judged consistent — and because the
    demotion only ever removes, a two-document borrower ID-4 had judged SATISFIED became "only 1
    document(s) in the file state the current address".
    """
    assert _addresses_agree(left, right)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("298 Sewall St, Boylston MA 01505", "45 Oak Ave, Worcester MA 01605"),
        ("298 Sewall St Apt A", "298 Sewall St Apt B"),
        ("100 Elm St", "100 Elm St Apt 5"),
    ],
)
def test_a_real_move_is_still_a_disagreement(left: str, right: str) -> None:
    """Tolerance must not swallow the case the tag exists to detect."""
    assert not _addresses_agree(left, right)


def test_a_newer_document_stating_the_same_place_differently_does_not_supersede() -> None:
    old = _doc("w2", date_field="tax_year", date_value="2023", borrowers=[_A])
    new = _doc(
        "urla", date_field="application_signed_date", date_value="2026-01-15", borrowers=[_A]
    )
    snap = _snapshot(
        [old, new],
        {
            "w2": "298 Sewall Street Apt A, Boylston MA 01505",
            "urla": "298 Sewall St #A, Boylston MA 01505-1234",
        },
    )

    value, reason = _id_address_role(snap, "w2", old)

    assert value == "current_residence", reason


# --------------------------------------------------------------------------------------------- #
# A co-borrower's document must not demote a joint one
# --------------------------------------------------------------------------------------------- #
def test_a_newer_document_for_one_borrower_does_not_demote_a_joint_document() -> None:
    """The role is ONE value per DOCUMENT, applied to every borrower it belongs to.

    A newer paystub belonging to B alone demoted the joint 1003 for A too, dropping A's compare set
    from two sources to one — a co-borrower's document silently suppressing A's finding, which is the
    failure this design calls unreachable.
    """
    joint = _doc("joint", date_field="tax_year", date_value="2023", borrowers=[_A, _B])
    b_only = _doc(
        "bdoc", date_field="application_signed_date", date_value="2026-01-15", borrowers=[_B]
    )
    snap = _snapshot([joint, b_only], {"joint": "1 First St", "bdoc": "2 Second Ave"})

    value, reason = _id_address_role(snap, "joint", joint)

    assert value == "current_residence", reason


def test_a_newer_document_covering_every_borrower_still_supersedes() -> None:
    """The narrowing must not cost the case the feature exists for."""
    joint = _doc("joint", date_field="tax_year", date_value="2023", borrowers=[_A, _B])
    newer = _doc(
        "urla", date_field="application_signed_date", date_value="2026-01-15", borrowers=[_A, _B]
    )
    snap = _snapshot([joint, newer], {"joint": "1 First St", "urla": "2 Second Ave"})

    value, _reason = _id_address_role(snap, "joint", joint)

    assert value == "superseded_residence"


# --------------------------------------------------------------------------------------------- #
# The 1003 — the shape the ticket was written for
# --------------------------------------------------------------------------------------------- #
def test_the_1003_can_supersede_an_old_w2() -> None:
    """ "2023 W-2 (old address) + 1003 (current address)" is the file shape LP-616 names.

    Neither URLA date field was in the as-of allowlist, so the W-2 found no newer dated residence,
    stayed current, and ID-4 kept firing the false discrepancy the ticket exists to remove. The
    feature only worked when a dated paystub, W-2 or licence happened to also be present.
    """
    w2 = _doc("w2", date_field="tax_year", date_value="2023", borrowers=[_A])
    urla = _doc(
        "urla", date_field="application_signed_date", date_value="2026-01-15", borrowers=[_A]
    )
    snap = _snapshot(
        [w2, urla], {"w2": "1 Old St, Boylston MA 01505", "urla": "2 New Ave, Worcester MA 01605"}
    )

    value, reason = _id_address_role(snap, "w2", w2)

    assert value == "superseded_residence", reason


def test_a_future_dated_document_cannot_supersede_anything() -> None:
    """A hazard binder is routinely effective AT CLOSING, and those extractors state the SUBJECT
    PROPERTY address — so a future-dated document treated as newest would demote every genuinely
    current residence at once."""
    now = _doc(
        "urla", date_field="application_signed_date", date_value="2026-01-15", borrowers=[_A]
    )
    future = _doc(
        "later", date_field="application_signed_date", date_value="2027-06-01", borrowers=[_A]
    )
    snap = _snapshot([now, future], {"urla": "1 First St", "later": "2 Second Ave"})

    value, reason = _id_address_role(snap, "urla", now)

    assert value == "current_residence", reason
