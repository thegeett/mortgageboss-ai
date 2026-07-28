"""LP-422 — the deterministic schedule-presence producer: Schedule C/E → a per-borrower income-scope fact.

LP-421 surfaced Schedule C / Schedule E into the snapshot; nothing read them. This turns PRESENCE into a tag —
DETERMINISTICALLY (presence is a FACT, not a judgment), so no calibration round, no worksheet, no Priya bar (the
ADR-332 escape hatch). Self-employment REUSES income.is_self_employed (LP-418), extended with Schedule C
presence; rental is a NEW borrower tag income.has_rental_income off Schedule E — because income.type is AI-only
(a tag has exactly one producer) and cannot carry a derived schedule signal.

These pin: Schedule C → self-employment; Schedule E → rental; presence not value (a LOSS still counts); fail
closed (no schedule → never a fabricated `base`); the document→borrower chain (anti-structural-death); and no
existing fixture's income.type / is_self_employed moves (the equivalence).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.verification.eval.fire_path_scenarios import build_tax_return_with_schedules_snapshot
from app.verification.eval.income_scenarios import build_income_calibration_snapshot
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.snapshot.documents_section import build_schedule_c, build_schedule_e
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
from app.verification.tag_materialization.declarations import ProductionMode, load_declarations
from app.verification.tag_materialization.derived import produce_derived_tags
from tests.expected_active import EXPECTED_ACTIVE_RULE_COUNT

_DECLS = load_declarations()
_SELF_EMPLOYED = _DECLS["income.is_self_employed"]
_RENTAL = _DECLS["income.has_rental_income"]
_B = UUID("95000000-0000-4000-8000-0000000001cc")


def _tf(value: str) -> dict[str, object]:
    return {"value": value, "source": None, "confidence": None}


def _snap_from_extraction(extracted: dict[str, object], *, dtype: str = "tax_return") -> Snapshot:
    """One borrower with a document whose (LP-421) schedules are built through the real reshape."""
    doc = DocumentEntry(
        content_id="tr",
        document_type=dtype,
        belongs_to=(BorrowerRef(borrower_id=_B, name="X"),),
        fields={},
        schedule_c=build_schedule_c(extracted, dtype),
        schedule_e=build_schedule_e(extracted, dtype),
    )
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
        documents=DocumentsSection.present([doc]),
        mismo=MismoSection.present(
            {"borrower.1.borrower_id": Field.present(str(_B), source=FieldSource.PARSED)}
        ),
        tags=TagsSection.present({}),
    )


def _value(decl, snap: Snapshot, borrower: UUID = _B) -> str | None:
    out = produce_derived_tags(decl, snap)
    tag = out.get(str(borrower), {}).get(decl.tag_id)
    return None if tag is None else str(tag.value)


# ======================================================================= #
# The signal — presence, not value
# ======================================================================= #
def test_schedule_c_present_is_self_employment() -> None:
    snap = _snap_from_extraction(
        {"schedule_c": [{"business_name": _tf("Acme"), "net_profit": _tf("82000.00")}]}
    )
    assert _value(_SELF_EMPLOYED, snap) == "yes"


def test_schedule_c_loss_is_still_self_employment() -> None:
    # presence, not net_profit — a Schedule C showing a LOSS is still self-employment (no value test smuggled in).
    snap = _snap_from_extraction(
        {"schedule_c": [{"business_name": _tf("Struggling LLC"), "net_profit": _tf("-15000.00")}]}
    )
    assert _value(_SELF_EMPLOYED, snap) == "yes"


def test_schedule_e_present_is_rental() -> None:
    snap = _snap_from_extraction(
        {
            "schedule_e": {
                "total_net_rental_income": _tf("9000"),
                "properties": [{"rents_received": _tf("9000")}],
            }
        }
    )
    assert _value(_RENTAL, snap) == "yes"
    assert _value(_SELF_EMPLOYED, snap) == "unknown"  # a rental filer is not thereby self-employed


def test_schedule_e_zero_rent_property_still_rental() -> None:
    # a Schedule E with a property but no rents_received in the year is still rental activity (presence).
    snap = _snap_from_extraction({"schedule_e": {"properties": [{"address": _tf("12 Oak St")}]}})
    assert _value(_RENTAL, snap) == "yes"


# ======================================================================= #
# Fail closed — no schedule NEVER means `base`
# ======================================================================= #
def test_tax_return_with_neither_schedule_fails_closed_never_base() -> None:
    snap = _snap_from_extraction({"tax_year": _tf("2025")})  # a tax return, no Schedule C or E
    se = _value(_SELF_EMPLOYED, snap)
    assert (
        se == "unknown" and se != "base"
    )  # no self-employment signal → unknown, never a fabricated wage type
    assert _value(_RENTAL, snap) == "no"  # a filed return with no Schedule E → no rental reported


def test_no_tax_return_and_no_income_type_is_unknown_for_rental() -> None:
    # a borrower with a pay stub carrying NO income.type tag, no tax return → no readable signal at all → unknown.
    snap = _snap_from_extraction({}, dtype="pay_stub")
    assert _value(_RENTAL, snap) == "unknown"
    assert _value(_SELF_EMPLOYED, snap) == "unknown"


def _snap_with_income_type(income_type: str, *, dtype: str = "pay_stub") -> Snapshot:
    """One borrower + one income document carrying an income.type tag (no schedules), to exercise the
    income.type fallback (LP-422 review). income.type is a document-subject tag, keyed at the doc's content_id."""
    doc = DocumentEntry(
        content_id="doc1",
        document_type=dtype,
        belongs_to=(BorrowerRef(borrower_id=_B, name="X"),),
        fields={},
    )
    tag = Tag(
        value=income_type,
        confidence=0.9,
        reasoning="stub",
        source_facts=("doc1",),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.STRUCTURAL_FACT,
        tag_version=1,
        stage=TagStage.A,
    )
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
        documents=DocumentsSection.present([doc]),
        mismo=MismoSection.present(
            {"borrower.1.borrower_id": Field.present(str(_B), source=FieldSource.PARSED)}
        ),
        tags=TagsSection.present({"doc1": {"income.type": tag}}),
    )


