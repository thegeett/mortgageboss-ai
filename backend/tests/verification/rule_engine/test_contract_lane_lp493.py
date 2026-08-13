"""LP-493 — PC-8 (activated), PC-5 (built, held) and PC-1 (dropped).

⚠️ EVERY VERDICT ASSERTION RUNS THROUGH A REAL RULE EVALUATION (LP-487's standing rule).

⚠️ n=5, AND FREE-TEXT CONTRACTS ARE THE LEAST RELIABLE DOCUMENT CLASS IN THE CORPUS: of ~8
purchase-agreement claims in the bench, ONE was real — the free reader projected Texas TREC fields onto a
North Carolina form. These tests prove wiring and direction, not accuracy.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.rule_engine.activation_bars import is_eligible, load_activation_bars
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


def _contract_snapshot(**fields: str) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 13, tzinfo=UTC),
        documents=DocumentsSection.present(
            [
                DocumentEntry(
                    content_id="pa-1",
                    document_type="purchase_agreement",
                    belongs_to=None,
                    fields={
                        k: Field.present(v, source=FieldSource.EXTRACTED)
                        for k, v in {"sales_price": "400000.00", **fields}.items()
                    },
                )
            ]
        ),
        mismo=MismoSection.present({}),
        tags=TagsSection.present({}),
    )


# --------------------------------------------------------------------------- #
# ⚠️ PC-8 SURFACES — it has NO firing path
# --------------------------------------------------------------------------- #
def test_pc8_has_no_firing_path() -> None:
    """⚠️ The catalog rationale is "SURFACE included personal property — judgment", and a judgmental rule
    has exactly two exits: needs_review and couldnt_check. PC-8 tells a processor what the contract
    includes; a human decides whether it is material. If someone gives it a `fired` path, this fails."""
    spec = load_rule_spec("PC-8")
    assert spec.judgment is not None
    assert spec.deterministic is None, "a judgment rule must not carry a deterministic body"
    assert "included" in spec.judgment.value_domain
    assert "fixtures_only" in spec.judgment.value_domain


def test_pc8_computes_no_deduction() -> None:
    """⚠️ Non-realty items are deducted from the sales price for LTV under the sales-concessions topic
    (tier S — the IPC page, whose per-cell table was NOT fetched). PC-8 carries no number and applies
    none: it surfaces, and the deduction belongs to the LTV lane if it is ever built."""
    values = load_rule_spec("PC-8").reference_values.values
    assert "none" in values["materiality_threshold"]


async def test_pc8_findings_carry_ratification(monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ RATIFICATION IS THE SAFETY SUBSTITUTE for the missing measurement (ADR-378), proven through the
    REAL evaluator — never by calling the mechanism (LP-487; LP-508's guard passed that way and reached
    1 of 5 rules)."""
    from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult

    async def judge(_context_json: str) -> RuleJudgmentResult:
        return RuleJudgmentResult(
            judgment=RuleJudgment(value="included", confidence=0.9, reasoning="scripted"),
            input_tokens=1,
            output_tokens=1,
            model="stub-pc",
            truncated=False,
        )

    # ⚠️ A PARTIAL SEAM IS NOT A SEAM (LP-490): stub EVERY group, then override the one under test.
    # `only_groups=frozenset()` skips AI groups entirely, which would leave the tag ABSENT and the rule
    # gated to couldnt_check — the finding would never be produced and the assertion would be vacuous.
    from app.verification.eval.stubs import stub_materialization_reasoners
    from app.verification.tag_materialization.ai import (
        AiGroupResult,
        AiSubjectJudgment,
        AiTagJudgment,
    )

    async def group(context_json: str) -> AiGroupResult:
        import json as _json

        subjects = _json.loads(context_json).get("subjects", [])
        return AiGroupResult(
            [
                AiSubjectJudgment(
                    index=int(s["index"]),
                    tags={"personal_property": AiTagJudgment("yes", 0.9, "scripted")},
                )
                for s in subjects
            ],
            input_tokens=1,
            output_tokens=1,
            model="stub-pc",
            truncated=False,
        )

    snapshot = await materialize_tags(
        _contract_snapshot(personal_property_included="Refrigerator, Washer/Dryer"),
        ai_reasoners={**stub_materialization_reasoners(), "contract_personal_property": group},
    )
    evaluations, _tags = await evaluate_rules(
        snapshot, rule_ids=("PC-8",), judgment_reasoners={"PC-8": judge}
    )
    asserted = [e for e in evaluations if e.verdict is Verdict.NEEDS_REVIEW]
    assert asserted, "PC-8 produced no asserting finding"
    assert all(e.ratification_pending for e in asserted)
    assert Verdict.FIRED not in [e.verdict for e in evaluations]


