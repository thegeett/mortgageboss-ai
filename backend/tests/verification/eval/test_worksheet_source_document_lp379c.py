"""LP-379-C — every calibration worksheet row names its SOURCE DOCUMENT (the Document tab's real filename).

A row's subject_id is a content-id; its context is date/amount/direction/description — but not WHICH document.
Across multiple bank statements and 2 borrowers, verifying a label meant hunting for the source. This adds a
`source_document` column carrying the REAL `original_filename` (what the Document tab shows), keyed by
content-id via the LP-379-C map + reusing LP-377-B's `resolve_subject_label`: a transaction names its PARENT
bank statement, a document names itself, a borrower row lists its income documents — never a hash. These pin
that, plus: the column is purely additive (row counts and every filled golden unchanged), the real map
overrides the field-derived fallback, and generation stays deterministic + keyless.
"""

from __future__ import annotations

import csv
import io
import re

from app.verification.eval.lf6t3n_fixture import (
    _B1_ID,
    LF6T3N_DOCUMENT_FILENAMES,
    build_lf6t3n_snapshot,
)
from app.verification.eval.worksheet import (
    build_worksheet,
    load_golden,
    render_csv,
    write_worksheets,
)
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS

_HASH = re.compile(
    r"^(txn|doc)[0-9a-f]{6,}$"
)  # a bare content-id / hash — never allowed in the column


def _snap():
    return build_lf6t3n_snapshot()


def _rows():
    return build_worksheet(_snap(), document_filenames=LF6T3N_DOCUMENT_FILENAMES)


# --------------------------------------------------------------------------- #
# Every row names a real source filename — never a hash
# --------------------------------------------------------------------------- #
def test_every_row_has_a_non_hash_source_document() -> None:
    rows = _rows()
    assert rows and all(r.source_document.strip() for r in rows)
    assert not [r for r in rows if _HASH.match(r.source_document)]


def test_transaction_row_names_its_parent_bank_statement_filename() -> None:
    # The subject is a transaction, but the SOURCE is its parent statement's REAL filename — resolved via
    # the PARENT document's key, not the resolver's txn/deposit branch. So it is the actual ".pdf" the
    # labeler opens (e.g. "BofA checking April.pdf"), never "Deposit of $… on …" and never the txn hash.
    txn_rows = [r for r in _rows() if r.subject_kind == "transaction"]
    assert txn_rows
    for r in txn_rows:
        assert r.source_document.endswith(".pdf")
        assert "Deposit of" not in r.source_document
    # every transaction source is a real DB bank-statement filename
    bank_files = {v for k, v in LF6T3N_DOCUMENT_FILENAMES.items() if k.startswith("doc")}
    assert {r.source_document for r in txn_rows} <= bank_files
    assert (
        len({r.source_document for r in txn_rows}) >= 2
    )  # the statements a labeler had to hunt across


def test_document_and_borrower_rows_name_their_real_source() -> None:
    rows = _rows()
    dl = next(r for r in rows if r.tag_id == "id.name_normalized")
    assert dl.source_document == "DL Akash Patel.pdf"  # the real Document-tab filename
    ps = next(r for r in rows if r.tag_id == "income.documented_monthly")
    assert ps.source_document.endswith(".pdf")
    # a borrower (income_stability) row lists the borrower's real income-document filenames (what to open)
    b1 = next(r for r in rows if r.subject_kind == "borrower" and r.subject_id == str(_B1_ID))
    assert (
        "Akash Pay stub 1.pdf" in b1.source_document
        and "Akash W2 BofA 2025.pdf" in b1.source_document
    )
    assert all(part.strip().endswith(".pdf") for part in b1.source_document.split(";"))


def test_real_map_overrides_the_field_descriptor_fallback() -> None:
    # WITHOUT the map, a legible field-derived descriptor (never a hash); WITH it, the real filename.
    fallback = next(r for r in build_worksheet(_snap()) if r.tag_id == "id.name_normalized")
    real = next(r for r in _rows() if r.tag_id == "id.name_normalized")
    assert fallback.source_document.startswith("Driver's license:")  # descriptor fallback
    assert real.source_document == "DL Akash Patel.pdf"  # real map wins


# --------------------------------------------------------------------------- #
# Purely additive — labels preserved, counts unchanged, column present
# --------------------------------------------------------------------------- #
def test_column_is_present_and_additive(tmp_path) -> None:
    snap = _snap()
    write_worksheets(snap, tmp_path)
    for name in ("mechanical", "judgment"):
        header = next(csv.reader(io.StringIO((tmp_path / f"lf6t3n-labels-{name}.csv").read_text())))
        assert "source_document" in header


def test_filled_labels_and_row_count_survive_the_new_column(tmp_path) -> None:
    snap = _snap()
    write_worksheets(snap, tmp_path)
    mech = tmp_path / "lf6t3n-labels-mechanical.csv"
    reader = list(csv.DictReader(io.StringIO(mech.read_text())))
    n_before = len(reader)
    reader[0]["golden_label"] = "6500"
    key = (reader[0]["tag_id"], reader[0]["subject_id"])
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=reader[0].keys(), lineterminator="\n")
    w.writeheader()
    w.writerows(reader)
    mech.write_text(buf.getvalue())

    write_worksheets(snap, tmp_path)  # regenerate
    after = list(csv.DictReader(io.StringIO(mech.read_text())))
    assert len(after) == n_before  # the column added rows to nothing
    assert load_golden(mech.read_text()).get(key) == "6500"  # golden survived
    assert all(r["source_document"].strip() for r in after)  # and every row got a source


# --------------------------------------------------------------------------- #
# Deterministic / keyless / equivalence
# --------------------------------------------------------------------------- #
def test_generation_stays_deterministic_and_keyless() -> None:
    assert render_csv(build_worksheet(_snap())) == render_csv(build_worksheet(_snap()))


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
        "AS-2",
        "AS-12",
        "IN-3",
    )