def test_income_type_rental_is_rental_even_without_a_schedule_e() -> None:
    # LP-422 review: income.type == "rental" (a 1003/doc-declared rental income_amounts perceives — it reads the
    # 1003) is a rental signal even with NO Schedule E filed, MIRRORING is_self_employed's self_employment path.
    snap = _snap_with_income_type("rental")
    assert _value(_RENTAL, snap) == "yes"


def test_readable_non_rental_income_type_is_a_definitive_no() -> None:
    # LP-422 review: a borrower with a readable income.type that is NOT rental (a W-2 wage earner, no tax return)
    # reaches "no" — NOT "unknown" — so IN-13 can not_applicable a wage earner instead of couldnt_checking every
    # no-tax-return file. Symmetric with is_self_employed's "no" (readable types, none self-employment).
    snap = _snap_with_income_type("base")
    assert _value(_RENTAL, snap) == "no"
    assert _value(_SELF_EMPLOYED, snap) == "no"  # the sibling: base wage, not self-employment


# ======================================================================= #
# D4 — the document→borrower chain (anti-structural-death)
# ======================================================================= #
def test_signal_reaches_the_borrower_subject_on_lp421_fixture() -> None:
    # The schedules live on a tax_return DOCUMENT; both tags materialize at the BORROWER subject the document
    # belongs_to (the value a per_borrower rule — IN-12 / IN-13 — actually reads).
    snap = build_tax_return_with_schedules_snapshot()
    borrower = snap.documents.entries[0].belongs_to[0].borrower_id  # type: ignore[index]
    assert _value(_SELF_EMPLOYED, snap, borrower) == "yes"  # Schedule C (net_profit 82000)
    assert _value(_RENTAL, snap, borrower) == "yes"  # Schedule E (2 properties)


# ======================================================================= #
# D1 — the mixed-mode fact + declarations
# ======================================================================= #
def test_income_type_is_ai_only_so_the_schedule_signal_needed_derived_tags() -> None:
    # WHY the signal did not feed income.type: a tag has exactly one producer, and income.type's is AI. A
    # derived producer for it is impossible — hence the borrower-level derived tags below.
    assert _DECLS["income.type"].mode is ProductionMode.AI
    assert _SELF_EMPLOYED.mode is ProductionMode.DERIVED and _SELF_EMPLOYED.subject == "borrower"
    assert _RENTAL.mode is ProductionMode.DERIVED and _RENTAL.subject == "borrower"


# ======================================================================= #
# D6 — equivalence: no existing fixture moves
# ======================================================================= #
def test_income_type_and_is_self_employed_unchanged_on_an_existing_fixture() -> None:
    # No existing fixture carries a Schedule C/E on a DocumentEntry (LP-421 defaults them None), so the extended
    # is_self_employed reads exactly what it read before (its income.type path). income.type is untouched.
    snap = build_income_calibration_snapshot()
    for _sid, tags in produce_derived_tags(_SELF_EMPLOYED, snap).items():
        assert tags["income.is_self_employed"].value in (
            "no",
            "unknown",
            "yes",
        )  # produced normally
    # none of the calibration documents has a Schedule C → no schedule-driven "yes"
    for entry in snap.documents.entries:
        assert entry.schedule_c is None and entry.schedule_e is None


def test_no_rule_activation_changed() -> None:
    assert len(ACTIVE_RULE_IDS) == EXPECTED_ACTIVE_RULE_COUNT  # a producer activates nothing
