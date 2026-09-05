"""LP-391 — pending-check surfacing: the THIRD rule state (applicable-but-manual).

Today a BLOCKED rule (not in ``ACTIVE_RULE_IDS`` — uncalibrated tag / missing producer) runs NOTHING, so a
file that qualifies for it produces SILENCE, which reads as "checked, nothing found" when it is really "didn't
look". For real-file testing (a processor on staging) that hides real issues.

This surfaces a blocked-but-APPLICABLE rule to Tab 1 (Needs Attention) as an explicit **manual-review flag** —
without shipping an uncalibrated verdict. The line is APPLICABILITY (safe: "this file HAS a gift / reserves /
income trend") vs VERDICT (uncalibrated: "this gift IS documented"): we surface the former, NEVER the latter.

THE GENERIC, DECLARED MECHANISM (no per-rule branch): evaluate each blocked candidate rule with the SAME
dispatch the live rules use; where it reaches a VERDICT (satisfied / fired / needs_review) it is applicable
AND its data is present but the rule is not trusted — so its would-be verdict is DISCARDED and a
``PENDING_AUTOMATION`` flag ships instead. Where it ``couldnt_check`` (data / producer absent — AS-7's NSF,
IN-14's rental support) or ``not_applicable`` (out of scope) it stays honestly DARK — no fabricated flag it
cannot support. This is neither live (a trusted verdict) nor inert (silence): the honest middle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult
from app.ai.stage_metrics import StageMetrics
from app.verification.rule_engine.activation_bars import load_activation_bars
from app.verification.rule_engine.judgment import Reasoner as JudgmentReasoner
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rule_engine.result import RuleEvaluation, Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.model import Snapshot

if TYPE_CHECKING:
    from app.verification.rule_engine.consistency import Reasoner as ConsistencyReasoner

# The verdicts that mean "applicable + data present" — the rule reached a real conclusion we simply do not
# trust yet. couldnt_check (data absent) and not_applicable (out of scope) are NOT here → they stay dark.
_SURFACEABLE = frozenset({Verdict.SATISFIED, Verdict.FIRED, Verdict.NEEDS_REVIEW})


async def _discarded_judgment_stub(_context_json: str) -> RuleJudgmentResult:
    """A no-op judgment for the pending pass. A judgment rule ALWAYS reaches needs_review when it is
    applicable with its tags present (the ratification-pending mandatory path) — regardless of the AI answer,
    which the pending pass then DISCARDS. So we never spend a REAL model call to compute a verdict we throw
    away (and, across a full run, never rate-limit the API on discarded judgments)."""
    return RuleJudgmentResult(
        judgment=RuleJudgment(
            value="unknown", confidence=None, reasoning="pending-check (verdict discarded)"
        ),
        input_tokens=0,
        output_tokens=0,
        model="pending-check-stub",
        truncated=False,
    )


def blocked_candidate_rule_ids() -> tuple[str, ...]:
    """Every rule with an activation bar that is NOT live — the blocked candidates (generic: bars minus the
    active set, never a hand-list). A base-active rule has no bar; an activated candidate is excluded here."""
    active = set(ACTIVE_RULE_IDS)
    return tuple(sorted(rid for rid in load_activation_bars() if rid not in active))


# The subject a collapsed flag is keyed under. A pending flag says "THIS FILE has something in scope",
# which is a statement about the file — so it is keyed at the loan, once, whatever the rule enumerates.
_FILE_SUBJECT = "loan"


def _to_pending(evaluation: RuleEvaluation, rule_name: str, in_scope: int) -> RuleEvaluation:
    """Convert a blocked rule's (untrusted) verdict into ONE manual-review flag for the whole rule.

    The would-be verdict, its confidence, and its load-bearing tag VALUES are DISCARDED (no leak) — only
    the fact that the rule is applicable survives, as a Needs-Attention flag naming the scope, never the
    judgment.

    ONE FLAG PER RULE, NOT ONE PER SUBJECT. This shipped per-subject and the first per-TRANSACTION
    blocked rule (FR-5) put SEVEN identical rows in front of a processor, each saying the same nothing:
    "something is in scope, the check is not active, review it manually." A loan-level rule made that
    one line; a per-transaction rule makes it N, and N copies of a sentence that carries no finding is
    noise that trains a reader to skip the whole tab — including the live findings beside it.
    The signal LP-391 exists to send is "this FILE has something in scope, and nothing looked at it".
    That is worth saying once, with a count.
    """
    return RuleEvaluation(
        rule_id=evaluation.rule_id,
        subject_id=_FILE_SUBJECT,
        verdict=Verdict.PENDING_AUTOMATION,
        verdict_confidence=None,
        load_bearing_tags=(),  # NEVER carry the uncalibrated tag values that drove the discarded verdict
        threshold_used=None,
        priya_validated=False,
        gated_pending_signoff=False,
        reasoning=(
            f"manual review needed — {_scope_phrase(in_scope)} in scope for the '{rule_name}' check, but "
            "that automated check is not active yet (its judgment is not calibrated). A processor must "
            "review it manually; the system has NOT judged it."
        ),
        how_to_fix="Review this item manually — the automated check is pending calibration, not a pass/fail.",
        ratification_pending=False,
    )


def _scope_phrase(in_scope: int) -> str:
    """How many subjects the blocked rule found — a COUNT is the one thing a collapsed flag can honestly
    add over "something is in scope", and it tells a processor how much manual work this is."""
    if in_scope <= 1:
        return "this file has something"
    return f"this file has {in_scope} items"


async def evaluate_pending_checks(
    snapshot: Snapshot,
    *,
    judgment_reasoners: dict[str, JudgmentReasoner] | None = None,
    consistency_reasoners: dict[str, ConsistencyReasoner] | None = None,
    confidence_floor: float | None = None,
    metrics: StageMetrics | None = None,
) -> list[RuleEvaluation]:
    """The pending-check pass: for every BLOCKED candidate rule, evaluate it and — where it reaches a
    surfaceable verdict — emit a ``PENDING_AUTOMATION`` manual-review flag INSTEAD (never the verdict).

    Additive: it evaluates a DISJOINT rule set from the live pass (blocked ≠ active), so the live verdicts
    are untouched. Returns only ``PENDING_AUTOMATION`` evaluations — no satisfied/fired/needs_review from an
    uncalibrated rule ever escapes."""
    blocked = blocked_candidate_rule_ids()
    if not blocked:
        return []
    # Stub every blocked JUDGMENT rule so the pass never spends a real model call on a verdict it discards
    # (an unstubbed judgment rule would hit the real API — and, run over a whole loan file's worth of blocked
    # rules, rate-limit it). A caller-supplied reasoner (e.g. OC-2) still wins.
    judge_reasoners = dict(judgment_reasoners or {})
    for rule_id in blocked:
        if rule_id not in judge_reasoners and load_rule_spec(rule_id).judgment is not None:
            judge_reasoners[rule_id] = _discarded_judgment_stub
    results, _judgment_tags = await evaluate_rules(
        snapshot,
        judgment_reasoners=judge_reasoners,
        consistency_reasoners=consistency_reasoners or {},
        confidence_floor=confidence_floor,
        rule_ids=blocked,
        # LP-644 §1 review — this pass is best-effort and its verdicts are discarded, but the run
        # WAITS for it: a blocked consistency rule still calls the model. Measured, not assumed free.
        metrics=metrics,
    )
    # Collapsed per rule, in first-seen order so the output is deterministic across runs.
    surfaceable: dict[str, list[RuleEvaluation]] = {}
    for evaluation in results:
        # `pending_surface: false` (LP-549) — the rule declares that its APPLICABILITY carries no signal,
        # so a flag saying "something is in scope" would report normality as a finding.
        if (
            evaluation.verdict in _SURFACEABLE
            and load_rule_spec(evaluation.rule_id).pending_surface
        ):
            surfaceable.setdefault(evaluation.rule_id, []).append(evaluation)
    return [
        _to_pending(group[0], load_rule_spec(rule_id).name, len(group))
        for rule_id, group in surfaceable.items()
    ]


__all__ = ["blocked_candidate_rule_ids", "evaluate_pending_checks"]
