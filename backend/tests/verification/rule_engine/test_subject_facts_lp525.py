"""LP-525 — a finding can name facts from its subject's own document.

THE LIMIT THIS REMOVES. A rule sees only its tags, and the tag layer deliberately narrows a document to
the few values the rule DECIDES on. Everything else — the context that makes a finding legible — is
dropped before the rule ever sees it. So IH-1 could say "the binder does not state a dwelling
loss-settlement basis" and could not say which binder, what Coverage A was, or which endorsements were
on it, even though all of that sits in the same snapshot one step away.

⚠️ WORDING ONLY. A declared subject fact is never gated, never compared, never load-bearing, and no
verdict may turn on it. A value a rule DECIDES on must be a tag, with the fail-closed gate and the
distrust layer behind it — this channel has neither, by design, because it exists to explain a verdict
rather than to reach one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.rule_engine.deterministic import (
    _fact_value,
    _subject_facts,
    evaluate_deterministic_rule,
)
from app.verification.rules.specs import SubjectFact, load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    ListRow,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from pydantic import ValidationError


def _f(value: str) -> Field:
    return Field.present(value, source=FieldSource.EXTRACTED)


def _row(code: str) -> ListRow:
    return ListRow(fields={"code_or_label": _f(code)})


def _binder(*, coverage: str | None = "577000", codes: tuple[str, ...] = ()) -> DocumentEntry:
    return DocumentEntry(
        content_id="hoi",
        document_type="homeowners_insurance",
        fields={"coverage_amount": _f(coverage)} if coverage is not None else {},
        lists={"forms_and_endorsements": tuple(_row(c) for c in codes)},
    )


# --------------------------------------------------------------------------------------------- #
# RESOLUTION
# --------------------------------------------------------------------------------------------- #
def test_a_scalar_field_resolves() -> None:
    assert _fact_value(_binder(), SubjectFact(field="coverage_amount")) == "577000"


def test_a_quoted_amount_keeps_the_precision_the_document_stated() -> None:
    """⚠️ DELIBERATELY UNLIKE LP-520's always-cents rule for AS-12's materiality floor, and the reason
    is the purpose. A floor is a COMPUTED comparison a processor judges, so "$2,000" has to be
    distinguishable from a rounded "$1,999.87". This is a QUOTE: a binder printing Coverage A of
    $577,000 should read back as $577,000, not as a more precise figure than it stated."""
    whole = _binder(coverage="577000")
    fractional = DocumentEntry(content_id="x", fields={"coverage_amount": _f("1234.56")})

    assert _fact_value(whole, SubjectFact(field="coverage_amount", money=True)) == "$577,000"
    assert _fact_value(fractional, SubjectFact(field="coverage_amount", money=True)) == "$1,234.56"


def test_a_list_names_its_rows() -> None:
    fact = SubjectFact(list="forms_and_endorsements", item="code_or_label")
    entry = _binder(codes=("HQ-208 NC", "HQ-220 NC", "HQ-290 NC"))

    assert _fact_value(entry, fact) == "HQ-208 NC, HQ-220 NC, HQ-290 NC"


def test_a_long_list_is_capped_and_says_so() -> None:
    """A binder can carry a dozen endorsements. Naming all of them buries the sentence; naming four and
    counting the rest keeps it readable without pretending the others do not exist."""
    fact = SubjectFact(list="forms_and_endorsements", item="code_or_label", limit=2)
    entry = _binder(codes=("A", "B", "C", "D", "E"))

    assert _fact_value(entry, fact) == "A, B and 3 more"


@pytest.mark.parametrize(
    "entry",
    [_binder(coverage=None), DocumentEntry(content_id="empty")],
    ids=["field-absent", "no-fields-at-all"],
)
def test_an_unresolved_fact_reads_as_not_stated_never_as_a_hole(entry: DocumentEntry) -> None:
    """⚠️ A sentence with a blank in it reads as a bug. "Coverage A of not stated" reads as what it
    actually is — a document that does not say — which is the same honesty the verdicts carry."""
    resolved = _subject_facts({"coverage_a": SubjectFact(field="coverage_amount")}, entry)

    assert resolved == {"coverage_a": "not stated"}


def test_a_subject_with_no_document_still_resolves_every_name() -> None:
    """A loan-level or per-borrower rule has no document behind the subject. Every declared name must
    still resolve to something, or `str.format` raises mid-run inside a Celery task."""
    resolved = _subject_facts({"a": SubjectFact(field="x"), "b": SubjectFact(field="y")}, None)

    assert resolved == {"a": "not stated", "b": "not stated"}


# --------------------------------------------------------------------------------------------- #
# LOAD VALIDATION
# --------------------------------------------------------------------------------------------- #
def test_a_fact_needs_exactly_one_source() -> None:
    with pytest.raises(ValidationError, match="exactly one of `field` or `list`"):
        SubjectFact(field="a", list="b", item="c")
    with pytest.raises(ValidationError, match="exactly one of `field` or `list`"):
        SubjectFact()


def test_a_list_without_an_item_is_rejected() -> None:
    """Without `item` there is no row field to take, and the fact would silently render nothing."""
    with pytest.raises(ValidationError, match="`list` requires `item`"):
        SubjectFact(list="forms_and_endorsements")


def test_an_undeclared_placeholder_is_rejected_at_load() -> None:
    """A stray placeholder raises at FORMAT time — mid-run, in a Celery task, after the AI calls have
    been paid for. Caught at load instead."""
    from app.verification.rules.specs import DeterministicEval

    with pytest.raises(ValidationError, match=r"unknown placeholder\(s\)"):
        DeterministicEval(
            load_bearing_tags=("t",),
            gated_tags=("t",),
            outcomes=({"verdict": "satisfied", "default": True, "reasoning": "ok"},),
            couldnt_check_fix="needs {nope}",
        )


# --------------------------------------------------------------------------------------------- #
# IH-1 END TO END — the finding a processor reads
# --------------------------------------------------------------------------------------------- #
def test_ih1_names_the_coverage_and_the_endorsements_it_looked_at() -> None:
    """The whole point, on the rule that motivated it. Before this the fix could only say "obtain the
    declarations page"; a processor looking at a binder that plainly says "Replacement Cost" had no way
    to see WHY that was not an answer. Now the finding shows the amount it read and the endorsements it
    checked, so the gap is visible rather than asserted."""
    tag = Tag(
        value="unknown",
        confidence=None,
        reasoning="the binder does not state a dwelling loss-settlement basis",
        source_facts=("doc",),
        produced_by=TagProducedBy.DERIVED,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )
    entry = _binder(codes=("HQ-208 NC", "HQ-220 NC", "HQ-290 NC"))
    snapshot = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 17, tzinfo=UTC),
        documents=DocumentsSection.present([entry]),
        tags=TagsSection.present({"hoi": {"ins.dwelling_settlement_basis": tag}}),
    )

    [result] = evaluate_deterministic_rule(load_rule_spec("IH-1"), snapshot)
    fix = result.how_to_fix or ""

    assert "$577,000" in fix
    assert "HQ-220 NC" in fix and "HQ-290 NC" in fix
    assert "Coverage C" in fix  # the personal-property distinction that caused the confusion


def test_ih1s_facts_are_not_inputs() -> None:
    """⚠️ THE BOUNDARY. `coverage_amount` is quoted in the wording and must never reach the verdict:
    not gated, not load-bearing, not compared. IH-1's decision still rests on one tag."""
    spec = load_rule_spec("IH-1")
    assert spec.deterministic is not None

    assert set(spec.deterministic.subject_facts) == {"coverage_a", "endorsements"}
    assert spec.deterministic.gated_tags == ("ins.dwelling_settlement_basis",)
    assert spec.deterministic.load_bearing_tags == ("ins.dwelling_settlement_basis",)
    assert "coverage_amount" not in str(spec.deterministic.operands)
