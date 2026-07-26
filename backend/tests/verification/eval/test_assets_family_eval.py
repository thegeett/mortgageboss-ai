"""LP-323-AS-C — the ASSETS family GOLDEN EVAL (the full case matrix + the pins).

Mirrors LP-323-ID-C / IN-C (the LP-317 harness is AS-1/txn-shaped — this is the dedicated assets harness
beside it). Each of the 10 authored rules (AS-2..AS-12, minus the deferred AS-8) is exercised through its
real evaluator; NONE is activated (ACTIVE_RULE_IDS verified — only AS-1 is live). EVALUATE, DON'T FIX.

NEW THIS WAVE: **case 12 is FULLY REAL** — AS-4 reads the WIRED `reserves` calculator, so a GATED calc →
the operand is None → couldnt_check (the system's first genuine gated-calculator test). PINS asserted:
AS-3 + AS-9 bucket C; AS-2's approximation; **AS-4's aggregate MASKING** (it reads one aggregate number and
cannot see a single ineligible account — contrast AS-10's per-account minimum, which AS-B built to NOT mask).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.enumerators import resolve_accounts
from app.verification.rule_engine.judgment import evaluate_judgment_rule
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    CalculationEntry,
    CalculationsSection,
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
    TransactionRecord,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

pytestmark = pytest.mark.anyio

_B = uuid4()


def _tag(v: object, *, conf: float | None = 0.9, by: TagProducedBy = TagProducedBy.AI) -> Tag:
    return Tag(
        value=v,
        confidence=conf,
        reasoning="fixture",
        source_facts=("raw",),
        produced_by=by,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _derived(v: object) -> Tag:
    return _tag(v, conf=None, by=TagProducedBy.DERIVED)


def _f(v: str) -> Field:
    return Field.present(v, source=FieldSource.EXTRACTED)


def _doc(cid: str, dtype: str = "bank_statement", *, fields=None) -> DocumentEntry:
    return DocumentEntry(
        content_id=cid,
        document_type=dtype,
        belongs_to=(BorrowerRef(borrower_id=_B, name="Sam"),),
        fields=fields or {},
    )


def _snap(*, docs=None, by_subject=None, mismo=None, reserves=None) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
        documents=DocumentsSection.present(list(docs or [])),
        mismo=MismoSection.present(mismo or {}),
        tags=TagsSection.present(by_subject or {}),
        calculations=CalculationsSection.present(reserves=reserves)
        if reserves is not None
        else CalculationsSection.missing(),
    )


def _det(rule_id: str, snap: Snapshot):
    return evaluate_deterministic_rule(load_rule_spec(rule_id), snap)


class _Reasoner:
    def __init__(self, value: str = "yes") -> None:
        self.value, self.calls = value, 0

    async def __call__(self, _ctx: str) -> RuleJudgmentResult:
        self.calls += 1
        return RuleJudgmentResult(RuleJudgment(self.value, 0.9, "x"), 1, 1, "stub", False)


def test_assets_activation_state() -> None:
    # LP-384 activated AS-9 (page completeness) + AS-10 (statement recency); LP-390-7 activated AS-2 (EMD
    # sourcing, auto) + AS-12 (borrowed-funds, ratify) — the first income-wave AI rules, Priya's 0.90 bars
    # signed off once apparent_category (100% concrete, LP-390-5a) + has_identified_source (93.8%) were measured.
    # LP-393-6 activated AS-11 (retirement/stock liquidation terms, auto) — liquidation_terms scored 100% (6/6)
    # on the LP-393-1 fixture after LP-393-4a encoded Priya's precedence rule; she signed off the 0.90 bar.
    for rid in ("AS-9", "AS-10", "AS-2", "AS-12", "AS-11"):
        assert rid in ACTIVE_RULE_IDS
    # The rest stay inert: authored + evaluated, not shipped (the LP-333 discipline). AS-3 is calculator-
    # blocked (no §3B cash-to-close calc); the others rest on unscored AI tags / a design question (AS-5).
    for rid in ("AS-3", "AS-4", "AS-5", "AS-6", "AS-7"):
        assert rid not in ACTIVE_RULE_IDS


# ================================================================================================= #
# AS-4 — reserves adequacy (calc + matrix; case 12 REAL; the MASKING pin)
# ================================================================================================= #
def _as4(months: str | None, required: str | None, *, gated: bool = False):
    reserves = (
        CalculationEntry(value={"months_available": months}, gated=gated)
        if months is not None
        else None
    )
    tags = {"loan": {"reserves.required_months": _derived(required)}} if required else {}
    return _det("AS-4", _snap(by_subject=tags, reserves=reserves))


def test_as4_fire_clean_boundaries() -> None:
    assert _as4("1", "6")[0].verdict is Verdict.FIRED and _as4("1", "6")[0].reasoning  # 1 + 9
    assert _as4("6", "6")[0].verdict is Verdict.SATISFIED  # 2
    assert _as4("5", "6")[0].verdict is Verdict.FIRED  # 3 just UNDER required → fire
    assert _as4("6", "6")[0].verdict is Verdict.SATISFIED  # 4 at requirement


def test_as4_case12_gated_reserves_calc_couldnt_check() -> None:
    # THE HEADLINE — a GATED wired calculator → the operand is None → couldnt_check (the first genuine
    # gated-calculator test; ID had none, Income only approximated it via a derived tag).
    assert _as4("6", "6", gated=True)[0].verdict is Verdict.COULDNT_CHECK  # 12
    assert (
        _as4("6", None)[0].verdict is Verdict.COULDNT_CHECK
    )  # 5/6 required_months absent/unknown → couldnt_check


def test_as4_case13_investment_matrix_and_the_MASKING_pin() -> None:
    # case 13 (D1 matrix): an investment property → 6 months required; 3 available → fire.
    assert _as4("3", "6")[0].verdict is Verdict.FIRED
    # PIN — AS-4 aggregate MASKING. AS-4 reads ONE aggregate (months_available) — it has NO per-account
    # input, so a passing aggregate satisfies it EVEN IF that total includes an ineligible/inflated
    # account's funds. The only guard is upstream (asset.usable_value zeroing ineligible), which is
    # UNCALIBRATED AI. So AS-4 MASKS a single account's problem (unlike AS-10's per-account minimum).
    # PINNED (a fix ticket: give AS-4 per-account visibility, or trust the upstream once calibrated).
    assert (
        _as4("6", "6")[0].verdict is Verdict.SATISFIED
    )  # a passing aggregate — the masking is invisible to AS-4


# AS-4 case 7 (low-conf) N/A¹: required_months is a derived tag (conf None → never needs_review). case 8
# N/A²: numeric, no label variance. case 11 N/A³: not a judgment. case 10 tag-level: covered by the recipe.


# ================================================================================================= #
# AS-10 — statement recency (per-account MINIMUM — the anti-masking counter-example)
# ================================================================================================= #
def _as10(min_months: str | None):
    tags = {"loan": {"stmt.min_account_months": _derived(min_months)}} if min_months else {}
    return _det("AS-10", _snap(by_subject=tags))


def test_as10_fire_boundary_and_no_masking() -> None:
    assert _as10("1")[0].verdict is Verdict.FIRED  # 1 (a short account) < 2
    assert _as10("2")[0].verdict is Verdict.SATISFIED  # 2/4 at the requirement
    assert _as10("3")[0].verdict is Verdict.SATISFIED
    assert _as10(None)[0].verdict is Verdict.COULDNT_CHECK  # 5 absent → couldnt_check


def test_as10_domain13_a_short_account_is_not_masked_by_a_full_one() -> None:
    # THE COUNTER-EXAMPLE to AS-4's masking: the recipe takes the per-account MINIMUM (LP-336
    # resolve_accounts), so one 1-month account among a 3-month account → min 1 → AS-10 FIRES. AS-B fixed
    # this shape at authoring; assert it. Chase-****5678 has 1 month, Wells-****9999 has 3 → min 1.
    def stmt(cid, bank, num):
        return _doc(
            cid,
            fields={
                "bank_name": _f(bank),
                "account_number_masked": Field.present(num, source=FieldSource.EXTRACTED),
            },
        )

    from app.verification.tag_materialization.derived import _stmt_min_account_months

    # Chase: 1 statement (May) → 1 distinct month. Wells: 3 statements (Apr/May/Jun) → 3. Months come
    # from stmt.period_end below, not from the doc fields.
    docs = [
        stmt("c1", "Chase", "12345678"),
        stmt("w1", "Wells", "99999999"),
        stmt("w2", "Wells", "99999999"),
        stmt("w3", "Wells", "99999999"),
    ]
    by = {
        "c1": {"stmt.period_end": _tag("2026-05-31")},
        "w1": {"stmt.period_end": _tag("2026-04-30")},
        "w2": {"stmt.period_end": _tag("2026-05-31")},
        "w3": {"stmt.period_end": _tag("2026-06-30")},
    }
    val, _ = _stmt_min_account_months(_snap(docs=docs, by_subject=by), "loan", None)
    assert val == "1"  # Chase has 1 month, not masked by Wells's 3 → AS-10 would fire


# ================================================================================================= #
# AS-7 — NSF (boundaries real)
# ================================================================================================= #
def _as7(count: str | None):
    tags = {"loan": {"stmt.nsf_count": _derived(count)}} if count else {}
    return _det("AS-7", _snap(by_subject=tags))


def test_as7_fire_clean_boundaries_and_absent() -> None:
    assert _as7("5")[0].verdict is Verdict.FIRED and _as7("5")[0].reasoning  # 1 + 9
    assert _as7("2")[0].verdict is Verdict.SATISFIED  # 2
    assert _as7("4")[0].verdict is Verdict.FIRED  # 3 just OVER 3
    assert _as7("3")[0].verdict is Verdict.SATISFIED  # 4 at tolerance
    assert _as7(None)[0].verdict is Verdict.COULDNT_CHECK  # 5


# ================================================================================================= #
# AS-6 / AS-11 — per_document + applicability (scope + fire)
# ================================================================================================= #
def _bs(owner: str, variance: str = "none", co_holder: str = "no"):
    # LP-404: AS-6 reads all three statement-holder tags on the bank_statement subject.
    return {
        "bs": {
            "stmt.owner_matches_borrower": _tag(owner),
            "stmt.holder_name_variance": _tag(variance),
            "stmt.non_borrower_co_holder": _tag(co_holder),
        }
    }


def test_as6_owner_mismatch_fires_scoped() -> None:
    # LP-404 — Priya's three outcomes: a `no` fires (an open finding); a non-statement is out of scope.
    docs = [_doc("bs", "bank_statement"), _doc("dl", "drivers_license")]
    by = {
        r.subject_id: r.verdict
        for r in _det("AS-6", _snap(docs=docs, by_subject=_bs("no", "middle_differs")))
    }
    assert by["bs"] is Verdict.FIRED and by["dl"] is Verdict.NOT_APPLICABLE  # non-match + scope
    bs = [_doc("bs", "bank_statement")]
    # a CERTAIN match (incl. a benign dropped middle) with no co-holder counts silently
    assert _det("AS-6", _snap(docs=bs, by_subject=_bs("yes", "middle_absent")))[0].verdict is (
        Verdict.SATISFIED
    )
    # PLAUSIBLE but unconfirmed → surfaced (needs_review) while the statement still counts
    assert _det("AS-6", _snap(docs=bs, by_subject=_bs("unknown", "nickname")))[0].verdict is (
        Verdict.NEEDS_REVIEW
    )
    # a joint account with a non-borrower co-holder → surfaced while the statement still counts
    assert _det("AS-6", _snap(docs=bs, by_subject=_bs("yes", "none", "yes")))[0].verdict is (
        Verdict.NEEDS_REVIEW
    )
    # the holder facts were unreadable (variance absent) → honest abstention
    assert (
        _det(
            "AS-6",
            _snap(docs=bs, by_subject={"bs": {"stmt.owner_matches_borrower": _tag("no")}}),
        )[0].verdict
        is Verdict.COULDNT_CHECK
    )


def test_as11_restricted_fires_scoped() -> None:
    r = _det(
        "AS-11",
        _snap(
            docs=[_doc("ra", "retirement_account")],
            by_subject={"ra": {"asset.liquidation_terms": _tag("restricted")}},
        ),
    )
    assert r[0].verdict is Verdict.FIRED  # 1 (+13: a 401k restricted balance)
    na = _det("AS-11", _snap(docs=[_doc("bs", "bank_statement")]))
    assert na[0].verdict is Verdict.NOT_APPLICABLE  # scope: a non-retirement doc
    ok = _det(
        "AS-11",
        _snap(
            docs=[_doc("ra", "retirement_account")],
            by_subject={"ra": {"asset.liquidation_terms": _tag("fully_liquid")}},
        ),
    )
    assert ok[0].verdict is Verdict.SATISFIED  # 2


# ================================================================================================= #
# AS-5 — gift chain (applicability; the gift-letter loop domain edge)
# ================================================================================================= #
def test_as5_gift_chain_scope_and_fire() -> None:
    # SCOPE (production-faithful): a non-gift-letter doc → not_applicable.
    na = _det("AS-5", _snap(docs=[_doc("bs", "bank_statement")]))
    assert (
        na[0].verdict is Verdict.NOT_APPLICABLE
    )  # 13/scope: no gift used → not_applicable (a gift rule is irrelevant)

    # KEYING-GAP PIN (LP-323-AS-C review): AS-5 is per_document on the gift letter and reads
    # txn.apparent_category from the gift-letter DOCUMENT subject (AS-5.yaml), but that tag is materialized
    # subject: transaction (tag_production.yaml) — a gift-letter document NEVER carries it. So in
    # production the load-bearing tag is absent → couldnt_check, ALWAYS; AS-5 cannot FIRE/SATISFY as
    # authored. It must read the gift DEPOSIT transaction's category (a cross-document gift↔deposit
    # correlation), not the letter's. PINNED — a spec fix, reported like the bucket-C gaps.
    gap = _det(
        "AS-5", _snap(docs=[_doc("gl", "gift_letter")])
    )  # no txn tag on the letter, as in prod
    assert gap[0].verdict is Verdict.COULDNT_CHECK

    # The rule's LOGIC is sound once the category reaches where AS-5 reads it (proving the gap is
    # keying/materialization, not logic) — reachable only AFTER the re-keying above. Tags hand-placed on
    # the gift-letter subject here to exercise the deterministic path:
    fire = _det(
        "AS-5",
        _snap(
            docs=[_doc("gl", "gift_letter")],
            by_subject={"gl": {"txn.apparent_category": _tag("vendor")}},
        ),
    )
    assert (
        fire[0].verdict is Verdict.FIRED
    )  # spec logic: gift letter but the transfer is not evidenced as a gift (reachable only after re-key)
    ok = _det(
        "AS-5",
        _snap(
            docs=[_doc("gl", "gift_letter")],
            by_subject={"gl": {"txn.apparent_category": _tag("gift")}},
        ),
    )
    assert ok[0].verdict is Verdict.SATISFIED  # spec logic (reachable only after re-key)


# ================================================================================================= #
# AS-2 — EMD sourcing (case 8 label variance) + THE APPROXIMATION PIN
# ================================================================================================= #
def _as2_txn(category: str, sourced: str):
    txn = TransactionRecord(
        content_id="t1",
        amount=_f("5000"),
        date=_f("2026-05-01"),
        direction=_f("credit"),
        description=_f("wire"),
    )
    doc = DocumentEntry(
        content_id="bs",
        document_type="bank_statement",
        belongs_to=(BorrowerRef(borrower_id=_B, name="Sam"),),
        transactions=(txn,),
    )
    return _det(
        "AS-2",
        _snap(
            docs=[doc],
            by_subject={
                "t1": {
                    "txn.apparent_category": _tag(category),
                    "txn.has_identified_source": _tag(sourced),
                }
            },
        ),
    )


def test_as2_fire_and_case8_and_the_approximation_pin() -> None:
    assert (
        _as2_txn("loan_proceeds", "no")[0].verdict is Verdict.FIRED
    )  # 1: unsourced loan-proceeds outflow
    assert _as2_txn("payroll", "yes")[0].verdict is Verdict.SATISFIED  # 2
    # case 8 (the direction=="credit" ORIGIN STORY): the fact-tag pivot's whole point is that an unusually
    # LABELED money-in is ABSTRACTED into txn.apparent_category by the AI — so the rule reads the clean enum
    # (loan_proceeds) regardless of the raw description, which is exactly what line 1 exercises. The raw
    # label → enum step is the AI's (a calibration concern), not the rule's; at the rule level the enum is
    # authoritative. A tag valued "unknown" gates to couldnt_check (asserted below), never a wrong fire.
    assert (
        _as2_txn("loan_proceeds", "unknown")[0].verdict is Verdict.COULDNT_CHECK
    )  # 6: unknown source → gate
    # PIN — AS-2 is an APPROXIMATION. The TRUE EMD check is a cross-document MATCH (the contract's EMD
    # amount ↔ a debit in a verified account), which is not cleanly expressible today. This rule
    # approximates it via txn sourcing (fires on an unsourced loan_proceeds inflow) — it does NOT match the
    # contract amount, does NOT check the direction (an EMD is a DEBIT), and does NOT catch an EMD paid
    # OUTSIDE the statements. PINNED (a fix ticket: a cross-document match, needs the contract EMD extracted).


# ================================================================================================= #
# AS-3 + AS-9 — the BUCKET C pins (couldnt_check; the exact upstream extraction ask)
# ================================================================================================= #
def test_pin_as3_bucket_c_closing_costs_absent() -> None:
    # AS-3: the cash-to-close recipe abstains (closing_costs is not extracted — no Loan-Estimate/CD
    # extraction) → couldnt_check. PINNED: the upstream ask is an LE/CD extraction producing closing_costs.
    (r,) = _det("AS-3", _snap())
    assert r.verdict is Verdict.COULDNT_CHECK


def test_pin_as9_bucket_c_no_page_count_extraction() -> None:
    # AS-9: the page-count tags never materialize (bank_statement.py extracts no page count) → couldnt_check.
    # PINNED: the upstream ask is a 'Page X of Y' extraction field.
    (r,) = _det("AS-9", _snap(docs=[_doc("bs", "bank_statement")]))
    assert r.verdict is Verdict.COULDNT_CHECK


# ================================================================================================= #
# AS-12 — judgment (armor + provenance + fail-closed)
# ================================================================================================= #
async def _as12(reasoned: dict, reasoner):
    txn = TransactionRecord(
        content_id="t1",
        amount=_f("20000"),
        date=_f("2026-05-01"),
        direction=_f("credit"),
        description=_f("wire"),
    )
    doc = DocumentEntry(
        content_id="bs",
        document_type="bank_statement",
        belongs_to=(BorrowerRef(borrower_id=_B, name="Sam"),),
        transactions=(txn,),
    )
    return await evaluate_judgment_rule(
        load_rule_spec("AS-12"), _snap(docs=[doc], by_subject={"t1": reasoned}), reasoner=reasoner
    )


async def test_as12_armor_provenance_failclosed() -> None:
    stub = _Reasoner("yes")
    (ev,) = await _as12(
        {
            "txn.apparent_category": _tag("loan_proceeds"),
            "txn.has_identified_source": _tag("no"),
            "txn.counterparty": _tag("Unknown LLC"),
        },
        stub,
    )
    assert ev.evaluation.verdict is Verdict.NEEDS_REVIEW  # 1: a judgment never auto-fires
    assert ev.evaluation.ratification_pending  # 11 ARMOR
    assert ev.evaluation.reasoning and stub.calls == 1  # 9 provenance; the AI was consulted
    # fail-closed: a gated reasoned-over tag absent → couldnt_check, NO AI call.
    gated = _Reasoner("yes")
    (g,) = await _as12({}, gated)
    assert g.evaluation.verdict is Verdict.COULDNT_CHECK and gated.calls == 0  # 5/12


# ================================================================================================= #
# per_account (LP-336) — an ambiguous identity → couldnt_check, never a guessed grouping
# ================================================================================================= #
def test_per_account_ambiguous_identity_not_grouped() -> None:
    def stmt(cid, bank, num):
        fields = {}
        if bank is not None:
            fields["bank_name"] = _f(bank)
        if num is not None:
            fields["account_number_masked"] = Field.present(num, source=FieldSource.EXTRACTED)
        return _doc(cid, fields=fields)

    resolved, unresolvable = resolve_accounts(
        _snap(docs=[stmt("ok", "Chase", "12345678"), stmt("ghost", None, "12345678")])
    )
    assert list(resolved.values()) == [["ok"]] and unresolvable == [
        "ghost"
    ]  # never a guessed merge


# ================================================================================================= #
# AS-8 — now LIVE (LP-406-2b, on the derived stmt.continuity tag); AS-1 — LIVE (unchanged)
# ================================================================================================= #
def test_as8_live_on_stmt_continuity_and_as1_unchanged() -> None:
    # AS-8's pairwise-sequential shape (deferred at LP-323-AS-A) is computed by the derived stmt.continuity
    # tag (LP-410), so AS-8 is a trivial deterministic rule that branches on it — and LIVE (LP-406-2b:
    # no-ai-dependency, its input resolves to "chained" on LF-6T3N → SATISFIED).
    as8 = load_rule_spec("AS-8")
    assert as8.deterministic is not None and "AS-8" in ACTIVE_RULE_IDS
    assert (
        load_rule_spec("AS-1").subject_enumeration == "per_deposit" and "AS-1" in ACTIVE_RULE_IDS
    )  # live, unchanged


# ================================================================================================= #
# NO EVAL FATIGUE — every in-scope AS rule has a must-FIRE case here (the guard)
# ================================================================================================= #
def test_every_in_scope_as_rule_has_a_must_fire_case_in_this_module() -> None:
    src = __import__("pathlib").Path(__file__).read_text()
    markers = {
        "AS-2": '_as2_txn("loan_proceeds", "no")[0].verdict is Verdict.FIRED',
        "AS-3": "test_pin_as3_bucket_c",  # cannot fire — bucket C (reported, the credible must-fire is blocked upstream)
        "AS-4": '_as4("1", "6")[0].verdict is Verdict.FIRED',
        "AS-5": "fire[0].verdict is Verdict.FIRED",
        "AS-6": 'by["bs"] is Verdict.FIRED',
        "AS-7": '_as7("5")[0].verdict is Verdict.FIRED',
        "AS-9": "test_pin_as9_bucket_c",  # cannot fire — bucket C (reported)
        "AS-10": '_as10("1")[0].verdict is Verdict.FIRED',
        "AS-11": "r[0].verdict is Verdict.FIRED",
        "AS-12": "test_as12_armor",
    }
    for rid, marker in markers.items():
        assert marker in src, (
            f"{rid} missing a must-fire (or a reported bucket-C blocker) — a rule with no fire case is NOT evaluated"
        )
