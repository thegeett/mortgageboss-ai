"""LP-390-8a — feed the stmt_facts group the loan's borrower roster so owner_matches_borrower can compare.

Before: `_doc_context` sent only the statement's own fields, so the group had no borrower names to compare
against and abstained structurally on every file (LP-390-5/LP-396: 5/5 `unknown`, "no borrower names were
provided"). This adds the loan's borrower roster to a DECLARING document group's context (a declared flag, not
a per-group code branch), reusing the LP-332 borrower resolution. Keyless: the live 5/5 `yes` re-score is
reported in docs/tickets/LP-390-8a.md; these pin the mechanism — the roster reaches stmt_facts, does NOT reach
any other group, is additive (is_reserve_eligible still sees the statement's fields), and empty/absent MISMO
degrades to an honest abstention path, never a leak.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    SnapshotField,
    TagsSection,
)
from app.verification.tag_materialization.ai import AiGroupResult, AiSubjectJudgment, AiTagJudgment
from app.verification.tag_materialization.declarations import DeclarationError, load_ai_groups
from app.verification.tag_materialization.producer import materialize_tags
from app.verification.tag_materialization.subjects import loan_borrower_roster

pytestmark = pytest.mark.anyio

_B1 = UUID("11111111-1111-4111-8111-111111111111")
_B2 = UUID("22222222-2222-4222-8222-222222222222")


def _f(v: str) -> Field:
    return Field.present(v, source=FieldSource.EXTRACTED)


def _stmt(cid: str, holder: str, owner: UUID) -> DocumentEntry:
    return DocumentEntry(
        content_id=cid,
        document_type="bank_statement",
        belongs_to=(BorrowerRef(borrower_id=owner, name="X"),),
        fields={"account_holder_name": _f(holder), "ending_balance": _f("5000")},
    )


def _snap(docs: list[DocumentEntry], *, borrowers: bool = True) -> Snapshot:
    mismo: dict[str, SnapshotField] = {}
    if borrowers:
        mismo = {
            "borrower.1.borrower_id": _f(str(_B1)),
            "borrower.1.first_name": _f("Jordan"),
            "borrower.1.last_name": _f("Rivera"),
            "borrower.2.borrower_id": _f(str(_B2)),
            "borrower.2.first_name": _f("Taylor"),
            "borrower.2.last_name": _f("Nguyen"),
        }
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 23, tzinfo=UTC),
        documents=DocumentsSection.present(docs),
        mismo=MismoSection.present(mismo),  # {} when borrowers=False → an empty roster
        tags=TagsSection.present({}),
    )


class _Capture:
    """A stub reasoner that records the context it was handed and echoes a fixed judgment."""

    def __init__(self, tags: dict[str, AiTagJudgment]) -> None:
        self.seen: list[dict[str, object]] = []
        self._tags = tags

    async def __call__(self, context_json: str) -> AiGroupResult:
        subjects = json.loads(context_json)["subjects"]
        self.seen.extend(subjects)
        return AiGroupResult(
            [AiSubjectJudgment(index=int(s["index"]), tags=dict(self._tags)) for s in subjects],
            1,
            1,
            "stub",
            False,
        )


def test_the_roster_reaches_stmt_facts_context() -> None:
    # the declared flag is set and the roster resolves from MISMO (reusing the LP-332 resolution).
    assert load_ai_groups()["stmt_facts"].include_borrower_roster is True
    assert loan_borrower_roster(_snap([_stmt("s1", "Jordan A Rivera", _B1)])) == [
        "Jordan Rivera",
        "Taylor Nguyen",
    ]


async def test_stmt_facts_context_carries_loan_borrowers_additively() -> None:
    # the fix: the group's context now includes "loan_borrowers" ALONGSIDE the statement's own fields — so
    # owner_matches_borrower has names to compare, and is_reserve_eligible still sees the statement (additive).
    stub = _Capture(
        {
            "owner_matches_borrower": AiTagJudgment("yes", 0.9, "Jordan A Rivera = Jordan Rivera"),
            "is_reserve_eligible": AiTagJudgment("yes", 0.9, "normal checking"),
        }
    )
    snap = _snap([_stmt("s1", "Jordan A Rivera", _B1)])
    out = await materialize_tags(
        snap, ai_reasoners={"stmt_facts": stub}, only_groups=frozenset({"stmt_facts"})
    )
    (ctx,) = stub.seen
    assert ctx["loan_borrowers"] == ["Jordan Rivera", "Taylor Nguyen"]  # the roster arrived
    assert (
        ctx["account_holder_name"] == "Jordan A Rivera"
    )  # ...alongside the statement's own fields
    # both tags produced (the group ran); the roster made owner_matches a real value, not the structural abstain
    tags = out.tags.by_subject["s1"]
    assert tags["stmt.owner_matches_borrower"].value == "yes"
    assert tags["stmt.is_reserve_eligible"].value == "yes"  # D4: unaffected, still its own judgment


async def test_other_document_groups_do_not_get_the_roster() -> None:
    # equivalence: a document group that does NOT declare the flag (asset_facts) sees a byte-unchanged context —
    # no "loan_borrowers" key. So only stmt_facts changed.
    stub = _Capture(
        {
            "liquidation_terms": AiTagJudgment("fully_liquid", 0.9, "brokerage"),
            "usable_value": AiTagJudgment("100", 0.9, "full"),
        }
    )
    inv = DocumentEntry(
        content_id="inv1",
        document_type="brokerage_statement",
        belongs_to=(BorrowerRef(borrower_id=_B1, name="X"),),
        fields={"institution_name": _f("Vanguard"), "total_value": _f("100000")},
    )
    await materialize_tags(
        _snap([inv]), ai_reasoners={"asset_facts": stub}, only_groups=frozenset({"asset_facts"})
    )
    (ctx,) = stub.seen
    assert "loan_borrowers" not in ctx  # asset_facts context is byte-unchanged


async def test_empty_roster_when_no_mismo_borrowers_reaches_the_abstain_path() -> None:
    # D3 — abstention stays REAL: with no borrowers to compare against, the roster is empty and the prompt is
    # instructed to answer "unknown" (there is nothing to match). The context still carries the (empty) key.
    stub = _Capture(
        {
            "owner_matches_borrower": AiTagJudgment("unknown", 0.4, "no loan_borrowers to compare"),
            "is_reserve_eligible": AiTagJudgment("yes", 0.9, "normal checking"),
        }
    )
    snap = _snap([_stmt("s1", "Someone Else", _B1)], borrowers=False)
    assert loan_borrower_roster(snap) == []
    out = await materialize_tags(
        snap, ai_reasoners={"stmt_facts": stub}, only_groups=frozenset({"stmt_facts"})
    )
    (ctx,) = stub.seen
    assert ctx["loan_borrowers"] == []  # an empty roster, sent honestly (not "no key at all")
    assert out.tags.by_subject["s1"]["stmt.owner_matches_borrower"].value == "unknown"


def test_declaration_rejects_the_flag_on_a_non_document_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the loader guard: the roster is the comparison context for a DOCUMENT's stated party — meaningless on a
    # transaction/borrower/loan group, so a mis-declared flag fails loud rather than silently doing nothing.
    from app.verification.tag_materialization import declarations as d

    bad = {
        "ai_groups": {
            "x": {
                "subject": "transaction",
                "context_builder": "transaction",
                "tags": ["txn.foo"],
                "system_prompt": "p",
                "include_borrower_roster": True,
            }
        }
    }
    monkeypatch.setattr(d, "_production_doc", lambda: bad)
    d.load_ai_groups.cache_clear()
    try:
        with pytest.raises(DeclarationError, match="include_borrower_roster"):
            d.load_ai_groups()
    finally:
        d.load_ai_groups.cache_clear()  # drop the poisoned/empty cache so other tests reload the real doc
