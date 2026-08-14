"""LP-389-A — ID-5 per borrower, through the REAL materialization path (the fiction rewritten).

LP-389 found ID-5 STRUCTURALLY DEAD: its inputs (id.id_expiration, contract.closing_date) materialize on the
DOCUMENT subject, but ID-5 read them at "loan" — couldnt_check on every file, its tests green only because
they hand-placed the tags at "loan" (the AS-1/ID-2/OC-2/LP-321a class). LP-389-A fixes it Priya's way: ID-5
checks EVERY borrower's ID (per-borrower, one verdict each), reusing LP-385's belongs_to attribution.

These pin the TRUE path — documents → materialize_tags (parsed id.id_expiration on the DL + derived per-borrower
promotion) → ID-5 reads the borrower's OWN attributed ID against the loan's one closing date. NOT a tag placed
where the rule reads it. The load-bearing properties: per-borrower isolation (one borrower's DL never covers
another's), fail-closed (no attributable DL → couldnt_check WITH a reason, never a guessed pass), the ID
expiration is taken ONLY from a government-ID document (not any doc that carries an expiration_date), and the
closing date is promoted to loan level (one date, every borrower checked against it).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from app.ai.extraction.parsing import coerce_date
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio

_B1 = UUID("11111111-1111-4111-8111-111111111111")
_B2 = UUID("22222222-2222-4222-8222-222222222222")


# --------------------------------------------------------------------------- #
# ⚠️ LP-508 review: these are RULE-LOGIC tests, so they run with the distrusted-field guard OFF.
#
# ID-3 and ID-5 gate on tags whose source fields are on the distrust list (a hallucinated driver's-licence
# date on docs 146/294), so with the guard live EVERY case here degrades to needs_review and the date
# comparison this file exists to prove is never reached. Asserting needs_review instead would delete the
# coverage, not move it. The DEGRADATION itself is asserted in test_distrusted_fields_lp508.py; this file
# keeps proving the logic underneath it.
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _without_distrust_guard(monkeypatch):
    monkeypatch.setattr("app.verification.rule_engine.gate.distrusted_tag_ids", dict, raising=True)


def _f(v: str) -> Field:
    return Field.present(v, source=FieldSource.EXTRACTED)


def _dl(
    cid: str, borrower: UUID, expiration: str, *, dtype: str = "drivers_license"
) -> DocumentEntry:
    return DocumentEntry(
        content_id=cid,
        document_type=dtype,
        belongs_to=(BorrowerRef(borrower_id=borrower, name="B"),),
        fields={"expiration_date": _f(expiration)},
    )


def _pa(closing: str = "2026-07-15") -> DocumentEntry:
    return DocumentEntry(
        content_id="pa", document_type="purchase_agreement", fields={"closing_date": _f(closing)}
    )


def _other(cid: str, borrower: UUID) -> DocumentEntry:
    # A NON-ID document attributed to the borrower (a pay stub). It carries no ID expiration, but it makes
    # the borrower ENUMERATE for the per-borrower rule (which draws borrowers from documents' belongs_to) —
    # so a borrower who submitted income docs but no driver's licence is still checked (and couldnt_checks).
    return DocumentEntry(
        content_id=cid,
        document_type="pay_stub",
        belongs_to=(BorrowerRef(borrower_id=borrower, name="B"),),
        fields={},
    )


def _snap(docs: list[DocumentEntry], *, borrowers: tuple[UUID, ...] = (_B1, _B2)) -> Snapshot:
    mismo = {f"borrower.{i}.borrower_id": _f(str(b)) for i, b in enumerate(borrowers, start=1)}
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 20, tzinfo=UTC),
        documents=DocumentsSection.present(docs),
        mismo=MismoSection.present(mismo),
        tags=TagsSection.present({}),
    )


async def _materialize(docs: list[DocumentEntry], **kw) -> Snapshot:
    return await materialize_tags(
        _snap(docs, **kw), only_groups=frozenset()
    )  # parsed + derived, no AI


async def _id5(docs: list[DocumentEntry], **kw) -> dict[str, Verdict]:
    mat = await _materialize(docs, **kw)
    return {
        str(r.subject_id): r.verdict
        for r in evaluate_deterministic_rule(load_rule_spec("ID-5"), mat)
    }


# --------------------------------------------------------------------------- #
# THE PROMOTION — the DL's document-subject expiration → the borrower subject
# --------------------------------------------------------------------------- #
async def test_id_expiration_is_promoted_per_borrower_from_the_attributed_dl() -> None:
    mat = await _materialize([_dl("dl1", _B1, "2029-06-12"), _dl("dl2", _B2, "2028-02-28"), _pa()])
    # id.id_expiration STAYS a document fact (dl1/dl2); the derived tag lands under the BORROWER.
    assert mat.tags.by_subject["dl1"]["id.id_expiration"].value == "2029-06-12"
    assert mat.tags.by_subject[str(_B1)]["id.borrower_id_expiration"].value == "2029-06-12"
    assert mat.tags.by_subject[str(_B2)]["id.borrower_id_expiration"].value == "2028-02-28"
    # the closing date is promoted to loan level (one value).
    assert mat.tags.by_subject["loan"]["contract.loan_closing_date"].value == "2026-07-15"


# --------------------------------------------------------------------------- #
# PER-BORROWER VERDICTS + ISOLATION — each borrower judged on their OWN ID
# --------------------------------------------------------------------------- #
async def test_fired_for_expired_satisfied_for_valid_each_on_their_own_id() -> None:
    # B1's DL is EXPIRED before closing; B2's is valid. Isolation: if B1 could read B2's DL it would satisfy.
    verdicts = await _id5(
        [_dl("dl1", _B1, "2026-04-30"), _dl("dl2", _B2, "2029-01-01"), _pa("2026-07-15")]
    )
    assert verdicts[str(_B1)] is Verdict.FIRED  # B1 on B1's own expired DL
    assert verdicts[str(_B2)] is Verdict.SATISFIED  # B2 on B2's own valid DL


async def test_boundary_expiration_equals_closing_is_satisfied_the_ge_default() -> None:
    verdicts = await _id5([_dl("dl1", _B1, "2026-07-15"), _pa("2026-07-15")], borrowers=(_B1,))
    assert (
        verdicts[str(_B1)] is Verdict.SATISFIED
    )  # valid ON the closing date (the encoded >= default)


# --------------------------------------------------------------------------- #
# FAIL-CLOSED — no attributable ID → couldnt_check WITH a reason, never a guessed pass
# --------------------------------------------------------------------------- #
async def test_borrower_with_no_attributable_dl_couldnt_checks_with_a_reason() -> None:
    # B1 has a DL; B2 submitted a pay stub but NO driver's licence. B2 must NOT silently pass — it
    # couldnt_checks, and the tag says why.
    mat = await _materialize([_dl("dl1", _B1, "2029-06-12"), _other("ps2", _B2), _pa()])
    b2_tag = mat.tags.by_subject[str(_B2)]["id.borrower_id_expiration"]
    assert b2_tag.value == "unknown" and "no driver's licence found" in (b2_tag.reasoning or "")
    verdicts = {
        str(r.subject_id): r.verdict
        for r in evaluate_deterministic_rule(load_rule_spec("ID-5"), mat)
    }
    assert verdicts[str(_B1)] is Verdict.SATISFIED  # B1's own valid DL
    assert verdicts[str(_B2)] is Verdict.COULDNT_CHECK  # B2: no ID → held, never a guessed pass


async def test_one_borrowers_dl_never_covers_another_the_lp332_masking_class() -> None:
    # ONLY B1's DL is present; B2 has a pay stub (so B2 enumerates) but no DL. B1's ID must never satisfy B2.
    verdicts = await _id5([_dl("dl1", _B1, "2029-06-12"), _other("ps2", _B2), _pa()])
    assert verdicts[str(_B1)] is Verdict.SATISFIED
    assert verdicts[str(_B2)] is Verdict.COULDNT_CHECK  # not SATISFIED — no cross-borrower leakage


async def test_conflicting_id_expirations_abstain_never_a_silently_picked_date() -> None:
    # Two DLs for B1 disagreeing on the expiration → ambiguous → unknown (not a silently-chosen date).
    mat = await _materialize(
        [_dl("dl1", _B1, "2026-04-30"), _dl("dl1b", _B1, "2029-06-12"), _pa()], borrowers=(_B1,)
    )
    tag = mat.tags.by_subject[str(_B1)]["id.borrower_id_expiration"]
    assert tag.value == "unknown" and "disagree" in (tag.reasoning or "")


async def test_same_expiration_two_formats_is_not_a_spurious_conflict() -> None:
    # Two DLs for B1 stating the SAME expiration in different renderings ("2029-06-12" vs "06/12/2029") AGREE.
    # The disagreement check normalizes dates (coerce_date), so a format difference is NOT read as ambiguity.
    mat = await _materialize(
        [_dl("dl1", _B1, "2029-06-12"), _dl("dl1b", _B1, "06/12/2029"), _pa()], borrowers=(_B1,)
    )
    tag = mat.tags.by_subject[str(_B1)]["id.borrower_id_expiration"]
    assert tag.value != "unknown"  # one agreed date, not a spurious "disagree" abstention
    assert coerce_date(str(tag.value)) == date(2029, 6, 12)


# --------------------------------------------------------------------------- #
# DOC-TYPE SCOPING — the expiration comes ONLY from a government ID, not any doc with expiration_date
# --------------------------------------------------------------------------- #
async def test_expiration_is_not_leaked_from_a_non_id_document() -> None:
    # A homeowners_insurance binder ALSO emits an expiration_date field (and so a leaked id.id_expiration).
    # The recipe must ignore it — the ID expiration comes only from the driver's licence.
    binder = DocumentEntry(
        content_id="ins",
        document_type="homeowners_insurance",
        belongs_to=(BorrowerRef(borrower_id=_B1, name="B"),),
        fields={"expiration_date": _f("2026-01-01")},  # a policy expiry, NOT an ID expiry
    )
    mat = await _materialize([_dl("dl1", _B1, "2029-06-12"), binder, _pa()], borrowers=(_B1,))
    # Only the DL's expiration is used — the binder's earlier date does not create a conflict or override.
    assert mat.tags.by_subject[str(_B1)]["id.borrower_id_expiration"].value == "2029-06-12"


# --------------------------------------------------------------------------- #
# THE CLOSING DATE — promoted to loan level; absent → couldnt_check (not a guessed pass)
# --------------------------------------------------------------------------- #
async def test_no_closing_date_couldnt_checks_every_borrower() -> None:
    mat = await _materialize(
        [_dl("dl1", _B1, "2029-06-12")], borrowers=(_B1,)
    )  # no purchase agreement
    assert (
        mat.tags.by_subject.get("loan", {}).get("contract.loan_closing_date", None) is None
        or mat.tags.by_subject["loan"]["contract.loan_closing_date"].value == "unknown"
    )
    (r,) = evaluate_deterministic_rule(load_rule_spec("ID-5"), mat)
    assert (
        r.verdict is Verdict.COULDNT_CHECK
    )  # no closing date → cannot judge, never a guessed pass
