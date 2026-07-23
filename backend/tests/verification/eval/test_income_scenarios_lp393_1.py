"""LP-393-1 — the standalone income-scenario snapshot builder (thin-n calibration data).

These pin, KEYLESS (no real model — the live reasoning results are reported in docs/tickets/LP-393-1.md, not
asserted here, because the model is non-deterministic): the builder produces the scenario borrowers at their
MINIMUM document sets; the clear-cut scenarios vary exactly the fields that drive each tag; the fixture is
COMPLETELY SEPARATE from LF-6T3N (own ids, no collision, no import either way, LF-6T3N byte-unchanged);
per-borrower isolation holds; and the ambiguous cases carry NO encoded answer (anti-anchoring).
"""

from __future__ import annotations

import inspect
from pathlib import Path

from app.verification.eval import income_scenarios
from app.verification.eval.income_scenarios import (
    CLEARCUT_EXPECTATIONS,
    SCENARIO_BORROWER_IDS,
    build_income_calibration_snapshot,
)
from app.verification.eval.lf6t3n_fixture import build_lf6t3n_plus, build_lf6t3n_snapshot
from app.verification.tag_materialization.subjects import _borrower_context, subject_type


def _by_scenario() -> dict[int, list]:
    snap = build_income_calibration_snapshot()
    out: dict[int, list] = {}
    for e in snap.documents.entries:
        if e.belongs_to is None:
            continue  # asset docs (per-document, no borrower)
        n = int(str(e.belongs_to[0].borrower_id)[-2:])
        out.setdefault(n, []).append(e)
    return out


# --------------------------------------------------------------------------- #
# MINIMUM DOCUMENTS — each scenario carries only what its tag needs (no noise)
# --------------------------------------------------------------------------- #
def test_scenarios_carry_only_their_own_minimum_income_documents() -> None:
    docs = _by_scenario()
    # the declining/rising/history scenarios are W-2s only; NO bank statement / DL / purchase agreement anywhere
    every_type = {e.document_type for es in docs.values() for e in es}
    assert every_type <= {"w2", "pay_stub", "voe"}  # only income document types
    assert "bank_statement" not in every_type and "drivers_license" not in every_type
    assert len(docs[3]) == 2 and len(docs[5]) == 1  # decline needs 2 W-2s; one-year needs 1
    assert len(docs[6]) == 3  # three consecutive years


def test_clearcut_scenarios_vary_the_fields_that_drive_each_tag() -> None:
    docs = _by_scenario()

    def _wages(n: int) -> list[str]:
        return [
            str(e.fields["wages_tips_other_comp"].value)
            for e in docs[n]
            if "wages_tips_other_comp" in e.fields
        ]

    # is_declining reads wages across years: B3 falls (80k->60k), B4 rises (60k->75k)
    assert _wages(3) == ["80000", "60000"] and _wages(4) == ["60000", "75000"]

    def _occ(n: int) -> list[str]:
        return [str(e.fields["occupation"].value) for e in docs[n] if "occupation" in e.fields]

    # same_line_of_work reads the role: B7 same (Nurse/Nurse), B8 different (Warehouse/Office)
    assert _occ(7) == ["Registered Nurse", "Registered Nurse"]
    assert _occ(8)[0] != _occ(8)[1]


# --------------------------------------------------------------------------- #
# SEPARATION — completely disjoint from LF-6T3N (the realism anchor), both ways
# --------------------------------------------------------------------------- #
def test_ids_are_disjoint_from_lf6t3n() -> None:
    snap = build_income_calibration_snapshot()
    lf = build_lf6t3n_snapshot()
    lf_bids = {str(r.borrower_id) for e in lf.documents.entries for r in (e.belongs_to or ())}
    assert SCENARIO_BORROWER_IDS and not (
        SCENARIO_BORROWER_IDS & lf_bids
    )  # no borrower-id collision
    lf_cids = {e.content_id for e in lf.documents.entries}
    my_cids = {e.content_id for e in snap.documents.entries}
    assert my_cids and not (my_cids & lf_cids)  # no content-id collision
    assert snap.loan_file_id != lf.loan_file_id


def test_neither_builder_imports_the_other() -> None:
    my_src = inspect.getsource(income_scenarios)
    lf_src = (
        Path(income_scenarios.__file__).with_name("lf6t3n_fixture.py").read_text(encoding="utf-8")
    )
    assert "lf6t3n_fixture" not in my_src  # this builder never imports the LF-6T3N one
    assert "income_scenarios" not in lf_src  # and LF-6T3N never imports this one


def test_lf6t3n_fixtures_are_byte_unchanged() -> None:
    # building the scenario snapshot must not perturb LF-6T3N: it still has EXACTLY its 2 borrowers, and none
    # of the scenario borrowers leaked in.
    build_income_calibration_snapshot()
    for lf in (build_lf6t3n_snapshot(), build_lf6t3n_plus()):
        bids = {str(r.borrower_id) for e in lf.documents.entries for r in (e.belongs_to or ())}
        assert len(bids) == 2 and not (bids & SCENARIO_BORROWER_IDS)


# --------------------------------------------------------------------------- #
# PER-BORROWER ISOLATION — a borrower's context sees ONLY its own documents (no cross-feed)
# --------------------------------------------------------------------------- #
def test_per_borrower_context_has_no_cross_feed() -> None:
    snap = build_income_calibration_snapshot()
    applies = frozenset({"w2", "pay_stub", "voe", "uniform_residential_loan_application"})
    for _sid, raw in subject_type("borrower").enumerate(snap):
        ctx = _borrower_context(raw, applies)
        n = int(raw.borrower_id[-2:])
        my_cids = {
            e.content_id
            for e in snap.documents.entries
            if e.belongs_to and str(e.belongs_to[0].borrower_id) == raw.borrower_id
        }
        # the context carries exactly this borrower's income docs (no other borrower's docs cross-fed in)
        assert len(ctx["documents"]) == len(my_cids), f"B{n} context cross-fed"  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# ANTI-ANCHORING — the ambiguous + continuance cases carry NO encoded answer
# --------------------------------------------------------------------------- #
def test_only_clearcut_scenarios_have_expected_answers() -> None:
    # clear-cut cases (B3-B8) have expectations; ambiguous (B9-B13) + continuance probes (B14-B15) do NOT
    assert set(CLEARCUT_EXPECTATIONS) == {3, 4, 5, 6, 7, 8}
    for ambiguous in (9, 10, 11, 12, 13, 14, 15):
        assert ambiguous not in CLEARCUT_EXPECTATIONS
