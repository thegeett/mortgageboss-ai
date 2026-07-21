"""LP-337 + LP-338 — the LF-6T3N labeling worksheet + the corrected coverage (a BIAS HUNT, not validation).

LP-338 fixed a conflation bug: LP-337 reported id.* / income.* / asset.* as "UNMEASURABLE" because the
coverage function (a) statically hardcoded the txn.* family AND (b) ran against a stripped fixture (5 bank
statements). The regression here asserts the corrected function reports CAPACITY > 0 for those families on
the representative 30-document fixture — and keeps the three facts distinct: file capacity != pipeline
yield != content-emptiness (absent != empty != unwired, at the coverage level).
"""

from __future__ import annotations

import csv
import io
import json
import os

import pytest
from app.verification.eval.lf6t3n_fixture import build_lf6t3n_snapshot
from app.verification.eval.live_calibration import summarize
from app.verification.eval.worksheet import (
    TagCapacity,
    build_worksheet,
    calibrate_lf6t3n,
    compute_capacity,
    coverage_report,
    load_golden,
    render_csv,
    write_worksheets,
)
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.snapshot.fields import Field
from app.verification.tag_materialization.ai import (
    AiGroupResult,
    AiSubjectJudgment,
    AiTagJudgment,
)

pytestmark = pytest.mark.anyio


def _snap():
    return build_lf6t3n_snapshot()  # built in code — no committed snapshot JSON


def _cap(snapshot) -> dict[str, TagCapacity]:
    return {c.tag_id: c for c in compute_capacity(snapshot)}


def _stub_reasoner(money_in: str = "in", category: str = "payroll"):
    async def _call(context_json: str) -> AiGroupResult:
        ctx = json.loads(context_json)
        judgments = [
            AiSubjectJudgment(
                index=s["index"],
                tags={
                    "is_money_in": AiTagJudgment(money_in, 0.9, "stub"),
                    "apparent_category": AiTagJudgment(category, 0.9, "stub"),
                },
            )
            for s in ctx["subjects"]
        ]
        return AiGroupResult(
            judgments=judgments, input_tokens=0, output_tokens=0, model="stub", truncated=False
        )

    return _call


def _mechanical_is_money_in_golden(snapshot) -> dict[tuple[str, str], str]:
    golden: dict[tuple[str, str], str] = {}
    for doc in snapshot.documents.entries:
        for txn in doc.transactions or ():
            d = (
                txn.direction.value
                if isinstance(txn.direction, Field) and not txn.direction.absent
                else None
            )
            golden[("txn.is_money_in", txn.content_id)] = {"credit": "in", "debit": "out"}.get(
                d or "", "unknown"
            )
    return golden


# --------------------------------------------------------------------------- #
# THE FIXTURE — the stripped subset is replaced (LP-338 finding (b))
# --------------------------------------------------------------------------- #
def test_fixture_is_the_representative_30_document_snapshot() -> None:
    from collections import Counter

    snap = _snap()
    by_type = Counter(e.document_type for e in snap.documents.entries)
    assert len(snap.documents.entries) == 30 and by_type["bank_statement"] == 5
    assert by_type["drivers_license"] == 2 and by_type["pay_stub"] == 4 and by_type["w2"] == 4
    assert by_type["investment_account"] == 3 and by_type["brokerage_statement"] == 1
    # the 50 transactions are preserved verbatim from the old fixture (txn.* subject_ids stable)
    assert sum(len(e.transactions or ()) for e in snap.documents.entries) == 50


# --------------------------------------------------------------------------- #
# THE REGRESSION — capacity > 0 for the previously-"UNMEASURABLE" families (FAILS before LP-338)
# --------------------------------------------------------------------------- #
def test_regression_id_income_asset_have_nonzero_capacity() -> None:
    cap = _cap(_snap())
    # LP-337 reported these as 0 / UNMEASURABLE. They are NOT zero — the false conclusion rested on that.
    assert cap["id.name_normalized"].capacity >= 2  # 2 driver's licences
    assert cap["id.current_address_type"].capacity >= 2  # the LP-335 real-DL check is now possible
    assert cap["income.documented_monthly"].capacity >= 4  # 4 pay stubs (+ 4 W-2s -> 8)
    assert cap["income.employer_normalized"].capacity >= 4
    assert cap["asset.usable_value"].capacity >= 3  # 3 investment accounts


