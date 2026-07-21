"""LP-379-A — refresh the calibration worksheet against the post-LP-385 tag layer.

The instrument must match what the tags DO today, before Priya labels. The ONE tag family that drifted is
income_stability: LP-385 moved it from the DOCUMENT subject to the BORROWER subject (a 2-year trend is a
cross-document question a single document cannot answer — LP-378 measured 0/120 per-document). So:

* its 32 stale PER-DOCUMENT rows must be GONE, and
* when borrowers ARE wired it must produce one row PER BORROWER per tag (matching LP-385's producer).

(LP-379-B has since wired the 2 DB borrowers into the fixture, so income_stability now materializes there —
the once-borrower-less assertion below was updated to the wired truth. The fixture-level wiring + no-cross-feed
proofs live in test_fixture_borrowers_lp379b.py.)

And the non-drift facts the ticket predicted but the gate of record refuted are pinned too: every filled
label survives verbatim (nothing rewritten — LP-340 kept the entity-suffix strip in IN-5's RULE, so the
employer_normalized TAG still reports the stated full name, and Geet's goldens are NOT in conflict).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.verification.eval.lf6t3n_fixture import build_lf6t3n_snapshot
from app.verification.eval.worksheet import (
    build_worksheet,
    compute_capacity,
    load_golden,
    write_worksheets,
)
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

_STABILITY = {
    "income.has_2yr_history",
    "income.is_declining",
    "income.same_line_of_work",
    "income.continuance_3yr",
}


def _snap() -> Snapshot:
    return build_lf6t3n_snapshot()


def _f(v: str) -> Field:
    return Field.present(v, source=FieldSource.EXTRACTED)


def _wired_snapshot() -> tuple[Snapshot, str, str]:
    """A 2-borrower snapshot with W-2s attributed by belongs_to (the wiring the fixture lacks)."""
    a, b = uuid4(), uuid4()

    def w2(cid: str, owner: object, yr: str, emp: str) -> DocumentEntry:
        return DocumentEntry(
            content_id=cid,
            document_type="w2",
            belongs_to=(BorrowerRef(borrower_id=owner, name="X"),),
            fields={"tax_year": _f(yr), "employer_name": _f(emp)},
        )

    snap = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 19, tzinfo=UTC),
        documents=DocumentsSection.present(
            [
                w2("a24", a, "2024", "Acme"),
                w2("a25", a, "2025", "Acme"),
                w2("b25", b, "2025", "Globex"),
            ]
        ),
        mismo=MismoSection.present(
            {"borrower.1.borrower_id": _f(str(a)), "borrower.2.borrower_id": _f(str(b))}
        ),
        tags=TagsSection.present({}),
    )
    return snap, str(a), str(b)


# --------------------------------------------------------------------------- #
# income_stability is a BORROWER tag now — the stale per-document rows are gone
# --------------------------------------------------------------------------- #
def test_income_stability_is_reported_as_a_borrower_subject() -> None:
    caps = {c.tag_id: c for c in compute_capacity(_snap())}
    for t in _STABILITY:
        assert caps[t].subject_kind == "borrower"  # LP-385 — no longer "document"


def test_income_stability_is_labelable_per_borrower_on_the_wired_fixture() -> None:
    # UPDATED BY LP-379-B: this test previously asserted the borrower-LESS fiction (0 rows / no_subject) —
    # correct for LP-379-A, when the fixture had no wired borrowers. LP-379-B wired the 2 DB borrowers into
    # the fixture, so income_stability now materializes per-BORROWER (the true state). The 32 stale
    # per-DOCUMENT rows are still gone; what returns is 8 per-borrower rows (2 borrowers x 4 tags).
    rows = [r for r in build_worksheet(_snap()) if r.tag_id in _STABILITY]
    assert len(rows) == 8 and {r.subject_kind for r in rows} == {"borrower"}
    caps = {c.tag_id: c for c in compute_capacity(_snap())}
    assert all(caps[t].capacity == 2 and caps[t].status == "labelable" for t in _STABILITY)


def test_income_stability_rows_are_per_borrower_when_borrowers_are_wired() -> None:
    # Granularity matches LP-385's producer: one row PER BORROWER per tag, keyed by borrower_id (not a
    # document content_id), each carrying ONLY that borrower's income docs (no cross-feed).
    snap, a, b = _wired_snapshot()
    rows = [r for r in build_worksheet(snap) if r.tag_id in _STABILITY]
    assert len(rows) == 8  # 4 tags x 2 borrowers
    assert all(r.subject_kind == "borrower" for r in rows)
    assert {r.subject_id for r in rows} == {a, b}  # keyed by borrower_id, not a document id
    a_ctx = " ".join(r.context for r in rows if r.subject_id == a)
    b_ctx = " ".join(r.context for r in rows if r.subject_id == b)
    assert "Acme" in a_ctx and "Globex" not in a_ctx  # A sees only A's employer
    assert "Globex" in b_ctx and "Acme" not in b_ctx  # B sees only B's employer


# --------------------------------------------------------------------------- #
# Every row targets a materializing tag — and nothing filled is rewritten
# --------------------------------------------------------------------------- #
def test_every_worksheet_row_targets_a_tag_with_capacity() -> None:
    # No row for a tag/doc-type that does not materialize on LF-6T3N today (income_stability being the tag
    # this ticket removes from the labelable set).
    snap = _snap()
    caps = {c.tag_id: c for c in compute_capacity(snap)}
    for r in build_worksheet(snap):
        assert caps[r.tag_id].capacity > 0, f"row for non-materializing tag {r.tag_id}"


def test_filled_employer_normalized_golden_survives_verbatim(tmp_path) -> None:
    # LP-340 kept the entity-suffix strip in IN-5's RULE, so the TAG still reports the stated full name —
    # "Acme Logistics Inc" is what the tag produces, NOT a convention conflict. Regeneration must preserve
    # it verbatim (never rewrite it to a stripped "Acme Logistics").
    import csv
    import io

    snap = _snap()
    write_worksheets(snap, tmp_path)
    mech = tmp_path / "lf6t3n-labels-mechanical.csv"
    reader = list(csv.DictReader(io.StringIO(mech.read_text())))
    target = next(r for r in reader if r["tag_id"] == "income.employer_normalized")
    target["golden_label"] = "Acme Logistics Inc"
    key = (target["tag_id"], target["subject_id"])
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=reader[0].keys(), lineterminator="\n")
    w.writeheader()
    w.writerows(reader)
    mech.write_text(buf.getvalue())

    write_worksheets(snap, tmp_path)  # regenerate
    assert load_golden(mech.read_text()).get(key) == "Acme Logistics Inc"  # verbatim, not stripped


# --------------------------------------------------------------------------- #
# Equivalence — this ticket touches only the worksheets + generator metadata
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


def test_generation_stays_deterministic_and_keyless() -> None:
    from app.verification.eval.worksheet import render_csv

    assert render_csv(build_worksheet(_snap())) == render_csv(build_worksheet(_snap()))
