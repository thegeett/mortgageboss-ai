"""LP-407-2 — the cheap Bucket 2.5 sub-wave (TAGS ONLY): PC-2's inputs + the DT-2/DT-4 monthly producers.

The audit (LP-407-1) found Bucket 2.5's true wire-and-write count is ~2, and this ticket builds the tags for
PC-2 + DT-2/DT-4 (LP-407-3 writes the rules). DT-5 is deliberately NOT wired — "premium used vs binder"
resolves to the binder's annual_premium on BOTH sides (the DTI insurance line and housing.insurance_monthly
read the same field), a vacuous self-compare with no independent operand today (D1). These pin:

  * each producer's conversion + fail-closed unknown (absent≠0 — never a fabricated 0),
  * the HOA periodicity conversion across frequencies AND fail-closed on an unstated/unrecognized one (D3 —
    the tag must NOT assume a periodicity the way the DTI's _extracted_hoa_monthly defaults to monthly),
  * the SUBJECT of each tag == the LOAN subject its rule (PC-2/DT-2/DT-4) enumerates (anti-structural-death,
    the ID-5 class — D4), with contract.sales_price the document fact its loan promotion reads,
  * additivity — DT-5's ins.premium_annual is NOT declared; ACTIVE_RULE_IDS is unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    SnapshotField,
    TagsSection,
)
from app.verification.snapshot.tag import Tag
from app.verification.tag_materialization.declarations import load_declarations
from app.verification.tag_materialization.derived import (
    _housing_hoa_monthly,
    _housing_taxes_monthly,
    _loan_sales_price,
    produce_derived_tags,
)
from app.verification.tag_materialization.parsed import produce_parsed_tag
from app.verification.tag_materialization.subjects import subject_type

_LOAN = "loan"


# --------------------------------------------------------------------------- #
# Builders — snapshots carrying the REAL extractor field names
# --------------------------------------------------------------------------- #
def _f(v: str) -> Field:
    return Field.present(v, source=FieldSource.EXTRACTED)


def _doc(cid: str, dtype: str, **fields: str) -> DocumentEntry:
    return DocumentEntry(
        content_id=cid,
        document_type=dtype,
        belongs_to=None,
        fields={k: _f(v) for k, v in fields.items()},
    )


def _snapshot(docs: list[DocumentEntry], mismo: dict[str, SnapshotField] | None = None) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
        documents=DocumentsSection.present(docs),
        mismo=MismoSection.present(mismo or {}),
        tags=TagsSection.present({}),
    )


def _with_parsed(snapshot: Snapshot) -> Snapshot:
    """Materialize only the PARSED declarations (no AI) into the snapshot's tags layer — so a derived
    promotion (contract.loan_sales_price) can read the parsed contract.sales_price it depends on."""
    by_subject: dict[str, dict[str, Tag]] = {}
    for decl in load_declarations().values():
        if decl.mode.value != "parsed":
            continue
        st = subject_type(decl.subject)
        field_name = decl.data.split(":", 1)[0]
        for subject_id, raw in st.enumerate(snapshot):
            tag = produce_parsed_tag(decl, subject_id, st.read_field(raw, field_name))
            if tag is not None:
                by_subject.setdefault(subject_id, {})[decl.tag_id] = tag
    return snapshot.model_copy(update={"tags": TagsSection.present(by_subject)})


# --------------------------------------------------------------------------- #
# housing.taxes_monthly — annual_tax_amount ÷ 12, fail-closed
# --------------------------------------------------------------------------- #
def test_taxes_monthly_divides_annual_by_twelve() -> None:
    snap = _snapshot([_doc("t", "property_tax_bill", annual_tax_amount="4800.00")])
    value, reason = _housing_taxes_monthly(snap, _LOAN, None)
    assert value == "400.00"
    assert "4800.00" in reason


def test_taxes_monthly_unknown_when_no_bill_never_zero() -> None:
    value, _ = _housing_taxes_monthly(_snapshot([_doc("d", "w2")]), _LOAN, None)
    assert value == "unknown"  # absent ≠ 0


def test_taxes_monthly_unknown_on_nonpositive_and_conflicting() -> None:
    zero = _housing_taxes_monthly(
        _snapshot([_doc("t", "property_tax_bill", annual_tax_amount="0")]), _LOAN, None
    )
    assert zero[0] == "unknown"  # a 0 tax is implausible → fail-closed, never a confident 0
    conflict = _housing_taxes_monthly(
        _snapshot(
            [
                _doc("t1", "property_tax_bill", annual_tax_amount="4800.00"),
                _doc("t2", "property_tax_bill", annual_tax_amount="3600.00"),
            ]
        ),
        _LOAN,
        None,
    )
    assert (
        conflict[0] == "unknown"
    )  # two bills DISAGREE on the amount → cannot tell which is the subject's
    # NOTE: two bills that AGREE on the amount pass through as that amount (dedup by value, mirroring the DTI's
    # newest-bill when values agree) — the same-amount-different-property residual is the DTI's no-subject-match
    # limitation, a later refinement; see _housing_taxes_monthly's docstring.
    agree = _housing_taxes_monthly(
        _snapshot(
            [
                _doc("t1", "property_tax_bill", annual_tax_amount="3600.00"),
                _doc(
                    "t2", "property_tax_bill", annual_tax_amount="3600"
                ),  # same amount, different rendering
            ]
        ),
        _LOAN,
        None,
    )
    assert (
        agree[0] == "300.00"
    )  # 3600 / 12 — agreeing bills (different renderings) dedup to one value


# --------------------------------------------------------------------------- #
# housing.hoa_monthly — the periodicity conversion (D3) + fail-closed on an unstated/unrecognized one
# --------------------------------------------------------------------------- #
def test_hoa_monthly_converts_each_recognized_frequency() -> None:
    cases = {
        "monthly": "600.00",
        "quarterly": "200",
        "semiannual": "100",
        "semi-annual": "100",
        "annual": "50",
        "annually": "50",
    }
    for freq, expected in cases.items():
        snap = _snapshot([_doc("h", "hoa_statement", dues_amount="600.00", dues_frequency=freq)])
        value, _ = _housing_hoa_monthly(snap, _LOAN, None)
        assert Decimal(str(value)) == Decimal(expected), f"{freq}: {value}"


def test_hoa_monthly_fails_closed_on_unstated_or_unrecognized_frequency() -> None:
    # The D3 discipline — the tag must NOT assume monthly (the DTI's _extracted_hoa_monthly default) on an
    # unstated / unrecognized frequency; that is a silent 12x miscalculation. It abstains instead.
    unrecognized = _housing_hoa_monthly(
        _snapshot([_doc("h", "hoa_statement", dues_amount="600.00", dues_frequency="biweekly")]),
        _LOAN,
        None,
    )
    assert unrecognized[0] == "unknown"
    assert "periodicity" in unrecognized[1]
    unstated = _housing_hoa_monthly(
        _snapshot([_doc("h", "hoa_statement", dues_amount="600.00")]), _LOAN, None
    )
    assert unstated[0] == "unknown"


def test_hoa_monthly_unknown_when_no_statement_never_zero() -> None:
    # A NO-HOA property is unknown here (absent≠0); its not_applicable is DT-2's applicability call — a NUMBER
    # tag cannot carry a not_applicable enum (D5). Never a fabricated 0 that would look like "$0 HOA".
    value, reason = _housing_hoa_monthly(_snapshot([_doc("d", "w2")]), _LOAN, None)
    assert value == "unknown"
    assert "not 0" in reason


def test_hoa_monthly_unknown_on_conflicting_statements() -> None:
    snap = _snapshot(
        [
            _doc("h1", "hoa_statement", dues_amount="600.00", dues_frequency="monthly"),
            _doc("h2", "hoa_statement", dues_amount="300.00", dues_frequency="monthly"),
        ]
    )
    assert _housing_hoa_monthly(snap, _LOAN, None)[0] == "unknown"


# --------------------------------------------------------------------------- #
# contract.loan_sales_price — the document→loan promotion PC-2 reads
# --------------------------------------------------------------------------- #
def test_loan_sales_price_promotes_the_contract_price() -> None:
    snap = _with_parsed(_snapshot([_doc("pa", "purchase_agreement", sales_price="365000.00")]))
    value, _ = _loan_sales_price(snap, _LOAN, None)
    assert value == "365000.00"


def test_loan_sales_price_unknown_when_absent_and_on_disagreement() -> None:
    absent = _loan_sales_price(_with_parsed(_snapshot([_doc("d", "w2")])), _LOAN, None)
    assert absent[0] == "unknown"
    # Two purchase agreements disagreeing on the price → unknown (never a silently-picked value).
    disagree = _with_parsed(
        _snapshot(
            [
                _doc("pa1", "purchase_agreement", sales_price="365000.00"),
                _doc("pa2", "purchase_agreement", sales_price="400000.00"),
            ]
        )
    )
    value, reason = _loan_sales_price(disagree, _LOAN, None)
    assert value == "unknown"
    assert "disagree" in reason


# --------------------------------------------------------------------------- #
# D4 — the SUBJECT of each tag matches the LOAN subject its rule enumerates (anti-structural-death)
# --------------------------------------------------------------------------- #
def test_new_tags_are_declared_at_the_subject_their_rule_enumerates() -> None:
    decls = load_declarations()
    # PC-2 / DT-2 / DT-4 all enumerate the loan subject → their read tags must key under loan.
    for tag_id in (
        "property.purchase_price",
        "contract.loan_sales_price",
        "housing.taxes_monthly",
        "housing.hoa_monthly",
    ):
        assert decls[tag_id].subject == "loan", tag_id
    # contract.sales_price is the DOCUMENT fact the loan promotion reads (a per-document contract field).
    assert decls["contract.sales_price"].subject == "document"


def test_loan_derived_tags_materialize_under_the_loan_subject_key() -> None:
    snap = _with_parsed(
        _snapshot(
            [_doc("h", "hoa_statement", dues_amount="600.00", dues_frequency="monthly")],
            mismo={"property.purchase_price": _f("365000.00")},
        )
    )
    decls = load_declarations()
    for tag_id in ("contract.loan_sales_price", "housing.taxes_monthly", "housing.hoa_monthly"):
        produced = produce_derived_tags(decls[tag_id], snap)
        assert set(produced) == {_LOAN}  # exactly one subject — the loan
        assert tag_id in produced[_LOAN]


# --------------------------------------------------------------------------- #
# Additivity / equivalence — DT-5 is NOT wired; ACTIVE_RULE_IDS is unchanged
# --------------------------------------------------------------------------- #
def test_dt5_input_is_not_declared() -> None:
    # D1: DT-5 ("premium used vs binder") is a vacuous self-compare today, so ins.premium_annual stays UNwired.
    assert "ins.premium_annual" not in load_declarations()


def test_new_tags_are_declared_and_no_rule_activated() -> None:
    decls = load_declarations()
    for tag_id in (
        "contract.sales_price",
        "property.purchase_price",
        "contract.loan_sales_price",
        "housing.taxes_monthly",
        "housing.hoa_monthly",
    ):
        assert tag_id in decls
    assert len(ACTIVE_RULE_IDS) == 27  # tags only — no rule written or activated
