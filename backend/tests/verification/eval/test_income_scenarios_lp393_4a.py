"""LP-393-4a — the fixture + liquidation-prompt + label corrections that make LP-393-4's re-score valid.

LP-393-4's numbers measured the wrong thing: same_line_of_work's 38% was a FIXTURE gap (missing `occupation`,
not a definitional divergence — 7 rows Priya marked `unknown` "No occupation given"); liquidation_terms' finding
was INVERTED (the AI UNDER-restricts penalized fully-vested accounts); is_declining had 2 label slips. These pin
(keyless): every scenario borrower now carries `occupation` (unchanged per borrower where there is no job
change), the clear-cut driving fields are untouched, the asset_facts prompt encodes Priya's precedence rule,
LF-6T3N is untouched, and the corrected scenario goldens are exactly the 5 cells she changed.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from app.verification.eval.income_scenarios import build_income_calibration_snapshot
from app.verification.eval.lf6t3n_fixture import build_lf6t3n_snapshot
from app.verification.tag_materialization.declarations import load_ai_groups

_WORKSHEET = Path(__file__).resolve().parents[4] / "docs/calibration/income-scenario-labels.csv"


def _income_docs_by_borrower() -> dict[int, list]:
    snap = build_income_calibration_snapshot()
    out: dict[int, list] = {}
    for e in snap.documents.entries:
        if e.belongs_to is None:
            continue
        out.setdefault(int(str(e.belongs_to[0].borrower_id)[-2:]), []).append(e)
    return out


def test_every_scenario_borrower_has_occupation_on_all_income_docs() -> None:
    # the fixture defect fixed: same_line_of_work is now answerable (7 rows were `unknown` ONLY for lack of it)
    docs = _income_docs_by_borrower()
    for n, entries in docs.items():
        assert all("occupation" in e.fields for e in entries), f"B{n} still missing occupation"


def test_no_job_change_scenarios_keep_one_occupation_throughout() -> None:
    # per Priya's rule ("no job change -> yes"): a same-employer scenario has ONE unchanged occupation, so the
    # tag can resolve `yes`; the intended-change scenarios (B8 career change, B11 promotion) differ on purpose.
    docs = _income_docs_by_borrower()
    for n in (3, 4, 6, 9, 12):  # same-employer scenarios
        occs = {str(e.fields["occupation"].value) for e in docs[n]}
        assert len(occs) == 1, f"B{n} occupation changed across its docs"
    assert (
        len({str(e.fields["occupation"].value) for e in docs[8]}) == 2
    )  # career change stays a change


def test_clearcut_driving_fields_are_untouched() -> None:
    # only the missing occupation was added — wages / tax years / employers are exactly as built (intent intact)
    docs = _income_docs_by_borrower()

    def wages(n: int) -> list[str]:
        return [
            str(e.fields["wages_tips_other_comp"].value)
            for e in docs[n]
            if "wages_tips_other_comp" in e.fields
        ]

    assert wages(3) == ["80000", "60000"] and wages(4) == ["60000", "75000"]
    assert wages(6) == ["58000", "60000", "61500"]  # three-year history unchanged
    assert {str(e.fields["employer_name"].value) for e in docs[3]} == {"Acme Freight Co"}


def test_liquidation_prompt_encodes_priyas_precedence() -> None:
    prompt = load_ai_groups()["asset_facts"].system_prompt.lower()
    assert "precedence" in prompt
    # partial vesting -> vested_usable; penalties (even fully vested) -> restricted; brokerage -> fully_liquid
    assert "partial vesting" in prompt and "vested_usable" in prompt
    assert (
        "penalt" in prompt and "restricted" in prompt and "fully-vested" in prompt.replace(" ", "-")
    )
    assert "brokerage" in prompt and "fully_liquid" in prompt


def test_lf6t3n_snapshot_is_untouched() -> None:
    lf = build_lf6t3n_snapshot()
    bids = {str(r.borrower_id) for e in lf.documents.entries for r in (e.belongs_to or ())}
    assert len(bids) == 2  # still exactly its 2 borrowers — no scenario leakage


def test_corrected_goldens_are_exactly_the_five_cells() -> None:
    rows = {
        (r["tag_id"], r["subject_id"]): r["golden_label"].strip()
        for r in csv.DictReader(io.StringIO(_WORKSHEET.read_text(encoding="utf-8")))
    }
    # the 5 corrections Priya made
    assert rows[("income.is_declining", "93000000-0000-4000-8000-000000000009")] == "yes"
    assert rows[("income.is_declining", "93000000-0000-4000-8000-000000000015")] == "no"
    assert rows[("asset.liquidation_terms", "inc-asset-4")] == "restricted"
    assert rows[("asset.liquidation_terms", "inc-asset-5")] == "restricted"
    assert rows[("asset.liquidation_terms", "inc-asset-6")] == "restricted"
    # the untouched asset cells stay as she left them (her rule: brokerage=liquid, graded-vested=vested_usable)
    assert rows[("asset.liquidation_terms", "inc-asset-1")] == "fully_liquid"
    assert rows[("asset.liquidation_terms", "inc-asset-2")] == "fully_liquid"
    assert rows[("asset.liquidation_terms", "inc-asset-3")] == "vested_usable"
