"""LP-437 — the generic nested-list mechanism (one build for all 66 lists).

These pin: a generic list round-trips extraction → snapshot → the reader with typed/coerced values +
provenance; each declarable helper (redact / derived / stable_row_id) incl. **derived's fail-closed
absent-on-unknown** (the forged-deposit discipline); the three LEGACY attributes are untouched and still
populate; ``SNAPSHOT_VERSION`` stays 4 and the golden fixture loads; and the registry is empty so every real
document gets ``lists={}`` (additive — no rule/tag/producer moved). The full-suite equivalence (36 live rules
identical, ACTIVE_RULE_IDS unchanged) is the existing verification tests staying green.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.verification.snapshot import documents_section as ds
from app.verification.snapshot.documents_section import (
    DerivedSpec,
    ListSpec,
    build_list_rows,
    build_transactions,
    finalize_lists,
    transaction_field_sets,
)
from app.verification.snapshot.fields import FieldSource
from app.verification.snapshot.model import (
    SNAPSHOT_VERSION,
    DocumentEntry,
    DocumentsSection,
    ListRow,
    Snapshot,
)
from app.verification.snapshot.traversal import all_list_rows

_SPEC = ListSpec(
    name="activity",
    fields=("date", "amount", "description"),
    derived=(
        DerivedSpec(
            field="direction",
            from_field="transaction_type",
            mapping={"deposit": "credit", "withdrawal": "debit"},
        ),
    ),
    redact=frozenset({"description"}),
    stable_row_id=True,
)

# LP-443: generic-list rows are stored BARE (the shipping bank_statement.transactions shape) —
# bare scalars + one page/snippet source per row, NOT {value}-wrapped. Row fields therefore carry
# no per-field confidence (honestly None); the source is EXTRACTED.
_EXTRACTED = {
    "activity": [
        {
            "date": "2026-05-01",
            "amount": "5000.00",
            "description": "PAYROLL ACCT 123456789 DEP",
            "transaction_type": "deposit",
            "source": {"page": 1, "snippet": "PAYROLL DEP"},
        },
        {
            "date": "2026-05-03",
            "amount": "200.00",
            "description": "COFFEE SHOP",
            "transaction_type": "mystery_type",  # UNKNOWN → direction must be ABSENT
        },
    ]
}


@pytest.fixture
def _registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(ds._LIST_SPECS, "demo_stmt", (_SPEC,))


def _rows(document_content_id: str = "docABC") -> tuple[ListRow, ...]:
    drafts = build_list_rows(
        _EXTRACTED, "demo_stmt", loan_file_id=UUID("00000000-0000-0000-0000-00000000f1e0")
    )
    return finalize_lists(drafts, document_content_id=document_content_id)["activity"]


# --------------------------------------------------------------------------- #
# Round-trip: extraction → snapshot → reader, typed with provenance
# --------------------------------------------------------------------------- #
def test_generic_list_round_trips_typed(_registered: None) -> None:
    rows = _rows()
    assert len(rows) == 2
    r1 = rows[0].fields
    assert r1["date"].value == "2026-05-01"
    # LP-443: a bare row carries no per-field confidence → honestly None (D4), never fabricated.
    assert r1["amount"].value == "5000.00" and r1["amount"].confidence is None
    assert r1["amount"].source is FieldSource.EXTRACTED


def test_round_trip_through_snapshot_json(_registered: None) -> None:
    entry = DocumentEntry(
        content_id="docABC", document_type="demo_stmt", lists={"activity": _rows()}
    )
    snap = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime.now(UTC),
        documents=DocumentsSection.present([entry]),
    )
    back = Snapshot.model_validate_json(snap.model_dump_json())
    read = all_list_rows(back, "activity")
    assert len(read) == 2
    assert read[0].fields["direction"].value == "credit"


# --------------------------------------------------------------------------- #
# The three declarable helpers
# --------------------------------------------------------------------------- #
def test_redact_masks_long_digit_run_keeps_signal(_registered: None) -> None:
    value = _rows()[0].fields["description"].value
    assert isinstance(value, str)
    assert "[redacted]" in value and "123456789" not in value
    assert "PAYROLL" in value and "DEP" in value  # sourcing signal kept


def test_derived_maps_known_value(_registered: None) -> None:
    direction = _rows()[0].fields["direction"]
    assert direction.value == "credit" and direction.source is FieldSource.DERIVED


def test_derived_is_fail_closed_absent_on_unknown(_registered: None) -> None:
    # THE forged-deposit discipline: an unmapped source value → ABSENT, never a fabricated value.
    direction = _rows()[1].fields["direction"]
    assert direction.absent is True
    assert direction.value is None and direction.source is None


def test_stable_row_id_is_stable_distinct_and_guard_safe(_registered: None) -> None:
    run1 = [r.row_id for r in _rows()]
    run2 = [r.row_id for r in _rows()]  # same input, fresh build
    assert run1 == run2  # stable across runs (content-derived, not positional)
    assert run1[0] != run1[1]  # distinct rows
    assert all(rid is not None and rid.startswith("lst") for rid in run1)  # guard-safe prefix


def test_row_id_is_none_when_not_declared(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = ListSpec(name="plain", fields=("a",), stable_row_id=False)
    monkeypatch.setitem(ds._LIST_SPECS, "plain_doc", (spec,))
    drafts = build_list_rows(
        {"plain": [{"a": "x"}]},
        "plain_doc",
        loan_file_id=UUID("00000000-0000-0000-0000-00000000f1e0"),
    )
    rows = finalize_lists(drafts, document_content_id="docX")["plain"]
    assert rows[0].row_id is None  # aggregate-only list → no per-row id


def test_all_absent_row_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = ListSpec(name="rows", fields=("a", "b"))
    monkeypatch.setitem(ds._LIST_SPECS, "d", (spec,))
    extracted = {"rows": [{"a": None, "b": None}, {"a": "kept"}]}
    drafts = build_list_rows(
        extracted, "d", loan_file_id=UUID("00000000-0000-0000-0000-00000000f1e0")
    )
    rows = finalize_lists(drafts, document_content_id="docX")["rows"]
    assert (
        len(rows) == 1 and rows[0].fields["a"].value == "kept"
    )  # empty row dropped, no hallucination


# --------------------------------------------------------------------------- #
# Coexistence + additive invariants (the STOP conditions)
# --------------------------------------------------------------------------- #
def test_only_wired_types_get_lists() -> None:
    # LP-443 wires generic lists for the batch (bank_statement + the generated list-bearing types);
    # a document type with NO wired list still gets {} (additive — nothing changes for it).
    assert "bank_statement" in ds._LIST_SPECS  # the first wired list
    assert (
        build_list_rows(
            {"transactions": [{"date": "x"}]},
            "w2",
            loan_file_id=UUID("00000000-0000-0000-0000-00000000f1e0"),
        )
        == {}
    )  # no wired list → {}
    assert "transactions" in build_list_rows(
        {"transactions": [{"date": "x"}]},
        "bank_statement",
        loan_file_id=UUID("00000000-0000-0000-0000-00000000f1e0"),
    )


def test_legacy_transactions_still_populate_and_coexist_with_lists(_registered: None) -> None:
    # The legacy bespoke path is byte-unchanged: transactions still reshape and populate, and an entry
    # can carry BOTH transactions and a generic list at once (coexist, never migrate).
    field_sets = transaction_field_sets(
        {
            "transactions": [
                {"date": "2026-05-01", "amount": "10.00", "transaction_type": "deposit"}
            ]
        },
        "bank_statement",
        loan_file_id=UUID("00000000-0000-0000-0000-00000000f1e0"),
    )
    txns = build_transactions(field_sets, document_content_id="docT")
    entry = DocumentEntry(
        content_id="docT",
        document_type="bank_statement",
        transactions=txns,
        lists={"activity": _rows()},
    )
    assert entry.transactions is not None and entry.transactions[0].direction.value == "credit"
    assert entry.lists["activity"][0].fields["direction"].value == "credit"


def test_snapshot_version_unchanged() -> None:
    assert (
        SNAPSHOT_VERSION == 4
    )  # additive, NO bump (the LP-421 precedent; a bump breaks the fixture)


def test_default_document_entry_has_empty_lists() -> None:
    entry = DocumentEntry(content_id="d", document_type="w2")
    assert entry.lists == {}  # present-empty default; transactions/schedule_c still default None
    assert entry.transactions is None and entry.schedule_c is None