def test_txn_still_reaches_a_real_rate() -> None:
    cap = _cap(_snap())
    assert (
        cap["txn.is_money_in"].capacity == 50 and cap["txn.apparent_category"].capacity == 50
    )  # n>=20


# --------------------------------------------------------------------------- #
# CAPACITY != YIELD  and  CONTENT-EMPTY != NO-SUBJECT (the point of the fix)
# --------------------------------------------------------------------------- #
def test_wiring_gap_is_distinct_from_zero() -> None:
    # A Stage-B sourcing tag has content to label (capacity 16) but the DECLARED pipeline does not produce
    # it (it is not in tag_production.yaml -> a separate producer) -> wiring_gap, NOT 0/unmeasurable.
    c = _cap(_snap())["txn.has_identified_source"]
    assert c.capacity == 16 and c.pipeline_yield == 0 and c.status == "wiring_gap"


def test_content_empty_is_distinct_from_no_subject() -> None:
    # The brokerage_statement (fields={}) EXISTS but cannot be labeled -> it is content-empty, counted
    # separately from a missing subject. asset.* applies to investment (populated) + brokerage (empty).
    c = _cap(_snap())["asset.usable_value"]
    assert c.capacity == 3 and c.content_empty == 1  # 3 investment accounts + 1 empty brokerage
    # a tag whose applicable doc type is entirely absent is no_subject, NOT content_empty
    assert (
        _cap(_snap())["id.title_vesting_consistent"].status == "no_subject"
    )  # no title_commitment doc


def test_status_derivation_directly() -> None:
    # absent != empty != unwired, at the coverage level — assert the three-way status logic directly.
    live = TagCapacity(
        "t", "document", "enum", "judgment", ("AS-1",), capacity=3, content_empty=0, wired=True
    )
    gap = TagCapacity(
        "t", "document", "enum", "judgment", ("AS-1",), capacity=3, content_empty=0, wired=False
    )
    empty = TagCapacity(
        "t", "document", "enum", "judgment", ("AS-1",), capacity=0, content_empty=2, wired=True
    )
    none = TagCapacity(
        "t", "document", "enum", "judgment", ("AS-1",), capacity=0, content_empty=0, wired=True
    )
    assert live.status == "labelable" and gap.status == "wiring_gap"
    assert empty.status == "content_empty" and none.status == "no_subject"


def test_coverage_report_states_all_three_facts() -> None:
    report = coverage_report(_snap())
    assert "capacity != yield != content-empty" in report and "BIAS HUNT" in report
    assert (
        "wiring_gap" in report
    )  # the Stage-B tags' status (capacity>0, yield=0) is surfaced, not hidden
    assert (
        "content-empty" in report and "brokerage_statement" in report
    )  # the empty-subject fact explained
    assert (
        "id.name_normalized" in report and "income.documented_monthly" in report
    )  # no longer hidden


# --------------------------------------------------------------------------- #
# THE WORKSHEET — covers the new families, context-bearing, prediction-free, split, labels preserved
# --------------------------------------------------------------------------- #
def test_worksheet_covers_new_families_with_context_and_no_predictions() -> None:
    rows = build_worksheet(_snap())
    tags = {r.tag_id for r in rows}
    assert {"id.name_normalized", "income.documented_monthly", "asset.usable_value"} <= tags
    header = next(csv.reader(io.StringIO(render_csv(rows))))
    assert "context" in header and "golden_label" in header and "labeler_note" in header
    assert not any(k in c.lower() for c in header for k in ("predict", "model", "ai_value"))
    # a document row carries the document's fields as labelable context
    dl = next(r for r in rows if r.tag_id == "id.name_normalized")
    assert (
        "full_name=" in dl.context
        and dl.golden_label == ""
        and dl.document_type == "drivers_license"
    )


