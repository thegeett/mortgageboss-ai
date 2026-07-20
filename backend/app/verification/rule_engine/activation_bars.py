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

from app.verification.rule_engine.registry import ACTIVE_RULE_IDS

_BARS_YAML = Path(__file__).resolve().parents[1] / "rules" / "activation_bars.yaml"
_SPECS_DIR = Path(__file__).resolve().parents[1] / "rules" / "specs"

_STATUSES = frozenset(
    {"calibratable-now", "not-calibratable-yet", "needs-producer", "no-ai-dependency"}
)
_SHIPS = frozenset({"auto", "ratify"})


class ActivationBarError(ValueError):
    """A malformed or incomplete activation-bar declaration (fail-loud, like the other declared loaders)."""


@dataclass(frozen=True)
class ActivationBar:
    """One inert rule's PROPOSED activation bar (Priya confirms). ``threshold`` is set only for
    ``calibratable-now``; ``validated`` is always false here."""

    rule_id: str
    status: str
    ships: str  # "auto" | "ratify" (from the rule's kind; LP-376-B)
    threshold: float | None  # the proposed default bar in [0,1], or None when no bar can apply
    validated: bool
    load_bearing_ai_tags: tuple[str, ...]
    fp_fn: str
    rationale: str


def _inert_rule_ids() -> frozenset[str]:
    """The rules with a spec that are NOT active — the set the bars must cover exactly."""
    specs = {p.stem for p in _SPECS_DIR.glob("*.yaml")}
    return frozenset(specs - set(ACTIVE_RULE_IDS))


@cache
def load_activation_bars() -> dict[str, ActivationBar]:
    """Load + validate every inert rule's proposed bar. Fail-loud on a missing/extra rule, a bad status/ships,
    a non-false ``validated``, or a threshold that is out of range or set on a non-calibratable rule."""
    raw = yaml.safe_load(_BARS_YAML.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ActivationBarError("activation_bars.yaml must be a mapping of rule_id -> bar")

    inert = _inert_rule_ids()
    declared = set(raw)
    if declared != inert:
        raise ActivationBarError(
            f"activation_bars.yaml must cover EXACTLY the inert rules. "
            f"missing={sorted(inert - declared)} extra={sorted(declared - inert)}"
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
    if validated is not False:
        raise ActivationBarError(
            f"{rule_id}: validated must be false — Priya's sign-off flips it, never this file"
        )
    if status == "calibratable-now":
        if not isinstance(threshold, int | float) or not (0.0 <= float(threshold) <= 1.0):
            raise ActivationBarError(
                f"{rule_id}: calibratable-now needs a proposed threshold in [0,1], got {threshold!r}"
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
    return ActivationBar(
        rule_id=rule_id,
        status=status,
        ships=ships,
        threshold=float(threshold) if threshold is not None else None,
        validated=False,
        load_bearing_ai_tags=tuple(str(t) for t in tags),
        fp_fn=str(body.get("fp_fn", "")).strip(),
        rationale=rationale,
    )


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
    "load_activation_bars",
    "parse_bar",
]
