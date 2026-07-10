"""Rule-kind classification loader (LP-301, ADR-247) — the Stage-2 routing table.

Reads the canonical, version-controlled ``rule_kinds.csv`` (one row per rule) — the
single source of truth for how the Stage-2 orchestrator routes each rule to an
evaluation path, and for the Priya-validation gate. This is a thin read; the CSV is
authoritative. No engine logic here (LP-304+ owns the evaluator).

Four **kinds** and their evaluation paths (architecture v2 §3C):

* ``calculative`` — deterministic pre-computes arithmetic → AI judges which inputs
  apply → deterministic re-verifies the final comparison (the *bookend*). Every
  calculative rule is ``numeric_check=True``. Path ``deterministic_bookend+ai`` when
  AI selects inputs, else ``deterministic_bookend``.
* ``structural`` — a deterministic check (presence / exact-match / count / date).
  AI is used ONLY for **fuzzy** entity matches (name/address/employer). So each
  structural rule is either **exact** (``exact_match=True`` → ``deterministic_only``,
  no AI) or **fuzzy** (``exact_match=False`` → ``ai_fuzzy_match``).
* ``judgmental`` — pure AI evaluation + human ratification (``ai_judgment``); no
  deterministic component.
* ``out_of_scope`` — not evaluated by this engine (external service / LOS-owned TRID
  / post-submission / unsupported program) → ``static_filter``, never routed to AI.

The Priya-validation gate: every rule starts ``priya_validated=False``; a calculative
rule carrying a regulatory threshold/window/limit/factor is ``threshold_needs_signoff
=True`` and must be signed off before it ships. LP-301 only *tracks* this — it invents
no sign-offs.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

# The canonical artifact — plain-text, git-diffable, co-located with the rules.
_CSV_PATH = Path(__file__).with_name("rule_kinds.csv")


class RuleKindName(StrEnum):
    """The four evaluation kinds (architecture v2 §3C)."""

    CALCULATIVE = "calculative"
    STRUCTURAL = "structural"
    JUDGMENTAL = "judgmental"
    OUT_OF_SCOPE = "out_of_scope"


class EvaluationPath(StrEnum):
    """How a rule is evaluated — the orchestrator routes on this."""

    DETERMINISTIC_BOOKEND_AI = "deterministic_bookend+ai"  # calc: AI selects inputs
    DETERMINISTIC_BOOKEND = "deterministic_bookend"  # calc: no AI input selection
    DETERMINISTIC_ONLY = "deterministic_only"  # structural exact — NO AI
    AI_FUZZY_MATCH = "ai_fuzzy_match"  # structural fuzzy entity match
    AI_JUDGMENT = "ai_judgment"  # judgmental
    STATIC_FILTER = "static_filter"  # out-of-scope — never routed to AI


@dataclass(frozen=True)
class RuleKind:
    """One rule's classification + routing + validation-gate state."""

    rule_id: str
    name: str
    category: str
    kind: RuleKindName
    evaluation_path: EvaluationPath
    numeric_check: bool  # calculative rules that get the deterministic bookend
    exact_match: bool | None  # structural only: exact (det-only) vs fuzzy (AI); else None
    priya_validated: bool  # flips True only when Priya confirms (LP-301: always False)
    threshold_needs_signoff: bool  # calc w/ a regulatory threshold — sign off before ship
    rationale: str


def _to_bool(value: str) -> bool:
    return value.strip().lower() == "true"


def _to_opt_bool(value: str) -> bool | None:
    v = value.strip().lower()
    return None if v == "" else v == "true"


@lru_cache(maxsize=1)
def load_rule_kinds() -> dict[str, RuleKind]:
    """Load the routing table → ``{rule_id: RuleKind}`` (cached; the CSV is source of truth)."""
    out: dict[str, RuleKind] = {}
    with _CSV_PATH.open(newline="") as f:
        for row in csv.DictReader(f):
            rk = RuleKind(
                rule_id=row["rule_id"].strip(),
                name=row["name"].strip(),
                category=row["category"].strip(),
                kind=RuleKindName(row["kind"].strip()),
                evaluation_path=EvaluationPath(row["evaluation_path"].strip()),
                numeric_check=_to_bool(row["numeric_check"]),
                exact_match=_to_opt_bool(row["exact_match"]),
                priya_validated=_to_bool(row["priya_validated"]),
                threshold_needs_signoff=_to_bool(row["threshold_needs_signoff"]),
                rationale=row["rationale"].strip(),
            )
            if rk.rule_id in out:
                raise ValueError(f"duplicate rule_id in rule_kinds.csv: {rk.rule_id}")
            out[rk.rule_id] = rk
    return out


def kind_for(rule_id: str) -> RuleKind | None:
    """The classification for one rule id, or ``None`` if it is not in the table."""
    return load_rule_kinds().get(rule_id)


def rules_by_kind(kind: RuleKindName) -> list[RuleKind]:
    """All rules of a given kind."""
    return [rk for rk in load_rule_kinds().values() if rk.kind is kind]


def numeric_check_rules() -> list[RuleKind]:
    """Rules that get the deterministic numeric bookend (the calculative set)."""
    return [rk for rk in load_rule_kinds().values() if rk.numeric_check]


# --------------------------------------------------------------------------- #
# Priya-validation gate helpers (tracking only — LP-301 signs off nothing)
# --------------------------------------------------------------------------- #


def unvalidated_rules() -> list[RuleKind]:
    """Rules not yet Priya-validated (all of them, until sign-offs land)."""
    return [rk for rk in load_rule_kinds().values() if not rk.priya_validated]


def rules_needing_threshold_signoff() -> list[RuleKind]:
    """Calculative rules whose regulatory threshold must be Priya-signed-off."""
    return [rk for rk in load_rule_kinds().values() if rk.threshold_needs_signoff]


def pending_threshold_signoff() -> list[RuleKind]:
    """Rules that need a threshold sign-off AND haven't been validated — the ship-blockers.

    A later ticket blocks shipping a rule in this list; here it is just reported.
    """
    return [
        rk
        for rk in load_rule_kinds().values()
        if rk.threshold_needs_signoff and not rk.priya_validated
    ]
