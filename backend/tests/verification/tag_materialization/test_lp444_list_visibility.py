"""LP-444 — generic lists become visible to an AI context, OPT-IN, capped (per-group), truncation-marked,
PII-scrubbed; a borrower context can also opt into the app's file-level stated liabilities (the CR-4
comparison set).

The list-capture bridge (LP-443) made list data reach the snapshot, but the AI context builder predated
lists so no reasoner could see them. This pins the visibility mechanism: (1) a group that does NOT declare
`include_lists`/`include_stated_liabilities` gets a BYTE-IDENTICAL context (no group sees anything new);
(2) an opted-in document/borrower context serialises a document's generic lists — capped at the group's
`list_row_cap` (default 50) with a truncation MARKER (so an unmatched item is "unknown", never a confirmed
absence), and every list-row value PII-scrubbed (list-row Fields are plain Fields — a raw identifier must
never reach a reasoner); (3) a borrower context opts into the file-level MISMO liabilities.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    ListRow,
    MismoSection,
    Snapshot,
)
from app.verification.tag_materialization.subjects import (
    ContextOptions,
    subject_type,
)

_E = FieldSource.EXTRACTED
_BID = "11111111-1111-1111-1111-111111111111"


def _f(v: str) -> Field:
    return Field.present(v, source=_E)


def _tradeline(i: int) -> ListRow:
    # account_number_masked deliberately carries a long raw-looking number to prove the scrub.
    return ListRow(
        fields={
            "creditor_name": _f(f"CREDITOR {i}"),
            "account_number_masked": _f(f"4471{i:09d}"),
            "balance": _f(str(i * 100)),
        }
    )


def _snapshot(n_tradelines: int, *, n_liabilities: int = 0) -> Snapshot:
    rows = tuple(_tradeline(i) for i in range(1, n_tradelines + 1))
    cr = DocumentEntry(
        content_id="docCR",
        document_type="credit_report",
        belongs_to=(BorrowerRef(borrower_id=_BID, name="J. Rivera"),),
        fields={"report_date": _f("2026-05-01")},
        lists={"tradelines": rows},
    )
    mismo: dict[str, Field] = {
        "borrower.1.borrower_id": _f(_BID),
        "borrower.1.first_name": _f("Jordan"),
    }
    for k in range(1, n_liabilities + 1):
        mismo[f"liability.{k}.creditor_name"] = _f(f"CREDITOR {k}")
        mismo[f"liability.{k}.monthly_payment"] = _f(str(k * 10))
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime.now(UTC),
        documents=DocumentsSection.present([cr]),
        mismo=MismoSection.present(mismo),
    )


def _borrower_ctx(snapshot: Snapshot, opts: ContextOptions) -> dict:
    st = subject_type("borrower")
    _sid, subj = st.enumerate(snapshot)[0]
    return st.build_context(subj, None, opts)


# --------------------------------------------------------------------------- #
# Equivalence: the default (opt-out) context is byte-identical
# --------------------------------------------------------------------------- #
def test_opt_out_context_has_no_lists_or_liabilities() -> None:
    ctx = _borrower_ctx(_snapshot(3, n_liabilities=2), ContextOptions())
    assert all("lists" not in doc for doc in ctx["documents"])
    assert "stated_liabilities" not in ctx


def test_opt_out_borrower_context_is_byte_identical() -> None:
    import json

    snap = _snapshot(3, n_liabilities=2)
    before = json.dumps(_borrower_ctx(snap, ContextOptions()), sort_keys=True)
    _ = _borrower_ctx(snap, ContextOptions(include_lists=True, include_stated_liabilities=True))
    after = json.dumps(_borrower_ctx(snap, ContextOptions()), sort_keys=True)
    assert before == after and "lists" not in before and "stated_liabilities" not in before


def test_document_context_opt_out_unchanged() -> None:
    entry = _snapshot(3).documents.entries[0]
    plain = subject_type("document").build_context(entry, None, ContextOptions())
    assert "lists" not in plain


# --------------------------------------------------------------------------- #
# Opt-in: lists serialised, PII-scrubbed, capped + marked (per-group cap)
# --------------------------------------------------------------------------- #
def test_opt_in_serialises_tradelines() -> None:
    ctx = _borrower_ctx(_snapshot(3), ContextOptions(include_lists=True))
    tl = ctx["documents"][0]["lists"]["tradelines"]
    assert len(tl["rows"]) == 3 and "truncated" not in tl
    assert tl["rows"][0]["creditor_name"] == "CREDITOR 1"


def test_list_row_pii_is_scrubbed() -> None:
    ctx = _borrower_ctx(_snapshot(1), ContextOptions(include_lists=True))
    row = ctx["documents"][0]["lists"]["tradelines"]["rows"][0]
    assert row["account_number_masked"] == "[redacted]"  # the long raw number scrubbed
    assert row["creditor_name"] == "CREDITOR 1"  # a non-identifier is kept


def test_truncation_marker_fires_over_the_default_cap() -> None:
    # 55 tradelines > the default cap (50) → the marker fires.
    ctx = _borrower_ctx(_snapshot(55), ContextOptions(include_lists=True))
    tl = ctx["documents"][0]["lists"]["tradelines"]
    assert tl["truncated"] is True and tl["shown"] == 50 and tl["total"] == 55
    assert len(tl["rows"]) == 50


def test_cap_is_per_group() -> None:
    # A group may raise/lower the cap; a lower cap truncates a list the default would have shown whole.
    ctx = _borrower_ctx(_snapshot(10), ContextOptions(include_lists=True, list_row_cap=5))
    tl = ctx["documents"][0]["lists"]["tradelines"]
    assert tl["truncated"] is True and tl["shown"] == 5 and tl["total"] == 10


def test_document_subject_also_opts_in() -> None:
    entry = _snapshot(2).documents.entries[0]
    ctx = subject_type("document").build_context(entry, None, ContextOptions(include_lists=True))
    assert "lists" in ctx and len(ctx["lists"]["tradelines"]["rows"]) == 2


# --------------------------------------------------------------------------- #
# The CR-4 comparison set: file-level stated liabilities, opt-in
# --------------------------------------------------------------------------- #
def test_stated_liabilities_opt_in() -> None:
    ctx = _borrower_ctx(
        _snapshot(3, n_liabilities=2), ContextOptions(include_stated_liabilities=True)
    )
    liabs = ctx["stated_liabilities"]
    assert len(liabs) == 2  # both file-level liability.{k}.* records surfaced
    assert liabs[0]["creditor_name"] == "CREDITOR 1" and liabs[0]["monthly_payment"] == "10"


def test_cr4_context_carries_both_tradelines_and_liabilities() -> None:
    # The Phase-A finding resolved: a borrower context can now carry BOTH inputs CR-4 compares.
    ctx = _borrower_ctx(
        _snapshot(3, n_liabilities=2),
        ContextOptions(include_lists=True, include_stated_liabilities=True),
    )
    assert "tradelines" in ctx["documents"][0]["lists"]
    assert len(ctx["stated_liabilities"]) == 2
