"""LP-377-D — gate per-document AI groups to their declared doc-types, FAIL-OPEN.

The gate skips a paid AI call on a document a group does not apply to — the redundant call it would only
abstain on (and, for income_amounts, OVER-PRODUCE a value on: LP-378 caught it emitting documented_monthly on
mortgage statements / tax bills). It ALWAYS fails open: an unknown / low-confidence / no-match document runs
every group. The only failure mode is a tag silently NOT materializing, so these pin: the gate skips only the
KNOWN-inapplicable docs, fails open on unknown, keeps the prompt's abstention backstop, is reversible, and is
generic (no group-id branch). The real-data equivalence-except-garbage proof is a one-off run in LP-377-D.md.
"""

from __future__ import annotations

import inspect
import json
import re
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.core.config import settings
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.tag_materialization import ai as ai_module
from app.verification.tag_materialization.ai import (
    AiGroupResult,
    AiSubjectJudgment,
    AiTagJudgment,
)
from app.verification.tag_materialization.declarations import load_ai_groups
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio

_DOCS = frozenset({"document"})


def _snapshot(*doc_types: str) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 18, tzinfo=UTC),
        documents=DocumentsSection.present(
            [
                DocumentEntry(content_id=f"d{i}", document_type=t, fields={})
                for i, t in enumerate(doc_types)
            ]
        ),
        mismo=MismoSection.present({}),
        tags=TagsSection.present({}),
    )


class _Spy:
    """Records the doc-types each group is asked about; returns the given values (empty → abstain)."""

    def __init__(
        self, seen: dict[str, list[str]], key: str, values: dict[str, str] | None = None
    ) -> None:
        self.seen = seen
        self.key = key
        self.values = values or {}

    async def __call__(self, context_json: str) -> AiGroupResult:
        subs = json.loads(context_json)["subjects"]
        self.seen.setdefault(self.key, []).extend(str(s.get("document_type")) for s in subs)
        judgments = [
            AiSubjectJudgment(
                index=int(s["index"]),
                tags={k: AiTagJudgment(v, 0.9, "stub") for k, v in self.values.items()},
            )
            for s in subs
        ]
        return AiGroupResult(judgments, 1, 1, "stub", False)


async def _run(snap: Snapshot, groups: dict[str, _Spy]) -> None:
    await materialize_tags(
        snap, ai_reasoners=dict(groups), only_subjects=_DOCS, only_groups=frozenset(groups)
    )


# --------------------------------------------------------------------------- #
# The gate skips KNOWN-inapplicable docs, keeps matching + unknown (fail-open)
# --------------------------------------------------------------------------- #
async def test_gate_skips_inapplicable_keeps_matching_and_unknown() -> None:
    seen: dict[str, list[str]] = {}
    snap = _snapshot("w2", "mortgage_statement", "unknown")
    await _run(
        snap,
        {
            "income_amounts": _Spy(seen, "income_amounts"),  # applies_to = pay_stub/w2/1003
            "stmt_facts": _Spy(seen, "stmt_facts"),  # applies_to = bank_statement/money_market
            "id_name": _Spy(seen, "id_name"),  # applies_to = all
        },
    )
    # income_amounts: w2 (match) + unknown (fail-open); mortgage_statement SKIPPED (the over-production fix).
    assert sorted(seen["income_amounts"]) == ["unknown", "w2"]
    # stmt_facts: nothing matches → only the unknown (fail-open).
    assert sorted(seen["stmt_facts"]) == ["unknown"]
    # id_name (applies_to=all): every document.
    assert sorted(seen["id_name"]) == ["mortgage_statement", "unknown", "w2"]


async def test_income_amounts_does_not_produce_on_non_income_docs() -> None:
    # THE CORRECTNESS FIX (LP-378): a real value on a non-income doc is garbage. With the gate, income_amounts
    # produces on the w2 and NOT on the mortgage statement / tax bill.
    seen: dict[str, list[str]] = {}
    snap = _snapshot("w2", "mortgage_statement", "property_tax_bill")
    spy = _Spy(seen, "income_amounts", values={"documented_monthly": "18697"})
    out = await materialize_tags(
        snap,
        ai_reasoners={"income_amounts": spy},
        only_subjects=_DOCS,
        only_groups=frozenset({"income_amounts"}),
    )
    tagged = {
        cid for cid, tags in out.tags.by_subject.items() if "income.documented_monthly" in tags
    }
    assert tagged == {
        "d0"
    }  # only the w2 (d0); the mortgage/tax docs got NO income tag — no fabricated income


# --------------------------------------------------------------------------- #
# Fail-open: reversibility flag, non-document groups, the abstention backstop
# --------------------------------------------------------------------------- #
async def test_gate_off_runs_every_group_on_every_doc(monkeypatch) -> None:
    monkeypatch.setattr(settings, "gate_ai_groups", False)  # GATE_AI_GROUPS=0 → brute-force
    seen: dict[str, list[str]] = {}
    snap = _snapshot("w2", "mortgage_statement", "property_tax_bill")
    await _run(snap, {"income_amounts": _Spy(seen, "income_amounts")})
    assert sorted(seen["income_amounts"]) == [
        "mortgage_statement",
        "property_tax_bill",
        "w2",
    ]  # ALL docs


