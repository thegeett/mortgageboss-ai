"""LP-380 — activation bars: the declared decision surface for which inert rules may go live.

An activation bar is the accuracy a rule's load-bearing AI tags must reach before the rule ships a TRUSTED
(auto, non-ratified) verdict. It CANNOT be computed — its height is the cost of error for that rule, a DOMAIN
judgment (Priya's). This module LOADS the proposed defaults (``activation_bars.yaml``), resolved per rule by
the registry (declared-key-resolved-by-registry — no per-rule evaluator branch), each ``validated=false`` until
Priya signs off. It SETS no bar and ACTIVATES nothing (that is LP-389).

The bar reconciles with LP-376-B's ratification armor as ONE safety with two settings, not a parallel one:
``activation_mode`` routes a below-bar auto-ship rule to ``needs_review`` and a judgment rule to ``ratify`` —
never an untrusted auto-ship. A rule whose tags are UNMEASURED is ``blocked`` (not "bar unmet"): distinct, so a
rule never ships on a tag nobody measured.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

from app.verification.rule_engine.registry import _BASE_ACTIVE
from app.verification.rules.kinds import RuleKindName, kind_for

_BARS_YAML = Path(__file__).resolve().parents[1] / "rules" / "activation_bars.yaml"
_SPECS_DIR = Path(__file__).resolve().parents[1] / "rules" / "specs"

# LP-411 — "no-ai-threshold-pending" is the THIRD eligibility case: no AI tag to calibrate, but a Priya
# THRESHOLD (a window/limit, not an AI accuracy) still needs sign-off. no-ai-dependency activates on
# input_resolves alone (nothing to sign off); no-ai-threshold-pending ALSO requires `validated` (her threshold
# sign-off). It exists because the SPEC/CSV `threshold_needs_signoff` flag is CALCULATIVE-ONLY (kinds.py rejects
# it on a structural rule), so PC-7 (structural, with a closing window) could not declare its sign-off there —
# and holding it on a plain no-ai bar required a FALSE `input_resolves: false` (LP-406-1b's stand-in). This
# status lets `validated` gate a no-AI rule honestly (input_resolves stays TRUE). See ADR-327.
_STATUSES = frozenset(
    {
        "calibratable-now",
        "not-calibratable-yet",
        "needs-producer",
        "no-ai-dependency",
        "no-ai-threshold-pending",
        # LP-490a / ADR-378 — activation on a SELF-CONSISTENCY rate instead of a measured accuracy, with
        # RATIFICATION as the safety substitute. ⚠️ This INVERTS the gate's stated principle ("activation
        # never trusts what it hasn't measured"): a deliberate product decision, taken with the trade-offs
        # recorded in ADR-378. A rule on this status must ratify EVERY finding it produces.
        "ratify-pending",
    }
)
_SHIPS = frozenset({"auto", "ratify"})


class ActivationBarError(ValueError):
    """A malformed or incomplete activation-bar declaration (fail-loud, like the other declared loaders)."""


@dataclass(frozen=True)
class ActivationBar:
    """One inert rule's activation bar. ``threshold`` is set only for ``calibratable-now``; ``validated`` is
    Priya's sign-off — False by default, True on the bars she has confirmed (IN-1/IN-5). Validating a bar does
    NOT activate the rule (that is LP-389); it records that the height is domain-approved."""

    rule_id: str
    status: str
    ships: str  # "auto" | "ratify" (from the rule's kind; LP-376-B)
    threshold: float | None  # the proposed default bar in [0,1], or None when no bar can apply
    validated: bool
    load_bearing_ai_tags: tuple[str, ...]
    fp_fn: str
    rationale: str
    # LP-389 — the eligibility evidence. ``measured_accuracy`` is the load-bearing tags' MEASURED accuracy
    # (LP-379), used with the validated bar to gate an AI rule; None when unmeasured. ``input_resolves`` is
    # the no-AI verification that the parsed input RESOLVES to real values on a real file (LP-381), used to
    # gate a no-ai-dependency rule. Both default to the fail-closed value (None / False).
    measured_accuracy: float | None = None
    input_resolves: bool = False
    # LP-490a / ADR-378 — the SELF-CONSISTENCY evidence. ⚠️ THIS IS NOT AN ACCURACY, and the field is
    # named for what it measures. It is the rate at which TWO INDEPENDENT derivations of the same tag,
    # from the same source data in FRESH contexts, agreed with each other. Two agreeing derivations are
    # STABLE, not RIGHT: a systematically wrong tag scores 1.0. Disagreement is a real signal;
    # agreement is weak evidence.
    #
    # ⚠️ IT MUST NEVER BE COLLAPSED INTO measured_accuracy. That field means "a human said what the
    # right answer was". This one means "the model said the same thing twice". A loader check rejects a
    # bar carrying both, because the distinction is the only thing telling a future reader which is
    # which — and `is_eligible` reads this field ONLY on the ratify-pending branch.
    self_consistency_rate: float | None = None
    self_consistency_cases: int | None = None
    self_consistency_disagreements: int | None = None
    self_consistency_model: str | None = None
    self_consistency_date: str | None = None
    # LP-495b review — THE DECLARED OVERRIDE, and the only way a bar may carry BOTH numbers. Written prose, not a
    # flag: activating a rule whose load-bearing tag was MEASURED BELOW ITS SIBLING'S BAR is a deliberate
    # product decision, and the decision has to be READABLE where the numbers sit. None (the default) keeps
    # the LP-490a separation absolute for every other bar — both fields present with no override is still a
    # load error. `is_eligible` reads it ONLY on the ratify-pending branch, and only to let a bar that has
    # written its reasoning down proceed; a bar that stays silent about a measurement is still held.
    measured_accuracy_override: str | None = None


def _candidate_rule_ids() -> frozenset[str]:
    """The rules the bars must cover exactly — every spec NOT in the BASE (pre-LP-389) active set. Anchored to
    ``_BASE_ACTIVE``, not the live ``ACTIVE_RULE_IDS``, so an activated rule (IN-1/IN-5/ID-5) KEEPS its bar as
    the record of why it went live — the candidate set stays a stable 23, not shrinking as rules activate."""
    specs = {p.stem for p in _SPECS_DIR.glob("*.yaml")}
    return frozenset(specs - set(_BASE_ACTIVE))


@cache
def load_activation_bars() -> dict[str, ActivationBar]:
    """Load + validate every inert rule's proposed bar. Fail-loud on a missing/extra rule, a bad status/ships,
    a non-false ``validated``, or a threshold that is out of range or set on a non-calibratable rule."""
    raw = yaml.safe_load(_BARS_YAML.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ActivationBarError("activation_bars.yaml must be a mapping of rule_id -> bar")

    candidates = _candidate_rule_ids()
    declared = set(raw)
    if declared != candidates:
        raise ActivationBarError(
            f"activation_bars.yaml must cover EXACTLY the candidate (non-base) rules. "
            f"missing={sorted(candidates - declared)} extra={sorted(declared - candidates)}"
        )

    return {rule_id: parse_bar(rule_id, body) for rule_id, body in raw.items()}


def parse_bar(rule_id: str, body: object) -> ActivationBar:
    """Parse + validate ONE rule's bar (fail-loud). Separated so the invariants — validated=false, a threshold
    only when calibratable-now, a known status/ships, a non-blank rationale — are directly testable."""
    if not isinstance(body, dict):
        raise ActivationBarError(f"{rule_id}: bar must be a mapping")
    status = str(body.get("status", ""))
    ships = str(body.get("ships", ""))
    threshold = body.get("threshold")
    validated = body.get("validated")
    if status not in _STATUSES:
        raise ActivationBarError(f"{rule_id}: unknown status {status!r}")
    if ships not in _SHIPS:
        raise ActivationBarError(f"{rule_id}: ships must be auto|ratify, got {ships!r}")
    # LP-424 (item 3) — a bar's ``ships`` must AGREE with the rule's KIND (rule_kinds.csv). A JUDGMENTAL rule
    # NEVER auto-ships (LP-376-B: a human ratifies every judgment; judgment.py hard-codes ratification_pending),
    # so a bar declaring ``ships: auto`` on a judgmental rule is a LIE — the runtime ratifies regardless, and the
    # bar would mis-state the rule's shipping mode to a reader/census. Fail loud (the LP-390-7 AS-5 pattern), the
    # same way an out-of-range threshold does. (The loader CAN see the kind — rule_kinds.csv via kind_for — so
    # this guard is implementable here; it is not a calc-only field like threshold_needs_signoff, LP-411.)
    kind = kind_for(rule_id)
    if ships == "auto" and kind is not None and kind.kind is RuleKindName.JUDGMENTAL:
        raise ActivationBarError(
            f"{rule_id}: ships=auto contradicts its judgmental kind — a judgment rule never auto-ships "
            "(a human ratifies every verdict, LP-376-B); the bar must declare ships: ratify"
        )
    # ``validated`` is Priya's sign-off (LP-380 flipped none; her sign-offs flip specific bars, e.g. IN-1/IN-5).
    # It must be an explicit bool, and only a calibratable-now rule with a real threshold may be validated —
    # a rule blocked on calibration can never be signed off as live-able.
    if not isinstance(validated, bool):
        raise ActivationBarError(
            f"{rule_id}: validated must be a boolean (true = Priya-confirmed), got {validated!r}"
        )
    if status == "calibratable-now":
        # `not isinstance(threshold, bool)` — a YAML bool is an int in Python (bool ⊂ int), so `threshold:
        # true` would otherwise coerce to a silent 1.0 bar instead of failing loud like the other typos.
        if (
            not isinstance(threshold, int | float)
            or isinstance(threshold, bool)
            or not (0.0 <= float(threshold) <= 1.0)
        ):
            raise ActivationBarError(
                f"{rule_id}: calibratable-now needs a proposed threshold in [0,1], got {threshold!r}"
            )
    elif validated and status != "no-ai-threshold-pending":
        # LP-411: no-ai-threshold-pending MAY be validated (Priya's threshold sign-off is what activates it).
        # Every OTHER non-calibratable status is BLOCKED and cannot be signed off as live-able.
        raise ActivationBarError(
            f"{rule_id}: only a calibratable-now or no-ai-threshold-pending rule may be validated "
            f"(status={status}) — a rule blocked on calibration/a producer cannot be signed off as live-able"
        )
    elif threshold is not None:
        raise ActivationBarError(
            f"{rule_id}: threshold must be null unless calibratable-now (status={status}) — an "
            f"unmeasured rule is BLOCKED ON CALIBRATION, not sitting under a bar"
        )
    tags = body.get("load_bearing_ai_tags") or []
    if not isinstance(tags, list):
        raise ActivationBarError(f"{rule_id}: load_bearing_ai_tags must be a list")
    rationale = str(body.get("rationale", "")).strip()
    if not rationale:
        raise ActivationBarError(
            f"{rule_id}: a rationale is required (the proposal Priya reasons over)"
        )
    # LP-389 eligibility evidence. measured_accuracy (bool ⊂ int guard, like threshold) is optional in [0,1];
    # input_resolves is a bool defaulting to the fail-closed False, and only a no-ai-dependency rule may set it
    # true (a rule's parsed input resolving is only the gate when it HAS no AI tag to measure).
    measured_accuracy = body.get("measured_accuracy")
    if measured_accuracy is not None and (
        not isinstance(measured_accuracy, int | float)
        or isinstance(measured_accuracy, bool)
        or not (0.0 <= float(measured_accuracy) <= 1.0)
    ):
        raise ActivationBarError(
            f"{rule_id}: measured_accuracy must be a number in [0,1] or null, got {measured_accuracy!r}"
        )
    input_resolves = body.get("input_resolves", False)
    if not isinstance(input_resolves, bool):
        raise ActivationBarError(
            f"{rule_id}: input_resolves must be a boolean, got {input_resolves!r}"
        )
    # LP-411: input_resolves is the parsed-input evidence for BOTH no-ai statuses (no-ai-dependency gates on it
    # alone; no-ai-threshold-pending gates on it AND validated).
    if input_resolves and status not in (
        "no-ai-dependency",
        "no-ai-threshold-pending",
        # LP-490a — a ratify-pending rule DOES gate on input_resolves (its inputs must materialize)
        # alongside its self-consistency rate.
        "ratify-pending",
    ):
        raise ActivationBarError(
            f"{rule_id}: input_resolves is the gate ONLY for a no-ai rule (status={status})"
        )
    # --- LP-490a / ADR-378 — the self-consistency evidence, and the separation it must keep. ---
    self_consistency_rate = body.get("self_consistency_rate")
    if self_consistency_rate is not None and (
        not isinstance(self_consistency_rate, int | float)
        or isinstance(self_consistency_rate, bool)
        or not (0.0 <= float(self_consistency_rate) <= 1.0)
    ):
        raise ActivationBarError(
            f"{rule_id}: self_consistency_rate must be a number in [0,1] or null, got "
            f"{self_consistency_rate!r}"
        )
    # ⚠️ THE NON-NEGOTIABLE SEPARATION. `measured_accuracy` means A HUMAN SAID WHAT THE RIGHT ANSWER WAS.
    # `self_consistency_rate` means THE MODEL SAID THE SAME THING TWICE. Collapsing them destroys the only
    # signal telling a future reader which kind of number a bar carries — so a bar carrying both is
    # rejected at LOAD, not quietly preferred one way at read time.
    # LP-495b review — the ONE exception, and it is a DECLARATION, not a loosening. A bar may carry both numbers
    # when it also writes down WHY the measurement does not hold it (`measured_accuracy_override`). The
    # separation the block above protects is preserved: the two fields still mean different things and are
    # still stored apart — what changes is that a bar can no longer ACHIEVE eligibility by omitting a
    # measurement it knows about. Dropping the number was the cheaper path; this makes writing it down the
    # cheaper path.
    override = body.get("measured_accuracy_override")
    if override is not None and not isinstance(override, str):
        raise ActivationBarError(
            f"{rule_id}: measured_accuracy_override must be a string (the written reasoning), got "
            f"{override!r}"
        )
    override = override.strip() if isinstance(override, str) else None
    override = override or None
    if self_consistency_rate is not None and measured_accuracy is not None and override is None:
        raise ActivationBarError(
            f"{rule_id}: a bar cannot carry BOTH measured_accuracy and self_consistency_rate — one means a "
            f"human labelled the right answer, the other means the model agreed with itself. Keep them "
            f"apart, or a consistency number will later be read as an accuracy. To activate DESPITE a "
            f"measurement, declare measured_accuracy_override with the reasoning — never drop the number."
        )
    if override is not None and (self_consistency_rate is None or measured_accuracy is None):
        raise ActivationBarError(
            f"{rule_id}: measured_accuracy_override is only meaningful on a bar carrying BOTH a "
            f"measured_accuracy and a self_consistency_rate — there is nothing to override otherwise"
        )
    if override is not None and status != "ratify-pending":
        raise ActivationBarError(
            f"{rule_id}: measured_accuracy_override applies only to a ratify-pending bar (status="
            f"{status}) — ratification of every finding is what makes overriding a measurement survivable"
        )
    if status == "ratify-pending" and self_consistency_rate is None:
        raise ActivationBarError(
            f"{rule_id}: a ratify-pending bar needs a self_consistency_rate (or it is simply unmeasured "
            f"and belongs at not-calibratable-yet)"
        )
    cases = body.get("self_consistency_cases")
    disagreements = body.get("self_consistency_disagreements")
    # ⚠️ A RATE WITHOUT A CASE COUNT IS UNREADABLE. A 1.0 over 2 cases and a 1.0 over 200 are different
    # claims, and the bar must say which.
    # ⚠️ `isinstance(True, int)` is True in Python, so `self_consistency_cases: true` loaded as ONE case
    # and passed the `> 0` guard this same block calls non-negotiable. The rate check next to it
    # already excludes bool; this one did not (reported finding).
    if self_consistency_rate is not None and (
        not isinstance(cases, int) or isinstance(cases, bool)
    ):
        raise ActivationBarError(
            f"{rule_id}: a self_consistency_rate needs self_consistency_cases — a rate with no case count "
            f"cannot be read"
        )
    if self_consistency_rate is not None and int(cases or 0) <= 0:
        raise ActivationBarError(
            f"{rule_id}: self_consistency_cases must be > 0 — a rate over ZERO cases is not a number, and "
            f"a rule with no instances of its trigger must stay held with a null rate"
        )
    # LP-411 (the LP-390-7 fail-loud pattern): a no-ai-threshold-pending bar SIGNED OFF (validated) to go live
    # must have a RESOLVING input — you cannot sign off a threshold to activate a rule whose input does not
    # resolve. Reject the contradiction at LOAD rather than let is_eligible silently hold it.
    if status == "no-ai-threshold-pending" and validated and not input_resolves:
        raise ActivationBarError(
            f"{rule_id}: a validated no-ai-threshold-pending bar must have input_resolves: true — a threshold "
            f"sign-off cannot activate a rule whose parsed input does not resolve"
        )
    return ActivationBar(
        rule_id=rule_id,
        status=status,
        ships=ships,
        threshold=float(threshold) if threshold is not None else None,
        validated=validated,
        load_bearing_ai_tags=tuple(str(t) for t in tags),
        fp_fn=str(body.get("fp_fn", "")).strip(),
        rationale=rationale,
        measured_accuracy=float(measured_accuracy) if measured_accuracy is not None else None,
        input_resolves=input_resolves,
        self_consistency_rate=(
            float(self_consistency_rate) if self_consistency_rate is not None else None
        ),
        self_consistency_cases=(
            int(cases) if isinstance(cases, int) and not isinstance(cases, bool) else None
        ),
        self_consistency_disagreements=(
            int(disagreements) if isinstance(disagreements, int) else None
        ),
        self_consistency_model=(
            str(body["self_consistency_model"]) if body.get("self_consistency_model") else None
        ),
        self_consistency_date=(
            str(body["self_consistency_date"]) if body.get("self_consistency_date") else None
        ),
        measured_accuracy_override=override,
    )


def is_eligible(bar: ActivationBar) -> bool:
    """LP-389 — the ACTIVATION GATE, fail-closed. A rule may go live ONLY if:

    * (AI rule) it is ``calibratable-now``, its bar is Priya-``validated``, and its MEASURED accuracy meets
      the bar (accuracy >= threshold — which is exactly ``activation_mode`` == auto/ratify); OR
    * (no-AI rule, no threshold) it is ``no-ai-dependency`` and its parsed ``input_resolves`` (verified); OR
    * (no-AI rule, threshold) it is ``no-ai-threshold-pending`` and its input ``input_resolves`` AND its
      threshold (a window/limit) is Priya-``validated`` (LP-411 — the third case).

    Every other state — an unmeasured tag (``not-calibratable-yet``), an unvalidated bar, a missing accuracy,
    an absent input, or ``needs-producer`` — is NOT eligible. When in doubt, hold. This is the inverse of the
    run-level fail-opens: activation never trusts what it hasn't measured."""
    if bar.status == "calibratable-now":
        return (
            bar.validated
            and bar.threshold is not None
            and bar.measured_accuracy is not None
            and bar.measured_accuracy >= bar.threshold
        )
    if bar.status == "no-ai-dependency":
        return bar.input_resolves
    if bar.status == "no-ai-threshold-pending":
        # LP-411: no AI to measure, but a domain threshold to sign off — held until BOTH the input resolves
        # AND Priya validates the window. (input_resolves stays honest; `validated` is the real hold.)
        return bar.input_resolves and bar.validated
    if bar.status == "ratify-pending":
        # LP-490a / ADR-378 — ⚠️ THE ONE BRANCH THAT ACTIVATES ON SOMETHING OTHER THAN A MEASUREMENT.
        # A self-consistency rate is NOT evidence of correctness (see the field's note), so ratification
        # is the substitute safety: every finding such a rule produces carries ratification_pending=True
        # (enforced in deterministic.py and judgment.py, proven per rule by test), so a wrong tag costs a
        # processor's attention and can never auto-assert.
        #
        # ⚠️ `measured_accuracy is None` IS LOAD-BEARING, not belt-and-braces. A rule whose tag was
        # MEASURED and FAILED is measured-and-failing, not unmeasured, and must stay held — AS-4's
        # stmt.is_reserve_eligible measured 0/5 against Priya's labels (LP-390-5), a systematic domain
        # disagreement that two agreeing derivations would score 1.0 on precisely because the model is
        # consistently wrong. This clause is what stops a self-consistency rate overriding a real
        # measurement.
        #
        # LP-495b review — `measured_accuracy_override` is the ONE way past it, and it is a WRITTEN one. The clause
        # above had a cheaper escape than it looked: a bar could simply OMIT a measurement it knew about
        # (`parse_bar` rejected a bar carrying both numbers, so omitting was the only way to record a rate
        # at all) and the guard would read the rule as unmeasured. IN-13 shipped that way — its
        # income.continuance_3yr scored 5/6 in LP-427 and the number lived in prose while the field stayed
        # None. So the number is now recordable ALONGSIDE the rate, and getting past the guard costs a
        # declared justification instead of a deletion. AS-4 is unaffected: a 0/5 tag with no override
        # written is still held, exactly as before.
        return (
            bar.input_resolves
            and bar.self_consistency_rate is not None
            and (bar.measured_accuracy is None or bar.measured_accuracy_override is not None)
        )
    return False


