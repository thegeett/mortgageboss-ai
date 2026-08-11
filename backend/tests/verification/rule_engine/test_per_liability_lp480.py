"""LP-480 — the per-liability enumerator: UNION, NO MERGE (ADR-374).

Liabilities are described by TWO sources for the same real debts — MISMO ``liability.{n}.*`` facts (what the
borrower DECLARED) and credit-report ``tradelines`` rows (what the bureau REPORTED). This enumerator unions
them and never merges, because a merge destroys exactly the signal CR-4 exists to detect: an undisclosed
tradeline IS a debt in one source and absent from the other.

These pin the properties the ticket requires: enumeration over both sources with a ``liability.source``
marker; content-derived subject ids that are deterministic and order-independent (never the positional MISMO
index); no guess-merge on the adversarial cases (same creditor, null holder on both sides, byte-identical
rows); an unresolvable member surfaced as its OWN subject with a marker rather than dropped; absent tags
yielding subjects with only the structural marker so the gate reports ``couldnt_check`` instead of the rule
vanishing; and the drift guard.

⚠️ The two sources NEVER co-occur anywhere in the repo (LP-480 Phase A), so every CROSS-SOURCE assertion here
is against a CONSTRUCTED fixture. The single-source tradeline assertions run on the real stored extractions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.rule_engine.enumerators import (
    LIABILITY_SOURCE_TAG,
    LIABILITY_UNRESOLVED_TAG,
    enumerate_subjects,
    is_known_enumerator,
)
from app.verification.rule_engine.gate import GateStatus, evaluate_gate
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    ListRow,
    MismoSection,
    Snapshot,
    TagsSection,
)

_KEY = "per_liability"


def _mismo_facts(liabilities: list[tuple[str | None, ...]]) -> dict[str, Field]:
    """``[(type, holder, monthly_payment, unpaid_balance), …]`` → the projected ``liability.{n}.*`` facts."""
    out: dict[str, Field] = {}
    for index, (ltype, holder, payment, balance) in enumerate(liabilities, start=1):
        for name, value in (
            ("type", ltype),
            ("holder_name", holder),
            ("monthly_payment", payment),
            ("unpaid_balance", balance),
        ):
            if value is not None:
                out[f"liability.{index}.{name}"] = Field.present(value, source=FieldSource.PARSED)
    return out


def _tradeline_doc(content_id: str, rows: list[dict[str, str]]) -> DocumentEntry:
    """A credit report carrying tradeline rows that already have LP-479 row ids."""
    return DocumentEntry(
        content_id=content_id,
        document_type="credit_report",
        belongs_to=None,
        fields={},
        lists={
            "tradelines": tuple(
                ListRow(
                    fields={
                        k: Field.present(v, source=FieldSource.EXTRACTED) for k, v in row.items()
                    },
                    row_id=f"{content_id}-row{i}",
                )
                for i, row in enumerate(rows)
            )
        },
    )


def _snapshot(
    *,
    documents: list[DocumentEntry] | None = None,
    liabilities: list[tuple[str | None, ...]] | None = None,
    tags_absent: bool = False,
) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        documents=DocumentsSection.present(documents or []),
        mismo=MismoSection.present(_mismo_facts(liabilities or [])),
        tags=TagsSection.missing() if tags_absent else TagsSection.present({}),
    )


def _source(tags: object) -> str | None:
    tag = dict(tags).get(LIABILITY_SOURCE_TAG)  # type: ignore[arg-type]
    return None if tag is None else str(tag.value)


# --------------------------------------------------------------------------- #
# Union, no merge — the ADR-374 core
# --------------------------------------------------------------------------- #
def test_unions_both_sources_and_marks_each_with_its_source() -> None:
    doc = _tradeline_doc("cr1", [{"creditor_name": "PENNYMAC", "balance": "582417"}])
    subjects = enumerate_subjects(
        _KEY,
        _snapshot(documents=[doc], liabilities=[("MortgageLoan", "PENNYMAC", "4263", "582417")]),
    )
    assert len(subjects) == 2  # ONE per source — the same real debt, never merged
    assert sorted(_source(t) for _, t in subjects) == ["credit_report_reported", "mismo_stated"]


def test_the_same_debt_in_both_sources_stays_two_subjects() -> None:
    """⚠️ The union DELIBERATELY double-lists a matched debt: CR-4's signal is the difference between the
    two lists, so a summing rule must filter on ``liability.source`` (ADR-374), not sum every subject."""
    same = {"creditor_name": "WFBNA AUTO", "monthly_payment": "914", "balance": "25212"}
    subjects = enumerate_subjects(
        _KEY,
        _snapshot(
            documents=[_tradeline_doc("cr1", [same])],
            liabilities=[("Installment", "WFBNA AUTO", "914", "25212")],
        ),
    )
    assert len({sid for sid, _ in subjects}) == 2


def test_no_credit_report_yields_only_stated_liabilities() -> None:
    subjects = enumerate_subjects(
        _KEY, _snapshot(liabilities=[("Installment", "WFBNA AUTO", "914", "25212")])
    )
    assert [_source(t) for _, t in subjects] == ["mismo_stated"]


def test_no_liabilities_and_no_credit_report_yields_no_subjects() -> None:
    assert enumerate_subjects(_KEY, _snapshot()) == []


# --------------------------------------------------------------------------- #
# No guess-merge — the adversarial cases
# --------------------------------------------------------------------------- #
def test_same_creditor_different_amounts_stay_separate() -> None:
    subjects = enumerate_subjects(
        _KEY,
        _snapshot(
            liabilities=[
                ("Installment", "SETOYOTA FIN DBA OF WO", "500", "10000"),
                ("Installment", "SETOYOTA FIN DBA OF WO", "700", "20000"),
            ]
        ),
    )
    assert len({sid for sid, _ in subjects}) == 2


def test_null_holder_on_both_sides_stays_separate_and_is_flagged() -> None:
    """The ``_per_account`` contract: an unidentifiable member is its own subject + a marker — never
    dropped, never merged into its equally-anonymous neighbour."""
    subjects = enumerate_subjects(
        _KEY,
        _snapshot(
            liabilities=[
                ("Installment", None, "500", "10000"),
                ("Installment", None, "700", "20000"),
            ]
        ),
    )
    assert len({sid for sid, _ in subjects}) == 2
    assert all(LIABILITY_UNRESOLVED_TAG in dict(tags) for _, tags in subjects)


def test_byte_identical_rows_still_get_distinct_ids() -> None:
    """Two indistinguishable stated liabilities are separated by the occurrence tiebreak, not merged."""
    row = ("Installment", None, "500", "10000")
    subjects = enumerate_subjects(_KEY, _snapshot(liabilities=[row, row]))
    assert len({sid for sid, _ in subjects}) == 2


def test_a_resolvable_liability_is_not_flagged_unresolved() -> None:
    subjects = enumerate_subjects(
        _KEY, _snapshot(liabilities=[("Installment", "WFBNA AUTO", "914", "25212")])
    )
    assert LIABILITY_UNRESOLVED_TAG not in dict(subjects[0][1])


# --------------------------------------------------------------------------- #
# Identity: content-derived, never the positional MISMO index
# --------------------------------------------------------------------------- #
def test_ids_are_deterministic_and_order_independent() -> None:
    liabilities = [
        ("MortgageLoan", "FAY SERVICING LLC", "3119", "405282"),
        ("Installment", "WFBNA AUTO", "914", "25212"),
        ("Revolving", "CITICARDS CBNA", "50", "1200"),
    ]
    first = [sid for sid, _ in enumerate_subjects(_KEY, _snapshot(liabilities=liabilities))]
    again = [sid for sid, _ in enumerate_subjects(_KEY, _snapshot(liabilities=liabilities))]
    reversed_ = [
        sid
        for sid, _ in enumerate_subjects(_KEY, _snapshot(liabilities=list(reversed(liabilities))))
    ]
    assert first == again  # deterministic
    assert set(first) == set(reversed_)  # content-derived: reordering does not change the ids


def test_tradeline_subject_id_is_the_lp479_row_id() -> None:
    doc = _tradeline_doc("cr1", [{"creditor_name": "PENNYMAC"}, {"creditor_name": "MAZDA FS"}])
    subjects = enumerate_subjects(_KEY, _snapshot(documents=[doc]))
    assert [sid for sid, _ in subjects] == ["cr1-row0", "cr1-row1"]


def test_a_tradeline_without_a_row_id_is_not_given_a_positional_one() -> None:
    """``stable_row_id`` off ⇒ no durable identity ⇒ no subject, rather than an id derived from position."""
    doc = DocumentEntry(
        content_id="cr1",
        document_type="credit_report",
        belongs_to=None,
        fields={},
        lists={
            "tradelines": (
                ListRow(fields={"creditor_name": Field.present("X", source=FieldSource.EXTRACTED)}),
            )
        },
    )
    assert enumerate_subjects(_KEY, _snapshot(documents=[doc])) == []


def test_tradelines_are_scoped_to_credit_reports() -> None:
    """A list name is not a unique key (the LP-453 review) — another document type's ``tradelines`` list
    must not become a liability subject."""
    other = _tradeline_doc("bs1", [{"creditor_name": "X"}]).model_copy(
        update={"document_type": "bank_statement"}
    )
    assert enumerate_subjects(_KEY, _snapshot(documents=[other])) == []


# --------------------------------------------------------------------------- #
# Absent tags → empty map → couldnt_check (never a vanishing rule)
# --------------------------------------------------------------------------- #
def test_absent_tags_still_yield_subjects_carrying_only_the_marker() -> None:
    doc = _tradeline_doc("cr1", [{"creditor_name": "PENNYMAC"}])
    subjects = enumerate_subjects(_KEY, _snapshot(documents=[doc], tags_absent=True))
    assert len(subjects) == 1  # the rule does NOT silently vanish
    assert set(dict(subjects[0][1])) == {LIABILITY_SOURCE_TAG}


def test_a_missing_load_bearing_tag_gates_to_couldnt_check() -> None:
    doc = _tradeline_doc("cr1", [{"creditor_name": "PENNYMAC"}])
    _, tags = enumerate_subjects(_KEY, _snapshot(documents=[doc], tags_absent=True))[0]
    result = evaluate_gate(
        {"liab.dti_payment": dict(tags).get("liab.dti_payment")}, confidence_floor=None
    )
    assert result.status is GateStatus.COULDNT_CHECK


# --------------------------------------------------------------------------- #
# The drift guard
# --------------------------------------------------------------------------- #
def test_the_enumerator_is_registered() -> None:
    assert is_known_enumerator(_KEY)


def test_an_unregistered_key_raises() -> None:
    assert not is_known_enumerator("per_liabilty")
    with pytest.raises(KeyError):
        enumerate_subjects("per_liabilty", _snapshot())
