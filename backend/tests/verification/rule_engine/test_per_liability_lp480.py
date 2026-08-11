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
    per_liability_source_is_degraded,
)
from app.verification.rule_engine.gate import GateStatus, evaluate_gate
from app.verification.snapshot.content_id import LIABILITY_PREFIX
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
    """``stable_row_id`` off ⇒ no LP-479 id ⇒ a CONTENT-derived id, never one derived from position.

    ⚠️ This assertion CHANGED in the LP-480 review. It originally required no subject at all — the
    "never positional" guarantee it exists for is preserved and asserted below, but the silent drop it
    also encoded contradicted the enumerator's own fail-closed contract ("never dropped, never merged"):
    it turned an unreadable tradeline into "nothing found" rather than ``couldnt_check``. See
    ``test_a_tradeline_without_a_row_id_becomes_its_own_unresolved_subject``.
    """
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
    [(subject_id, _)] = enumerate_subjects(_KEY, _snapshot(documents=[doc]))
    assert subject_id.startswith(LIABILITY_PREFIX), "content-derived"
    assert "row0" not in subject_id and "cr1" not in subject_id, (
        "never positional, never doc-scoped"
    )


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


# --------------------------------------------------------------------------- #
# LP-480 review fixes — the retire guard, the idless row, and the recorded limitations
# --------------------------------------------------------------------------- #
def test_a_tradeline_without_a_row_id_becomes_its_own_unresolved_subject() -> None:
    """⚠️ Reported finding: it was ``continue``d away silently, so a CR rule would report "nothing
    found" instead of ``couldnt_check`` — a false negative, and (with the retire guard) a false close."""
    doc = DocumentEntry(
        content_id="cr1",
        document_type="credit_report",
        belongs_to=None,
        fields={},
        lists={
            "tradelines": (
                ListRow(
                    fields={
                        "creditor_name": Field.present("PENNYMAC", source=FieldSource.EXTRACTED)
                    },
                    row_id=None,  # an older snapshot, or stable_row_id off
                ),
            )
        },
    )
    subjects = enumerate_subjects(_KEY, _snapshot(documents=[doc]))
    assert len(subjects) == 1, "the row must not be dropped"
    subject_id, tags = subjects[0]
    assert subject_id.startswith("lia")  # content-derived, never positional
    assert _source(tags) == "credit_report_reported"
    assert LIABILITY_UNRESOLVED_TAG in dict(tags)


def test_two_idless_rows_with_identical_content_stay_two_subjects() -> None:
    """The occurrence tiebreak keeps them distinct — an idless row is never merged into its twin."""
    row = ListRow(
        fields={"creditor_name": Field.present("SETOYOTA", source=FieldSource.EXTRACTED)},
        row_id=None,
    )
    doc = DocumentEntry(
        content_id="cr1",
        document_type="credit_report",
        belongs_to=None,
        fields={},
        lists={"tradelines": (row, row)},
    )
    subjects = enumerate_subjects(_KEY, _snapshot(documents=[doc]))
    assert len({sid for sid, _ in subjects}) == 2


def test_per_liability_is_document_derived_for_the_retire_guard() -> None:
    """⚠️ Reported finding: absent from ``_DOCUMENT_DERIVED_ENUMERATIONS``, a degraded run would have
    retired every prior tradeline finding as "no longer applies" — the false-close that set prevents."""
    from app.services.verification_run import _DOCUMENT_DERIVED_ENUMERATIONS

    assert _KEY in _DOCUMENT_DERIVED_ENUMERATIONS


def test_the_credit_report_leg_is_degraded_when_documents_are_absent() -> None:
    snapshot = _snapshot().model_copy(update={"documents": DocumentsSection.missing()})
    assert per_liability_source_is_degraded(snapshot)


def test_a_file_with_no_credit_report_is_not_degraded() -> None:
    """An honest "nothing reported" — not a build failure. Retiring here is correct."""
    assert not per_liability_source_is_degraded(
        _snapshot(liabilities=[("Auto", "WFBNA", "914", "1")])
    )


def test_a_credit_report_that_contributed_no_rows_is_degraded() -> None:
    """⚠️ THE MIXED-SOURCE HOLE the review found: the union is NON-EMPTY (MISMO supplied a subject), so
    the plain "zero subjects" heuristic passes while the whole credit-report half is missing."""
    empty_report = DocumentEntry(
        content_id="cr1", document_type="credit_report", belongs_to=None, fields={}, lists={}
    )
    snapshot = _snapshot(
        documents=[empty_report], liabilities=[("MortgageLoan", "PENNYMAC", "4263", "582417")]
    )
    assert enumerate_subjects(_KEY, snapshot), (
        "the union is non-empty — the old heuristic sees health"
    )
    assert per_liability_source_is_degraded(snapshot), "but the document-derived source IS degraded"


def test_a_healthy_credit_report_is_not_degraded() -> None:
    doc = _tradeline_doc("cr1", [{"creditor_name": "PENNYMAC"}])
    assert not per_liability_source_is_degraded(_snapshot(documents=[doc]))


def test_the_mismo_subject_id_moves_when_a_balance_moves() -> None:
    """⚠️ RECORDED CONSEQUENCE, not desired behaviour (see ``_per_liability``'s docstring): the id hashes
    mutable amounts, so a re-imported 1003 with a moved balance mints a NEW subject — LP-322 retires the
    prior finding and duplicates it, losing any processor resolution. Pinned so the day someone changes
    the identity fields, this test tells them what it fixes."""
    before = enumerate_subjects(_KEY, _snapshot(liabilities=[("Auto", "WFBNA", "914", "25212")]))
    after = enumerate_subjects(_KEY, _snapshot(liabilities=[("Auto", "WFBNA", "914", "24800")]))
    assert before[0][0] != after[0][0]


def test_two_credit_reports_double_list_the_same_debt() -> None:
    """⚠️ RECORDED LIMITATION: no dedup WITHIN a source. ``liability.source`` does not protect a summing
    rule here — both subjects are ``credit_report_reported``."""
    row = {"creditor_name": "PENNYMAC", "balance": "582417"}
    subjects = enumerate_subjects(
        _KEY, _snapshot(documents=[_tradeline_doc("cr1", [row]), _tradeline_doc("cr2", [row])])
    )
    assert len(subjects) == 2
    assert {_source(t) for _, t in subjects} == {"credit_report_reported"}
