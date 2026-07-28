"""LP-418 — the PRODUCER BATCH: build the small producers that unblock written-but-inert rules. PRODUCERS AND
FIXTURES ONLY — no rules are written or activated here.

Three producers ship:
  #1 income.is_self_employed — a DETERMINISTIC per-borrower promotion of the measured income.type (an AI tag),
     the borrower-level self-employment signal IN-12's activation bar said was missing. NO new AI.
  #2 txn.is_nsf_or_overdraft — an AI (transaction-subject) producer; AS-7's rule HELD on calibration and only
     lacked this producer.
  #3 occupancy.rental_support — an AI (loan-subject) producer; IN-14 ships ratify and only lacked this producer.

And two standalone LABELING fixtures (#5/#6) that supply the positive classes LP-395 measured as too thin:
  #5 voe_offer — six VOE + six offer-letter documents (income_docs had offer_letter_present n=0).
  #6 other_income — six borrowers each declaring an other-income type (income_stability had continuance_3yr n=1).

These tests PIN the producers materialize (reported, not predicted), the fixtures supply ≥6 labelable rows per
target tag, and NO rule activation moved (this is a producer/fixture batch, not a rule batch).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.verification.eval.fire_path_scenarios import (
    build_other_income_continuance_snapshot,
    build_voe_offer_labeling_snapshot,
)
from app.verification.eval.income_scenarios import build_income_calibration_snapshot
from app.verification.eval.stubs import stub_materialization_reasoners
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.declarations import load_ai_groups, load_declarations
from app.verification.tag_materialization.derived import produce_derived_tags
from app.verification.tag_materialization.producer import materialize_tags
from tests.expected_active import EXPECTED_ACTIVE_RULE_COUNT

pytestmark = pytest.mark.anyio

_B1 = UUID("93000000-0000-4000-8000-000000000001")
_B2 = UUID("93000000-0000-4000-8000-000000000002")


def _f(value: str) -> Field:
    return Field.present(value, source=FieldSource.EXTRACTED)


def _income_type_tag(value: str) -> Tag:
    return Tag(
        value=value,
        confidence=0.9,
        reasoning="stub income type",
        source_facts=("d",),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _two_borrower_snapshot(
    doc_types: dict[str, tuple[UUID, str | None]],
) -> Snapshot:
    """A snapshot with one document per (content_id) attributed to a borrower, each optionally carrying an
    income.type tag. ``doc_types`` maps content_id -> (borrower_id, income_type_value | None)."""
    docs = [
        DocumentEntry(
            content_id=cid,
            document_type="pay_stub",
            belongs_to=(BorrowerRef(borrower_id=bid, name=f"B{cid}"),),
            fields={},
        )
        for cid, (bid, _type) in doc_types.items()
    ]
    tags: dict[str, dict[str, Tag]] = {
        cid: {"income.type": _income_type_tag(itype)}
        for cid, (_bid, itype) in doc_types.items()
        if itype is not None
    }
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
        documents=DocumentsSection.present(docs),
        mismo=MismoSection.present(
            {
                "borrower.1.borrower_id": _f(str(_B1)),
                "borrower.2.borrower_id": _f(str(_B2)),
            }
        ),
        tags=TagsSection.present(tags),
    )


# ======================================================================= #
# #1 — income.is_self_employed (deterministic, per-borrower)
# ======================================================================= #
def test_self_employed_recipe_reports_yes_no_unknown() -> None:
    # The reported branches (not predicted): a borrower whose income document states self_employment -> "yes";
    # a borrower with a readable NON-self-employment type -> "no" (lets IN-12 reach not_applicable, an enum can);
    # a borrower with NO readable income type -> "unknown" (fail-closed, never a fabricated "no").
    decl = load_declarations()["income.is_self_employed"]
    snap = _two_borrower_snapshot(
        {
            "d-se": (_B1, "self_employment"),  # borrower 1 -> yes
            "d-w2": (_B2, "base"),  # borrower 2 -> no (type present, not self-employment)
        }
    )
    out = produce_derived_tags(decl, snap)
    by_borrower = {sid: tags["income.is_self_employed"].value for sid, tags in out.items()}
    assert by_borrower[str(_B1)] == "yes"
    assert by_borrower[str(_B2)] == "no"

    # A borrower with no readable income type -> unknown.
    snap_unknown = _two_borrower_snapshot({"d-none": (_B1, None), "d2-none": (_B2, None)})
    out_unknown = produce_derived_tags(decl, snap_unknown)
    assert {v["income.is_self_employed"].value for v in out_unknown.values()} == {"unknown"}


async def test_self_employed_wires_per_borrower_through_the_pipeline() -> None:
    # The recipe runs LAST (derived-last, LP-333), so it sees the AI-produced income.type. On the income
    # calibration fixture it materializes ONE row per enumerated borrower (13). Under the keyless stub the
    # AI income.type is honest-unknown, so every promotion reads "unknown" — an HONEST reflection of the stub
    # (the yes/no branches are exercised by the recipe test above against real income.type values), and proof
    # the promotion is wired per-borrower end to end.
    mat = await materialize_tags(
        build_income_calibration_snapshot(), ai_reasoners=stub_materialization_reasoners()
    )
    rows = [
        str(sub["income.is_self_employed"].value)
        for sub in mat.tags.by_subject.values()
        if "income.is_self_employed" in sub
    ]
    assert len(rows) == 13  # one per enumerated borrower
    assert set(rows) == {"unknown"}  # the stub does not assign a real income.type


# ======================================================================= #
# #5 — the VOE + offer-letter labeling fixture
# ======================================================================= #
async def test_voe_offer_fixture_supplies_a_positive_class() -> None:
    # income_docs (subject:document, applies_to:None) judges EVERY document, so voe_present / offer_letter_present
    # each get a row per document (12). The POSITIVE class is the six VOE docs + six offer-letter docs — LP-395's
    # offer_letter_present had ZERO positives (n=0 -> IN-9 uncalibratable); this fixture supplies six on its own.
    mat = await materialize_tags(
        build_voe_offer_labeling_snapshot(), ai_reasoners=stub_materialization_reasoners()
    )

    def rows(tag: str) -> int:
        return sum(1 for sub in mat.tags.by_subject.values() if tag in sub)

    assert rows("income.voe_present") == 12
    assert rows("income.offer_letter_present") == 12
    # the labelable positive class: six VOE documents + six employment_offer_letter documents
    doc_types = [d.document_type for d in build_voe_offer_labeling_snapshot().documents.entries]
    assert doc_types.count("voe") == 6
    assert doc_types.count("employment_offer_letter") == 6


# ======================================================================= #
# #6 — the other-income continuance fixture
# ======================================================================= #
async def test_other_income_fixture_supplies_continuance_rows() -> None:
    # income_stability (subject:borrower) produces continuance_3yr per borrower. LP-395 measured it all-unknown
    # (n=1, no fixture stated other income with a continuance horizon). This supplies six borrowers, each a 1003
    # declaring a distinct other-income type -> six labelable continuance_3yr rows.
    snap = build_other_income_continuance_snapshot()
    mat = await materialize_tags(snap, ai_reasoners=stub_materialization_reasoners())
    rows = sum(1 for sub in mat.tags.by_subject.values() if "income.continuance_3yr" in sub)
    assert rows == 6
    # six distinct borrowers enumerated (per-borrower attribution + MISMO ids)
    assert len(snap.documents.entries) == 6


# ======================================================================= #
# Declarations — all three producers wired; the two AI groups load
# ======================================================================= #
def test_three_producers_are_declared() -> None:
    decls = load_declarations()
    # #1 deterministic, per-borrower
    d1 = decls["income.is_self_employed"]
    assert d1.mode == "derived" and d1.subject == "borrower"
    # #2 AI, per-transaction
    d2 = decls["txn.is_nsf_or_overdraft"]
    assert d2.mode == "ai" and d2.subject == "transaction"
    # #3 AI, per-loan
    d3 = decls["occupancy.rental_support"]
    assert d3.mode == "ai" and d3.subject == "loan"


def test_new_ai_groups_load_with_the_right_shape() -> None:
    groups = load_ai_groups()
    txn_nsf = groups["txn_nsf"]
    assert txn_nsf.subject == "transaction"
    assert "txn.is_nsf_or_overdraft" in txn_nsf.tag_ids
    # a transaction-subject group must NOT gate documents via applies_to (it is neither a document- nor a
    # borrower-subject group) — the DeclarationError this batch first tripped.
    assert txn_nsf.applies_to is None

    occ = groups["occupancy_rental"]
    assert occ.subject == "loan"
    assert "occupancy.rental_support" in occ.tag_ids


# ======================================================================= #
# The batch activated NO rule (producers/fixtures only)
# ======================================================================= #
def test_no_rule_activation_changed() -> None:
    # LP-418 ships producers + fixtures; it writes and activates NO rule. The written-but-inert rules those
    # producers unblock (IN-12 / AS-7 / IN-14) are activated by their OWN later tickets, not here.
    assert len(ACTIVE_RULE_IDS) == EXPECTED_ACTIVE_RULE_COUNT
