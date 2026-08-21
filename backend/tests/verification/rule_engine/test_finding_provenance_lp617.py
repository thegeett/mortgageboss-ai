"""LP-617 — a finding names the documents it is about.

ID-4 shipped "reconcile the discrepancies across the W-2s, pay stubs, bank statements, driver's
license, homeowners insurance, and property tax bill" — ten documents named as CATEGORIES and the
culprit as none of them. The processor opens all ten.

The engine knew. A consistency rule gathers per SOURCE and a per_document rule's subject IS the
document; both threw that away at the finding boundary. Across LF-3CVT and LF-T9HD, 148 governed
findings carried ZERO document links.

The value-matching populator could never have supplied this: `distinctive_values` reads
`details["document_value"]` and `source_snippet`, and a governed finding sets NEITHER — so it
returns an empty set for every one of them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult
from app.verification.rule_engine.consistency import evaluate_consistency_rule
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

pytestmark = pytest.mark.anyio

_B = uuid4()


def _tag(value: str) -> Tag:
    return Tag(
        value=value,
        confidence=0.9,
        reasoning="fixture",
        source_facts=("raw",),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _snap(docs: list[tuple[str, str, str]]) -> Snapshot:
    """[(content_id, document_type, address)] — all typed `residence`, all current."""
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 21, tzinfo=UTC),
        documents=DocumentsSection.present(
            [
                DocumentEntry(
                    content_id=cid,
                    document_type=dt,
                    belongs_to=(BorrowerRef(borrower_id=_B, name="Aditya"),),
                )
                for cid, dt, _ in docs
            ]
        ),
        tags=TagsSection.present(
            {
                cid: {
                    "id.address_normalized": _tag(addr),
                    "id.current_address_type": _tag("residence"),
                    "id.address_role": _tag("current_residence"),
                }
                for cid, _dt, addr in docs
            }
        ),
    )


async def _reasoner(_ctx: str) -> RuleJudgmentResult:
    return RuleJudgmentResult(RuleJudgment("disagree", 0.9, "different"), 1, 1, "stub", False)


async def test_a_consistency_finding_carries_the_documents_it_compared() -> None:
    """The sources that SURVIVED the filter and the exclusion — exactly what the verdict rests on."""
    snap = _snap(
        [
            ("docA", "pay_stub", "1 Main Street, Raleigh, NC 27601"),
            ("docB", "bank_statement", "9 Elm Road, Durham, NC 27701"),
        ]
    )
    results = await evaluate_consistency_rule(load_rule_spec("ID-4"), snap, reasoner=_reasoner)

    assert len(results) == 1
    assert set(results[0].source_content_ids) == {"docA", "docB"}


async def test_an_excluded_source_is_not_claimed_as_provenance() -> None:
    """A source dropped by LP-616's supersession exclusion did not inform the verdict, so it must not
    appear in the finding's provenance — a link to it would send a processor to the wrong document."""
    snap = _snap(
        [
            ("docA", "pay_stub", "1 Main Street, Raleigh, NC 27601"),
            ("docB", "bank_statement", "9 Elm Road, Durham, NC 27701"),
            ("old", "w2", "298 Sewall Street, Boylston, MA 01505"),
        ]
    )
    tags = dict(snap.tags.by_subject)
    tags["old"] = dict(tags["old"]) | {"id.address_role": _tag("superseded_residence")}
    snap = snap.model_copy(update={"tags": TagsSection.present(tags)})

    results = await evaluate_consistency_rule(load_rule_spec("ID-4"), snap, reasoner=_reasoner)

    assert "old" not in results[0].source_content_ids
    assert set(results[0].source_content_ids) == {"docA", "docB"}


def test_a_per_document_rule_carries_its_own_subject() -> None:
    """A per_document rule's subject IS the document, so its provenance is exact and free."""
    from app.verification.rules.specs import load_rule_spec as _load

    spec = _load("IH-1")
    assert spec.subject_enumeration == "per_document"


def test_a_loan_level_rule_claims_no_documents() -> None:
    """EMPTY IS HONEST. A rule over a computed tag has no document to point at, and a fabricated link
    is worse than none — so the subject_id (a borrower/liability/loan key) is never emitted as one."""
    from app.verification.rule_engine.result import RuleEvaluation, Verdict

    evaluation = RuleEvaluation(
        rule_id="DT-1",
        subject_id="loan",
        verdict=Verdict.SATISFIED,
        verdict_confidence=None,
        load_bearing_tags=(),
        threshold_used=None,
        priya_validated=False,
        gated_pending_signoff=False,
        reasoning="x",
        how_to_fix=None,
    )
    assert evaluation.source_content_ids == ()