async def test_the_abstention_backstop_survives_a_fail_open_document() -> None:
    # A document the gate lets THROUGH (unknown → fail-open) that the group shouldn't produce for: the prompt
    # (here the stub) still ABSTAINS → an "unknown" tag, never a wrong value. The gate never removes this.
    seen: dict[str, list[str]] = {}
    snap = _snapshot("unknown")
    spy = _Spy(seen, "income_amounts", values={"documented_monthly": "unknown"})
    out = await materialize_tags(
        snap,
        ai_reasoners={"income_amounts": spy},
        only_subjects=_DOCS,
        only_groups=frozenset({"income_amounts"}),
    )
    assert seen["income_amounts"] == ["unknown"]  # the gate kept it (fail-open)...
    assert (
        out.tags.by_subject["d0"]["income.documented_monthly"].value == "unknown"
    )  # ...and it abstained


async def test_non_document_groups_are_not_gated() -> None:
    # txn_stage_a is transaction-subject; the doc-type gate never touches it. (No transactions here → it
    # simply enumerates none; the point is applies_to on a non-document group is a no-op, asserted via source.)
    assert load_ai_groups()["txn_stage_a"].subject == "transaction"
    assert "group.subject != _DOCUMENT_SUBJECT" in inspect.getsource(ai_module._gate_subjects)


async def test_confident_mistype_residual_is_named() -> None:
    # THE DOCUMENTED RESIDUAL (LP-377-D): the snapshot has no classification confidence, so a document
    # CONFIDENTLY mis-typed is gated by its wrong type. A title document mis-typed 'w2' → id_title (applies_to
    # = title docs) SKIPS it → id.title_vesting_consistent does not materialize on it. Named, not hidden.
    seen: dict[str, list[str]] = {}
    snap = _snapshot("w2")  # actually a title doc, but the classifier confidently typed it w2
    await _run(
        snap, {"id_title": _Spy(seen, "id_title", values={"title_vesting_consistent": "yes"})}
    )
    assert "id_title" not in seen  # id_title never ran on the mis-typed doc — the accepted residual


# --------------------------------------------------------------------------- #
# Generic — no group-id / doc-type branch in the gate
# --------------------------------------------------------------------------- #
def test_gate_is_generic_no_group_id_or_doc_type_branch() -> None:
    # Strip the docstring (whose prose mentions income_amounts / w2 as EXAMPLES) — the CODE must be free of
    # any group-id or doc-type branch; it keys only on group.applies_to + the document's type.
    src = inspect.getsource(ai_module._gate_subjects)
    code = re.sub(r'""".*?"""', "", src, flags=re.DOTALL)
    forbidden = [
        "income_amounts",
        "income_employer",
        "stmt_facts",
        "asset_facts",
        "id_title",
        "id_poa",
        "w2",
        "pay_stub",
        "bank_statement",
        "power_of_attorney",
        "title_commitment",
    ]
    for token in forbidden:
        assert token not in code, f"the gate must be generic (data-driven), found {token!r}"


# --------------------------------------------------------------------------- #
# Load-time guards on `applies_to` (LP-377-D review) — a typo can't silently gate a group to death
# --------------------------------------------------------------------------- #
def test_applies_to_rejects_a_document_type_not_in_the_catalog() -> None:
    # A slug the classifier never emits (typo / rename) would gate the group out on every real doc → a
    # silent-dead tag. It must fail LOUD at load, not silently, against the canonical catalog.
    from app.verification.tag_materialization.declarations import (
        DeclarationError,
        _parse_applies_to,
    )

    with pytest.raises(DeclarationError, match="not in the catalog"):
        _parse_applies_to("some_group", "document", ["pay_stub", "retirment_account"])  # typo


def test_applies_to_accepts_real_catalog_types_and_all() -> None:
    from app.verification.tag_materialization.declarations import _parse_applies_to

    assert _parse_applies_to("g", "document", ["pay_stub", "w2"]) == frozenset({"pay_stub", "w2"})
    assert _parse_applies_to("g", "document", "all") is None
    assert _parse_applies_to("g", "document", None) is None


def test_applies_to_on_a_loan_or_transaction_group_is_rejected() -> None:
    # applies_to names doc types, so it is meaningful only for a group that GATES on them (document, LP-377-D)
    # or GATHERS them (borrower, LP-385). On a loan/transaction group it is dead config — reject at load.
    from app.verification.tag_materialization.declarations import (
        DeclarationError,
        _parse_applies_to,
    )

    with pytest.raises(DeclarationError, match="does not gate or gather documents"):
        _parse_applies_to("txn_group", "transaction", ["pay_stub"])
    # A BORROWER group (gathers documents into its context, LP-385) IS allowed a list applies_to.
    assert _parse_applies_to("g", "borrower", ["w2", "pay_stub"]) == frozenset({"w2", "pay_stub"})
    # 'all' / omitted stays fine on any subject (it is the no-op default).
    assert _parse_applies_to("txn_group", "transaction", "all") is None
