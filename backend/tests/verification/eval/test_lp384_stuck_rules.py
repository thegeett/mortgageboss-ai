"""LP-384 — the stuck deterministic rules, unblocked by EXTENDING LF-6T3N with the documents they read.

Five no-AI rules resolved `unknown` because LF-6T3N lacked their inputs (LP-381/382/383), NOT because they are
broken. build_lf6t3n_plus adds those documents, each carrying a KNOWN, ASSERTED answer so the rule's CATCH is
provable — a deliberate 77-day gap (IN-4 FIRES), a deliberate missing page (AS-9 FIRES). AS-10 already resolves
on the base fixture. AS-3 (no §3B calculator) and IN-3 (needs the AI documented_monthly) stay blocked — the
gate correctly holds them (fail-closed). These pin the field-name match (the LP-333/369 trap), each rule's real
verdict (fire AND satisfy), the base-fixture additivity, and the earned activation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.eval.lf6t3n_fixture import build_lf6t3n_plus, build_lf6t3n_snapshot
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.tag_materialization.declarations import load_declarations
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio


def _f(v: str) -> Field:
    return Field.present(v, source=FieldSource.EXTRACTED)


async def _materialize(snap: Snapshot) -> Snapshot:
    return await materialize_tags(snap, only_groups=frozenset())  # parsed + derived, no AI


async def _verdicts(snap: Snapshot, rule_id: str) -> dict[str, Verdict]:
    mat = await _materialize(snap)
    return {
        str(r.subject_id): r.verdict
        for r in evaluate_deterministic_rule(load_rule_spec(rule_id), mat)
    }


def _snap(docs: list[DocumentEntry], *, mismo: dict | None = None) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 21, tzinfo=UTC),
        documents=DocumentsSection.present(docs),
        mismo=MismoSection.present(mismo or {}),
        tags=TagsSection.present({}),
    )


# --------------------------------------------------------------------------- #
# THE FIELD-NAME MATCH — the added documents carry the EXACT producer-read names (the LP-333/369 trap)
# --------------------------------------------------------------------------- #
def test_added_documents_use_the_exact_producer_read_field_names() -> None:
    decls = load_declarations()
    plus = {e.content_id: e for e in build_lf6t3n_plus().documents.entries}
    voe = plus["voe_prior"]
    stmt = plus["stmt_missing_page"]
    # IN-4's employment dates: the tag `data` name IS the VOE field the fixture populates.
    assert decls["income.employment_start"].data == "start_date" and "start_date" in voe.fields
    assert decls["income.employment_end"].data == "end_date" and "end_date" in voe.fields
    # AS-9's page counts.
    assert decls["stmt.page_count_declared"].data == "page_count_declared"
    assert decls["stmt.page_count_present"].data == "page_count_present"
    assert "page_count_declared" in stmt.fields and "page_count_present" in stmt.fields
    # AS-10's period end.
    assert decls["stmt.period_end"].data == "statement_period_end"
    assert "statement_period_end" in stmt.fields


# --------------------------------------------------------------------------- #
# ADDITIVE — the extension only APPENDS documents: existing documents' tags are untouched, and the AS-9
# statement was built NOT to disturb AS-10 (it joins an existing account + month). The only loan-level tag
# that changes is the employment gap — which the VOEs are added precisely to resolve (unknown → 77).
# --------------------------------------------------------------------------- #
async def test_plus_only_appends_documents_without_mutating_the_base() -> None:
    base = await _materialize(build_lf6t3n_snapshot())
    plus = await _materialize(build_lf6t3n_plus())
    # 1) the plus document set is the base set + exactly the three added documents.
    base_ids = {e.content_id for e in build_lf6t3n_snapshot().documents.entries}
    plus_ids = {e.content_id for e in build_lf6t3n_plus().documents.entries}
    assert plus_ids - base_ids == {"voe_prior", "voe_current", "stmt_missing_page"}
    # 2) every EXISTING (per-document) subject's tags are byte-identical — new documents mutate no old one.
    for subject, tags in base.tags.by_subject.items():
        if subject == "loan":
            continue
        for tag_id, tag in tags.items():
            got = plus.tags.by_subject.get(subject, {}).get(tag_id)
            assert got is not None and got.value == tag.value, f"{subject}/{tag_id} changed"
    # 3) AS-10's input is UNDISTURBED (the AS-9 statement joined an existing account + month on purpose).
    base_loan, plus_loan = base.tags.by_subject["loan"], plus.tags.by_subject["loan"]
    assert plus_loan["stmt.min_account_months"].value == base_loan["stmt.min_account_months"].value
    # ... and the ONLY loan tag that changes is the employment gap (the VOEs resolve it: unknown → 77).
    changed = {
        t for t in base_loan if base_loan[t].value != plus_loan.get(t, base_loan[t]).value
    } | {t for t in plus_loan if t not in base_loan}
    assert changed == {"income.max_employment_gap_days"}


# --------------------------------------------------------------------------- #
# IN-4 — a deliberate 77-day gap FIRES; a no-gap variant SATISFIES
# --------------------------------------------------------------------------- #
async def test_in4_fires_on_the_77_day_gap_in_the_plus_fixture() -> None:
    verdicts = await _verdicts(build_lf6t3n_plus(), "IN-4")
    assert verdicts["loan"] is Verdict.FIRED  # 77 days > the 30-day window


async def test_in4_satisfies_without_a_gap() -> None:
    # contiguous employment (prior ends 2024-06-30, next starts 2024-07-01) → 1-day gap → satisfied.
    docs = [
        DocumentEntry(
            content_id="v1",
            document_type="voe",
            fields={"start_date": _f("2022-01-10"), "end_date": _f("2024-06-30")},
        ),
        DocumentEntry(
            content_id="v2", document_type="voe", fields={"start_date": _f("2024-07-01")}
        ),
    ]
    assert (await _verdicts(_snap(docs), "IN-4"))["loan"] is Verdict.SATISFIED


# --------------------------------------------------------------------------- #
# AS-9 — a declared-5 / present-4 statement FIRES; a complete statement SATISFIES
# --------------------------------------------------------------------------- #
async def test_as9_fires_on_the_missing_page_in_the_plus_fixture() -> None:
    verdicts = await _verdicts(build_lf6t3n_plus(), "AS-9")
    assert verdicts["stmt_missing_page"] is Verdict.FIRED  # declares 5, only 4 present


async def test_as9_satisfies_when_complete() -> None:
    stmt = DocumentEntry(
        content_id="s",
        document_type="bank_statement",
        fields={"page_count_declared": _f("4"), "page_count_present": _f("4")},
    )
    assert (await _verdicts(_snap([stmt]), "AS-9"))["s"] is Verdict.SATISFIED


# --------------------------------------------------------------------------- #
# AS-10 — SATISFIES on the base fixture (already resolves); FIRES on a short account
# --------------------------------------------------------------------------- #
async def test_as10_satisfies_on_the_base_fixture() -> None:
    assert (await _verdicts(build_lf6t3n_snapshot(), "AS-10"))["loan"] is Verdict.SATISFIED


async def test_as10_fires_on_a_short_account() -> None:
    # one account with a single statement month → 1 < the required 2 → fires.
    stmt = DocumentEntry(
        content_id="s",
        document_type="bank_statement",
        fields={
            "bank_name": _f("Solo Bank"),
            "account_number_masked": _f("****9999"),
            "statement_period_end": _f("2026-05-31"),
        },
    )
    assert (await _verdicts(_snap([stmt]), "AS-10"))["loan"] is Verdict.FIRED


# --------------------------------------------------------------------------- #
# STILL HELD (fail-closed) — AS-3 (no calculator) + IN-3 (AI dependency) only abstain
# --------------------------------------------------------------------------- #
async def test_as3_and_in3_stay_couldnt_check_even_on_the_plus_fixture() -> None:
    plus = build_lf6t3n_plus()
    assert (await _verdicts(plus, "AS-3"))["loan"] is Verdict.COULDNT_CHECK  # no §3B calculator
    assert (await _verdicts(plus, "IN-3"))[
        "loan"
    ] is Verdict.COULDNT_CHECK  # needs documented_monthly (AI)


# --------------------------------------------------------------------------- #
# ACTIVATION — the three earned rules are live (14 → 17); AS-3/IN-3 are not
# --------------------------------------------------------------------------- #
def test_the_three_stuck_rules_activated_and_the_blocked_two_did_not() -> None:
    for rid in ("AS-9", "IN-4", "AS-10"):
        assert rid in ACTIVE_RULE_IDS
    for rid in ("AS-3", "IN-3"):
        assert rid not in ACTIVE_RULE_IDS
    assert len(ACTIVE_RULE_IDS) == 17


async def test_the_activated_rules_reach_real_verdicts_through_the_orchestrator() -> None:
    # end-to-end through evaluate_rules on the extended fixture (not just the evaluator directly).
    mat = await _materialize(build_lf6t3n_plus())
    results, _ = await evaluate_rules(mat, rule_ids=("AS-9", "IN-4", "AS-10"))
    verdicts = {r.rule_id for r in results if r.verdict in (Verdict.FIRED, Verdict.SATISFIED)}
    assert {"AS-9", "IN-4", "AS-10"} <= verdicts  # each reaches a real verdict somewhere
