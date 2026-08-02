"""LP-385 — the per-borrower income context: income_stability sees a borrower's income docs TOGETHER.

income_stability produced NOTHING per-document (LP-378: 0/120) because a 2-year trend / decline / continuance
is a CROSS-document question. It is now a per-BORROWER group whose context gathers the borrower's ATTRIBUTED
documents (by belongs_to — LP-202 evidence, fail-closed). These pin: attribution is by evidence (unattributed
→ not gathered), no cross-borrower contamination (LP-332 masking class), the tag materializes under the
BORROWER subject, and the context is honestly incomplete when a borrower has no attributable income docs.
(Whether the JUDGMENTS are correct is calibration — LP-379, unmeasured here.)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.tag_materialization.ai import AiGroupResult, AiSubjectJudgment, AiTagJudgment
from app.verification.tag_materialization.producer import materialize_tags
from app.verification.tag_materialization.subjects import (
    BorrowerSubject,
    ContextOptions,
    subject_type,
)

pytestmark = pytest.mark.anyio

_A = uuid4()  # Akash
_B = uuid4()  # Bansari


def _f(v: str) -> Field:
    return Field.present(v, source=FieldSource.EXTRACTED)


def _w2(cid: str, owner, *, year: str, employer: str, wages: str) -> DocumentEntry:
    return DocumentEntry(
        content_id=cid,
        document_type="w2",
        belongs_to=(BorrowerRef(borrower_id=owner, name="X"),) if owner is not None else None,
        fields={
            "tax_year": _f(year),
            "employer_name": _f(employer),
            "wages_tips_other_comp": _f(wages),
        },
    )


def _snap(entries: list[DocumentEntry]) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 19, tzinfo=UTC),
        documents=DocumentsSection.present(entries),
        mismo=MismoSection.present(
            {"borrower.1.borrower_id": _f(str(_A)), "borrower.2.borrower_id": _f(str(_B))}
        ),
        tags=TagsSection.present({}),
    )


def _borrower_ctx(snapshot: Snapshot, borrower_id, index: int, applies_to=None) -> dict:
    return subject_type("borrower").build_context(
        BorrowerSubject(str(borrower_id), index, snapshot), applies_to, ContextOptions()
    )


# --------------------------------------------------------------------------- #
# Attribution by evidence — the borrower's docs, and ONLY theirs
# --------------------------------------------------------------------------- #
def test_context_gathers_the_borrowers_attributed_documents() -> None:
    snap = _snap(
        [
            _w2("a24", _A, year="2024", employer="Acme", wages="100000"),
            _w2("a25", _A, year="2025", employer="Acme", wages="110000"),
            _w2("b25", _B, year="2025", employer="Globex", wages="90000"),
        ]
    )
    ctx = _borrower_ctx(snap, _A, 1)
    years = sorted(d["fields"]["tax_year"] for d in ctx["documents"])
    assert years == ["2024", "2025"]  # both of A's W-2s, seen together — the cross-document context
    employers = {d["fields"]["employer_name"] for d in ctx["documents"]}
    assert employers == {"Acme"} and "Globex" not in str(
        ctx
    )  # NONE of B's docs (no cross-contamination)


def test_unattributed_document_is_not_gathered_for_any_borrower() -> None:
    # A document with no belongs_to (attribution unresolved) is NOT guessed onto a borrower — the context is
    # honestly incomplete, never a trend fabricated from a mis-attributed document (LP-332/LP-336).
    snap = _snap([_w2("orphan", None, year="2025", employer="Acme", wages="100000")])
    assert _borrower_ctx(snap, _A, 1)["documents"] == []
    assert _borrower_ctx(snap, _B, 2)["documents"] == []


def test_context_filters_to_the_groups_applies_to_doc_types() -> None:
    # LP-385 review fix: a non-income document attributed to the borrower is NOT sent to income_stability —
    # the doc-type filter (applies_to) drops it STRUCTURALLY, not via the prompt's "ignore" instruction that
    # LP-378 measured failing. Fails OPEN on an unknown/None type (never dropped on a guess).
    snap = _snap(
        [
            _w2("a25", _A, year="2025", employer="Acme", wages="110000"),
            DocumentEntry(
                content_id="bank1",
                document_type="bank_statement",  # a KNOWN non-income type → excluded
                belongs_to=(BorrowerRef(borrower_id=_A, name="X"),),
                fields={"ending_balance": _f("5000")},
            ),
            DocumentEntry(
                content_id="mystery",
                document_type=None,  # unclassified → fail-open (kept, never dropped on a guess)
                belongs_to=(BorrowerRef(borrower_id=_A, name="X"),),
                fields={"x": _f("y")},
            ),
        ]
    )
    ctx = _borrower_ctx(snap, _A, 1, applies_to=frozenset({"w2", "pay_stub"}))
    types = {d["document_type"] for d in ctx["documents"]}
    assert types == {
        "w2",
        None,
    }  # the bank statement dropped; the unknown-type doc kept (fail-open)


def test_borrower_with_no_income_docs_has_empty_document_context() -> None:
    # No attributable income docs → an empty document context → the prompt returns unknown-with-reason for
    # every tag (honest incompleteness, never a fabricated trend). Here we assert the CONTEXT is empty.
    snap = _snap([_w2("b25", _B, year="2025", employer="Globex", wages="90000")])
    ctx_a = _borrower_ctx(snap, _A, 1)
    assert (
        ctx_a["documents"] == [] and ctx_a["borrower_mismo"]
    )  # A has no docs but keeps their MISMO facts


# --------------------------------------------------------------------------- #
# The tag now materializes under the BORROWER subject — per borrower, no cross-feed
# --------------------------------------------------------------------------- #
class _Stub:
    """An income_stability reasoner that reports the employers it SAW per subject — to prove each borrower's
    call carried only that borrower's documents."""

    def __init__(self) -> None:
        self.seen_per_index: dict[int, set[str]] = {}

    async def __call__(self, context_json: str) -> AiGroupResult:
        subjects = json.loads(context_json)["subjects"]
        for s in subjects:
            self.seen_per_index[int(s["index"])] = {
                d["fields"].get("employer_name") for d in s.get("documents", [])
            }
        return AiGroupResult(
            [
                AiSubjectJudgment(
                    index=int(s["index"]),
                    tags={
                        "has_2yr_history": AiTagJudgment("yes", 0.9, "two consecutive W-2s"),
                        "is_declining": AiTagJudgment("no", 0.9, "wages rose"),
                        "same_line_of_work": AiTagJudgment("yes", 0.9, "same employer"),
                        "continuance_3yr": AiTagJudgment("unknown", 0.5, "no horizon stated"),
                    },
                )
                for s in subjects
            ],
            1,
            1,
            "stub",
            False,
        )


