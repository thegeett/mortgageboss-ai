"""LP-379-B — the LF-6T3N calibration fixture now carries 2 wired borrowers, mirroring the DB.

LP-379-A found the fixture had NO wired borrowers (mismo.absent=True, zero borrower_id, belongs_to=None), so
LP-385's per-borrower income_stability producer enumerated nobody and materialized 0 rows — the 5 income
rules it was built to unblock could not be calibrated. This wires the fixture to MIRROR the DB's structure:
2 borrowers (one primary + one co), each owning their income documents by belongs_to, each with a 2-year
non-declining W-2 history. These tests pin that mirror: the borrowers exist, attribution is per-borrower with
NO cross-feed (the LP-332 masking class), income_stability materializes per-borrower on the fixture, and the
wiring is ADDITIVE — the 30-document shape, the txn/id/asset capacities, and the 70 filled mechanical goldens
are undisturbed. (The de-identified fixture cannot mirror one DB detail additively — the co-borrower's stable
employer — documented in docs/tickets/LP-379-B.md; that is a reported divergence, not a test failure.)
"""

from __future__ import annotations

import csv
import io
import json
from collections import Counter

import pytest
from app.verification.eval.lf6t3n_fixture import _B1_ID, _B2_ID, build_lf6t3n_snapshot
from app.verification.eval.worksheet import build_worksheet, compute_capacity, write_worksheets
from app.verification.tag_materialization.ai import AiGroupResult, AiSubjectJudgment, AiTagJudgment
from app.verification.tag_materialization.producer import materialize_tags
from app.verification.tag_materialization.subjects import subject_type

pytestmark = pytest.mark.anyio

_STABILITY = {
    "income.has_2yr_history",
    "income.is_declining",
    "income.same_line_of_work",
    "income.continuance_3yr",
}
_INCOME_TYPES = {"w2", "pay_stub", "voe", "uniform_residential_loan_application"}


def _snap():
    return build_lf6t3n_snapshot()


# --------------------------------------------------------------------------- #
# The 2 borrowers exist and are wired (MISMO + belongs_to), mirroring the DB
# --------------------------------------------------------------------------- #
def test_fixture_has_two_wired_borrowers() -> None:
    snap = _snap()
    assert not snap.mismo.absent  # the fixture now carries MISMO (was absent)
    borrowers = subject_type("borrower").enumerate(snap)
    assert [bid for bid, _ in borrowers] == [
        str(_B1_ID),
        str(_B2_ID),
    ]  # primary (idx1) then co (idx2)


def test_each_borrower_owns_a_two_year_history_no_cross_feed() -> None:
    st = subject_type("borrower")
    by_id = {bid: st.build_context(bsub, None) for bid, bsub in st.enumerate(_snap())}

    b1_income = [d for d in by_id[str(_B1_ID)]["documents"] if d["document_type"] in _INCOME_TYPES]
    b2_income = [d for d in by_id[str(_B2_ID)]["documents"] if d["document_type"] in _INCOME_TYPES]
    assert len(b1_income) == 4 and len(b2_income) == 4  # 2 pay stubs + 2 W-2s each (mirrors the DB)

    # A genuine 2-year W-2 history (the point of LP-379-B — the DB has 2024+2025, the old fixture had only 2025)
    b1_years = sorted(d["fields"]["tax_year"] for d in b1_income if d["document_type"] == "w2")
    assert b1_years == ["2024", "2025"]

    # NO cross-feed (LP-332 masking): B1 sees only its employers, none of B2's, and vice-versa.
    b1_emps = {d["fields"].get("employer_name") for d in b1_income}
    b2_emps = {d["fields"].get("employer_name") for d in b2_income}
    assert b1_emps == {"Acme Logistics Inc", "Northgate Warehousing"}
    assert b2_emps == {"Sterling Retail LLC", "Cafe Bluebird"}
    assert b1_emps.isdisjoint(b2_emps)