def test_pc8_is_live_on_a_two_valued_spread() -> None:
    """⚠️ THE STRONGEST RATE IN ANY COHORT SO FAR — and still only 5 cases. Unlike LP-492's
    single-verdict spreads, both derivations produced a genuinely two-valued answer, so the rate reflects
    the model agreeing on DIFFERENT answers rather than agreeing on one."""
    bar = load_activation_bars()["PC-8"]
    assert bar.status == "ratify-pending"
    assert bar.self_consistency_rate == 1.0 and bar.self_consistency_cases == 5
    assert bar.measured_accuracy is None
    assert is_eligible(bar) and "PC-8" in ACTIVE_RULE_IDS


# --------------------------------------------------------------------------- #
# ⚠️ PC-5 — built, HELD on a uniform-abstain derivation
# --------------------------------------------------------------------------- #
def test_pc5_is_held_not_activated() -> None:
    """⚠️ THE TICKET'S OWN PRE-RATE CHECK 2: refuse to record a rate when every derivation returned the
    same abstain value. PC-5's ran cleanly on LF-6T3N — calls succeeded, context non-redacted — but the
    spread was {unknown: 2}. A rate over a uniform abstain is the CR-8 shape: perfectly consistent and
    carrying no information. Not recorded, so PC-5 stays held."""
    bar = load_activation_bars()["PC-5"]
    assert bar.status == "not-calibratable-yet"
    assert bar.self_consistency_rate is None, "a uniform-abstain rate must not be recorded"
    assert not is_eligible(bar)
    assert "PC-5" not in ACTIVE_RULE_IDS


def test_pc5_encodes_no_customary_threshold() -> None:
    """⚠️ B3-4.3-09 says large deposits and those exceeding what is "customary for the area" should be
    closely evaluated — and gives NO number. None is invented; a fabricated percentage would fire on
    ordinary files."""
    values = load_rule_spec("PC-5").reference_values.values
    assert "not defined" in values["customary_deposit_threshold"]


def test_pc5_records_the_single_emd_input_gap() -> None:
    """⚠️ Doc 183 understated a $204k ADDITIONAL earnest money distinct from the primary figure.
    `earnest_money_amount` is singular and NO `additional_earnest_money_amount` field exists, so a second
    deposit is LOST. The prompt asks the model to name one in its reasoning; the tag cannot carry it."""
    assert "additional" in load_rule_spec("PC-5").evidence_required.lower()


# --------------------------------------------------------------------------- #
# ⚠️ PC-1 — dropped, and the reasons pinned so it is not rebuilt hollow
# --------------------------------------------------------------------------- #
def test_pc1_is_not_live_and_its_tags_stay_undeclared() -> None:
    """⚠️ PC-1 IS DROPPED, for two independent reasons:

    1. `title.parties_match` ("Title parties match borrowers/seller") asks the SAME question TI-1 already
       answers with `title.vested_owner_matches` — live, deterministic and proven at LP-491. Building it
       would put a SECOND MATCHER on one comparison, which is exactly what LP-483 forbade for CR-1/CR-4.
    2. `contract.arms_length`'s only schema field, `parties_relationship_disclosed`, is **0/5** on the
       real contracts — TI-3/4/5's shape (ADR-354: a field existing is not a field populating).

    Both tags stay UNDECLARED. If someone declares one against an invented source, this fails."""
    declared = load_declarations()
    assert "title.parties_match" not in declared
    assert "contract.arms_length" not in declared
    assert "PC-1" not in ACTIVE_RULE_IDS
    # TI-1's tag — the live answer to the same question — is declared and stays that way.
    assert "title.vested_owner_matches" in declared