async def test_income_stability_materializes_per_borrower_no_cross_feed() -> None:
    snap = _snap(
        [
            _w2("a24", _A, year="2024", employer="Acme", wages="100000"),
            _w2("a25", _A, year="2025", employer="Acme", wages="110000"),
            _w2("b25", _B, year="2025", employer="Globex", wages="90000"),
        ]
    )
    stub = _Stub()
    out = await materialize_tags(
        snap,
        ai_reasoners={"income_stability": stub},
        only_subjects=frozenset({"borrower"}),
        only_groups=frozenset({"income_stability"}),
    )
    # The tag is keyed under the BORROWER subject (borrower_id), not a document content_id.
    assert out.tags.by_subject[str(_A)]["income.has_2yr_history"].value == "yes"
    assert out.tags.by_subject[str(_B)]["income.has_2yr_history"].value == "yes"
    assert "a24" not in out.tags.by_subject  # NOT keyed under a document content_id
    # THE LP-332 MASKING CLASS: each borrower's call saw ONLY their own employer — no cross-borrower leak.
    seen = [set(v) for v in stub.seen_per_index.values()]
    assert {"Acme"} in seen and {
        "Globex"
    } in seen  # one borrower saw Acme, the other Globex — never mixed
    assert all(v in ({"Acme"}, {"Globex"}) for v in seen)
