"""LP-483 B1/B2 — the ``liability`` production subject family, and the first produced ``liab.*`` tag.

⚠️ WHY THIS FAMILY MATTERS BEYOND CR-1. ``KNOWN_SUBJECTS`` held only transaction/document/loan/borrower,
so a tag declared ``entity: liability`` had nowhere to be produced — which is why ALL 14 ``liab.*`` tags
sat in ``fact_tags.csv`` declared and unproduced. This family is the missing floor under the whole credit
tag vocabulary, not CR-1 overhead.

These pin: the family is registered; its subject ids are IDENTICAL to what the rule-engine's
``per_liability`` emits (a tag under a different id is a tag no rule can read); the alias map resolves a
canonical name to each source's own column and yields an ABSENT tag for a name a source does not carry;
and ``liab.monthly_payment`` materializes from both sources.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.rule_engine.enumerators import _per_liability, liability_rows
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    ListRow,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.tag_materialization.declarations import KNOWN_SUBJECTS
from app.verification.tag_materialization.producer import materialize_tags
from app.verification.tag_materialization.subjects import subject_type

pytestmark = pytest.mark.anyio


def _mismo(liabilities: list[tuple[str | None, ...]]) -> dict[str, Field]:
    out: dict[str, Field] = {}
    for i, (ltype, holder, payment, balance) in enumerate(liabilities, start=1):
        for name, value in (
            ("type", ltype),
            ("holder_name", holder),
            ("monthly_payment", payment),
            ("unpaid_balance", balance),
        ):
            if value is not None:
                out[f"liability.{i}.{name}"] = Field.present(value, source=FieldSource.PARSED)
    return out


def _tradeline_doc(rows: list[dict[str, str]]) -> DocumentEntry:
    return DocumentEntry(
        content_id="cr1",
        document_type="credit_report",
        belongs_to=None,
        fields={},
        lists={
            "tradelines": tuple(
                ListRow(
                    fields={
                        k: Field.present(v, source=FieldSource.EXTRACTED) for k, v in row.items()
                    },
                    row_id=f"cr1-row{i}",
                )
                for i, row in enumerate(rows)
            )
        },
    )


def _snapshot(
    *,
    documents: list[DocumentEntry] | None = None,
    liabilities: list[tuple[str | None, ...]] | None = None,
) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        documents=DocumentsSection.present(documents or []),
        mismo=MismoSection.present(_mismo(liabilities or [])),
        tags=TagsSection.present({}),
    )


def test_liability_is_a_known_subject() -> None:
    assert "liability" in KNOWN_SUBJECTS
    assert subject_type("liability") is not None


def test_subject_ids_match_the_rule_engine_enumerator_exactly() -> None:
    """⚠️ THE CONTRACT. A production subject id that differs from ``per_liability``'s would materialize a
    tag under an id no rule ever reads — silently, forever. Both derive from ``liability_rows``."""
    snap = _snapshot(
        documents=[_tradeline_doc([{"creditor_name": "PENNYMAC", "monthly_payment": "4263"}])],
        liabilities=[("Installment", "WFBNA AUTO", "914", "25212")],
    )
    produced = [sid for sid, _ in subject_type("liability").enumerate(snap)]
    consumed = [sid for sid, _ in _per_liability(snap)]
    assert produced == consumed


def test_read_field_resolves_each_source_own_column() -> None:
    snap = _snapshot(
        documents=[_tradeline_doc([{"account_type": "REV", "monthly_payment": "41"}])],
        liabilities=[("MortgageLoan", "FAY SERVICING", "3119", "405282")],
    )
    st = subject_type("liability")
    by_source = {row.source: row for row in liability_rows(snap)}
    tradeline = by_source["credit_report_reported"]
    stated = by_source["mismo_stated"]
    # the canonical name resolves to a DIFFERENT column per source
    assert st.read_field(tradeline, "account_type").value == "REV"
    assert st.read_field(stated, "account_type").value == "MortgageLoan"
    assert st.read_field(stated, "creditor_name").value == "FAY SERVICING"
    assert st.read_field(stated, "balance").value == "405282"


def test_a_name_a_source_does_not_carry_yields_no_field() -> None:
    """Fail-closed: MISMO has no dispute column, so the read is None → an ABSENT tag, never a default."""
    snap = _snapshot(liabilities=[("Installment", "WFBNA AUTO", "914", "25212")])
    stated = liability_rows(snap)[0]
    assert subject_type("liability").read_field(stated, "is_disputed") is None
    assert subject_type("liability").read_field(stated, "not_a_real_field") is None


async def test_monthly_payment_materializes_from_both_sources() -> None:
    snap = _snapshot(
        documents=[_tradeline_doc([{"creditor_name": "PENNYMAC", "monthly_payment": "4263"}])],
        liabilities=[("Installment", "WFBNA AUTO", "914", "25212")],
    )
    tagged = await materialize_tags(snap, only_groups=frozenset())
    values = {
        sid: tags["liab.monthly_payment"].value
        for sid, tags in tagged.tags.by_subject.items()
        if "liab.monthly_payment" in tags
    }
    assert sorted(values.values()) == ["4263", "914"]


async def test_a_liability_without_a_payment_gets_no_tag() -> None:
    """Absent ≠ 0. A tradeline carrying no monthly payment produces NO tag, never a fabricated zero."""
    snap = _snapshot(documents=[_tradeline_doc([{"creditor_name": "PENNYMAC"}])])
    tagged = await materialize_tags(snap, only_groups=frozenset())
    assert all("liab.monthly_payment" not in tags for tags in tagged.tags.by_subject.values())