def ratifies_every_finding(rule_id: str) -> bool:
    """Is this rule activated on a self-consistency rate, and therefore required to ratify everything?

    ⚠️ The deterministic evaluator calls this. Ratification is the ENTIRE safety substitute for
    measurement on a ratify-pending rule (ADR-378), so it has to be enforced where the verdict is built,
    not asserted in a comment — `deterministic.py` never set the flag before LP-490a, which would have
    shipped every ai_fuzzy_match rule with no human in the loop.
    """
    bar = load_activation_bars().get(rule_id)
    return bar is not None and bar.status == "ratify-pending"


def eligible_rule_ids() -> tuple[str, ...]:
    """The candidate rules that PASS the activation gate today (sorted) — what LP-389 activated."""
    return tuple(sorted(rid for rid, bar in load_activation_bars().items() if is_eligible(bar)))


def activation_mode(bar: ActivationBar, measured_accuracy: float | None) -> str:
    """The activation verdict mode for a rule at a MEASURED accuracy — the reconciliation with LP-376-B (one
    safety, two settings), pure and declarative (LP-389 wires it; this ticket decides nothing live):

    * ``blocked``      — not calibratable-now (no measured accuracy to clear a bar) → cannot go live.
    * ``ratify``       — a judgment rule (ships=ratify) → NEVER auto-ships (LP-376-B); a human ratifies.
    * ``auto``         — calibratable, auto-ship, accuracy >= the proposed bar → a TRUSTED verdict.
    * ``needs_review`` — calibratable, auto-ship, accuracy < the bar → below-bar routes to a human, not auto.
    """
    if bar.status != "calibratable-now" or bar.threshold is None:
        return "blocked"
    if bar.ships == "ratify":
        return "ratify"
    if measured_accuracy is None:
        return "needs_review"
    return "auto" if measured_accuracy >= bar.threshold else "needs_review"


__all__ = [
    "ActivationBar",
    "ActivationBarError",
    "activation_mode",
    "eligible_rule_ids",
    "is_eligible",
    "load_activation_bars",
    "parse_bar",
]