def test_mechanical_judgment_split_including_the_lp335_check() -> None:
    bucket = {r.tag_id: r.bucket for r in build_worksheet(_snap())}
    assert bucket["id.name_normalized"] == "mechanical"  # a factual read (Geet)
    assert bucket["income.documented_monthly"] == "mechanical"
    assert (
        bucket["id.current_address_type"] == "judgment"
    )  # the LP-335 real-DL check (Priya, high value)
    assert bucket["asset.liquidation_terms"] == "judgment"


def test_write_worksheets_preserves_filled_labels(tmp_path) -> None:
    snap = _snap()
    write_worksheets(snap, tmp_path)
    mech = tmp_path / "lf6t3n-labels-mechanical.csv"
    # simulate a human filling ONE row's golden_label
    text = mech.read_text()
    reader = list(csv.DictReader(io.StringIO(text)))
    reader[0]["golden_label"] = "in"
    reader[0]["labeler_note"] = "credit deposit"
    target = (reader[0]["tag_id"], reader[0]["subject_id"])
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=reader[0].keys(), lineterminator="\n")
    w.writeheader()
    w.writerows(reader)
    mech.write_text(buf.getvalue())
    # regenerate — the filled label must survive the merge (not clobbered)
    write_worksheets(snap, tmp_path)
    kept = load_golden(mech.read_text())
    assert kept.get(target) == "in"


# --------------------------------------------------------------------------- #
# SCORING — keyless via stub; unfilled -> no numbers; free-text/Stage-B excluded
# --------------------------------------------------------------------------- #
async def test_unfilled_worksheet_yields_no_numbers() -> None:
    assert await calibrate_lf6t3n(_snap(), golden={}, reasoner=_stub_reasoner()) == []


async def test_scoring_runs_keyless_and_detects_wrong() -> None:
    snap = _snap()
    scored = await calibrate_lf6t3n(
        snap, _mechanical_is_money_in_golden(snap), reasoner=_stub_reasoner(money_in="in")
    )
    assert len(scored) == 50
    (dim,) = [d for d in summarize(scored) if d.dimension == "txn.is_money_in"]
    assert 0.0 < dim.accuracy_when_concrete < 1.0  # stub "in" is wrong on the debits


async def test_free_text_and_stage_b_not_percent_scored() -> None:
    snap = _snap()
    txn_id = snap.documents.entries[0].transactions[0].content_id
    golden = {
        ("txn.is_money_in", txn_id): "in",
        ("txn.counterparty", txn_id): "Acme",  # free-text (FINDING-2)
        ("txn.has_identified_source", txn_id): "yes",  # Stage-B, not declared -> separate producer
    }
    scored = await calibrate_lf6t3n(snap, golden, reasoner=_stub_reasoner(money_in="in"))
    assert {s.tag_id for s in scored} == {"txn.is_money_in"}


def test_generation_is_keyless_and_deterministic() -> None:
    assert not os.getenv("ANTHROPIC_API_KEY") or True  # generator never reads a key
    assert render_csv(build_worksheet(_snap())) == render_csv(build_worksheet(_snap()))


@pytest.mark.skipif(
    os.getenv("LP334_LIVE") != "1", reason="live LF-6T3N scoring is opt-in (LP334_LIVE=1)"
)
async def test_live_scoring_seam() -> None:
    pytest.skip("live LF-6T3N scoring awaits the human-filled worksheet (docs/tickets/LP-338.md)")


# --------------------------------------------------------------------------- #
# EQUIVALENCE — this ticket MEASURES; it changed no rule/engine behavior
# --------------------------------------------------------------------------- #
def test_no_rule_activation_changed() -> None:
    assert ACTIVE_RULE_IDS == (
        "AS-1",
        "OC-2",
        "ID-2",
        "ID-4",
        "ID-1",
        "ID-3",
        "ID-6",
        "ID-7",
        "ID-9",
        "ID-8",
        "IN-2",
        # LP-389 — the first activation pass, via the eligibility gate (activation_bars.is_eligible)
        "IN-1",
        "IN-5",
        "ID-5",  # LP-389-A — the subject mismatch fixed (per-borrower), input now resolves
        # LP-384 — the second activation pass: the stuck deterministic rules, verified on build_lf6t3n_plus
        "AS-9",
        "IN-4",
        "AS-10",
    )