# --------------------------------------------------------------------------- #
# income_stability materializes per-borrower ON THE FIXTURE (stub reasoner — deterministic, no network)
# --------------------------------------------------------------------------- #
class _Stub:
    def __init__(self) -> None:
        self.employers_per_subject: dict[str, set[str]] = {}

    async def __call__(self, context_json: str) -> AiGroupResult:
        subjects = json.loads(context_json)["subjects"]
        judgments = []
        for s in subjects:
            self.employers_per_subject[str(s["index"])] = {
                d["fields"].get("employer_name") for d in s.get("documents", [])
            }
            judgments.append(
                AiSubjectJudgment(
                    index=int(s["index"]),
                    tags={
                        t.split(".", 1)[1]: AiTagJudgment("yes", 0.9, "stub") for t in _STABILITY
                    },
                )
            )
        return AiGroupResult(judgments, 0, 0, "stub", False)


async def test_income_stability_materializes_per_borrower_on_the_fixture() -> None:
    stub = _Stub()
    out = await materialize_tags(
        _snap(),
        ai_reasoners={"income_stability": stub},
        only_subjects=frozenset({"borrower"}),
        only_groups=frozenset({"income_stability"}),
    )
    # Keyed under each borrower_id (not a document content_id).
    assert out.tags.by_subject[str(_B1_ID)]["income.has_2yr_history"].value == "yes"
    assert out.tags.by_subject[str(_B2_ID)]["income.has_2yr_history"].value == "yes"
    # Each borrower's call carried ONLY its own employers — no cross-borrower leak on the fixture.
    seen = list(stub.employers_per_subject.values())
    assert {"Acme Logistics Inc", "Northgate Warehousing"} in seen
    assert {"Sterling Retail LLC", "Cafe Bluebird"} in seen
    assert all(
        v
        in (
            {"Acme Logistics Inc", "Northgate Warehousing"},
            {"Sterling Retail LLC", "Cafe Bluebird"},
        )
        for v in seen
    )


def test_worksheet_emits_eight_per_borrower_income_stability_rows() -> None:
    rows = [r for r in build_worksheet(_snap()) if r.tag_id in _STABILITY]
    assert len(rows) == 8  # 2 borrowers x 4 tags
    assert {r.subject_id for r in rows} == {str(_B1_ID), str(_B2_ID)}
    caps = {c.tag_id: c for c in compute_capacity(_snap())}
    assert all(caps[t].status == "labelable" and caps[t].capacity == 2 for t in _STABILITY)


# --------------------------------------------------------------------------- #
# ADDITIVE — the wiring disturbs nothing the fixture already asserted
# --------------------------------------------------------------------------- #
def test_document_shape_is_unchanged() -> None:
    snap = _snap()
    by_type = Counter(e.document_type for e in snap.documents.entries)
    assert len(snap.documents.entries) == 30 and by_type["bank_statement"] == 5
    assert by_type["pay_stub"] == 4 and by_type["w2"] == 4 and by_type["drivers_license"] == 2
    assert sum(len(e.transactions or ()) for e in snap.documents.entries) == 50


def test_non_borrower_capacities_are_unchanged() -> None:
    caps = {c.tag_id: c for c in compute_capacity(_snap())}
    # the doc/txn-subject families the fixture already materialized are untouched by adding borrowers
    assert caps["txn.is_money_in"].capacity == 50 and caps["txn.apparent_category"].capacity == 50
    assert (
        caps["income.documented_monthly"].capacity == 8 and caps["id.name_normalized"].capacity == 2
    )
    assert (
        caps["asset.usable_value"].capacity == 3
        and caps["stmt.owner_matches_borrower"].capacity == 8
    )


def test_filled_goldens_survive_regeneration_on_the_wired_fixture(tmp_path) -> None:
    # A filled mechanical golden survives regeneration against the WIRED fixture (the merge is additive — the
    # tax-year wiring changed w2/w4 CONTEXT text, never a golden_label; only income_stability rows are added).
    from app.verification.eval.worksheet import load_golden

    snap = _snap()
    write_worksheets(snap, tmp_path)
    mech = tmp_path / "lf6t3n-labels-mechanical.csv"
    reader = list(csv.DictReader(io.StringIO(mech.read_text())))
    reader[0]["golden_label"] = "6500"
    key = (reader[0]["tag_id"], reader[0]["subject_id"])
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=reader[0].keys(), lineterminator="\n")
    w.writeheader()
    w.writerows(reader)
    mech.write_text(buf.getvalue())

    write_worksheets(snap, tmp_path)  # regenerate against the wired fixture
    assert load_golden(mech.read_text()).get(key) == "6500"
