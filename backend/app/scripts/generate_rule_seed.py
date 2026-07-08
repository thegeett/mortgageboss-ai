"""Generate the version-controlled rule seed (LP-118) — ``docs/rules/rule_seed.json``.

The seed is the AUTHORING SOURCE OF TRUTH for the ``verification_rules`` table (the
table is the runtime read-source, populated FROM this seed by the LP-118 migration).
It is a SUPERSET merge of two inputs, so the table both matches reality AND scales to
the playbook:

  1. **The live code rules** — every :data:`CROSS_SOURCE_RULES` (LP-86), with its real
     ``rule_id`` (never renamed), its LP-117.5 ``playbook_id``, and the structural facts
     we already know from code (canonical_type, severity, message_template, program/
     purpose applicability, threshold params). These are ``enabled=True``.
  2. **The playbook-only rows** — every playbook row (``docs/rules/rule_seed.csv``) NOT
     already covered by a live rule, as a not-yet-built row: a derived ``rule_id``
     (``pb.<playbook_id>``), ``enabled=False``, null ``evaluator``/``canonical_type``
     (LP-120 fills them when the rule is built).

Nothing here executes a rule. Re-run after changing the live rules or the playbook CSV::

    uv run python -m app.scripts.generate_rule_seed
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from app.verification.cross_source.rules import CROSS_SOURCE_RULES
from app.verification.rules.schema import PurposeScope

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RULES_DIR = _REPO_ROOT / "docs" / "rules"
_PLAYBOOK_CSV = _RULES_DIR / "rule_seed.csv"
_OUT_JSON = _RULES_DIR / "rule_seed.json"

# Priya-CONFIRMED thresholds (LP-117.5 session) — these two rules seed validated=True.
# Everything else seeds validated=False (the Priya-validation gate). NOTE: the live
# income-variance rule currently uses 10% in code (an LP-80 overlay-overrideable
# grounded-starter); the Priya-confirmed value is 5% — seeded here as authoring data.
# The table executes nothing yet, so this is not a behavior change; LP-121 reconciles.
_VALIDATED_PARAMS: dict[str, dict[str, Any]] = {
    "xsrc.income.stated_vs_documented": {"variance_pct": 5},  # IN-1, Priya-confirmed >5%
    "xsrc.asset.large_deposit_unsourced": {"large_deposit_pct": 50},  # AS-1, Priya-confirmed >50%
}

# Authored applicability (LP-119) in the scope/triggers/required_inputs shape. Seeded per rule as
# each is built; AS-5 (gift-letter) is the LP-119 thin-slice proof. Overrides the default
# program/purpose applicability. The gift LETTER is the check-target (evaluated in LP-120), NOT a
# required input — its absence is the finding, so it does not appear here.
_AUTHORED_APPLICABILITY: dict[str, dict[str, Any]] = {
    "xsrc.asset.gift_without_letter": {  # AS-5
        "scope": {},  # applies to all files
        "triggers": {
            "all": [
                {
                    "kind": "entity_exists",
                    "collection": "assets",
                    "field": "is_gift",
                    "op": "eq",
                    "value": True,
                }
            ]
        },
        "required_inputs": [{"kind": "data_field", "path": "assets[].is_gift"}],
    },
}


def _confidence_mode(layer: str | None) -> str | None:
    """certain (pure-DET) vs computed (DET-FUZZY) — a best-effort seed; LP-120 finalizes."""
    if not layer:
        return None
    return "computed" if "FUZZY" in layer.upper() else "certain"


def _load_playbook() -> dict[str, dict[str, str]]:
    """The playbook rows keyed by playbook_id (from LP-117.5's rule_seed.csv)."""
    with _PLAYBOOK_CSV.open(encoding="utf-8") as f:
        return {row["playbook_id"]: row for row in csv.DictReader(f)}


def _default_applicability(rule: Any) -> dict[str, Any]:
    """The valid scope/triggers/required_inputs shape for a rule not yet AUTHORED (FIX 3b).

    Translates the CrossSourceRule's program/purpose into a real ``scope`` (with the engine's keys —
    ``loan_purpose``/``refinance_type``, NOT the flat ``purpose``) and leaves triggers/required_inputs
    empty (unauthored). Never emits the flat ``{program, purpose}`` shape that ``extra="forbid"``
    now rejects and that the engine silently ignored.
    """
    scope: dict[str, list[str]] = {}
    if rule.program is not None:
        scope["program"] = [rule.program.value]
    if rule.purpose is not None:
        # PurposeScope.PURCHASE/REFINANCE gate on loan_purpose; CASH_OUT/RATE_TERM on refinance_type.
        dim = (
            "refinance_type"
            if rule.purpose in (PurposeScope.CASH_OUT, PurposeScope.RATE_TERM)
            else "loan_purpose"
        )
        scope[dim] = [rule.purpose.value]
    return {"scope": scope, "triggers": {}, "required_inputs": []}


def _live_rows(playbook: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """One seed row per live CrossSourceRule — real rule_id + known structural facts."""
    rows: list[dict[str, Any]] = []
    for rule in CROSS_SOURCE_RULES:
        pb = playbook.get(rule.playbook_id) if rule.playbook_id else None
        # An authored LP-119 applicability overrides the default; otherwise the valid empty shape.
        authored = _AUTHORED_APPLICABILITY.get(rule.rule_id)

        params: dict[str, Any] = {}
        validated = rule.rule_id in _VALIDATED_PARAMS
        if validated:
            params = dict(_VALIDATED_PARAMS[rule.rule_id])
        elif rule.threshold is not None:
            params = {"threshold": str(rule.threshold.value), "unit": rule.threshold.unit}

        layer = pb["layer"] if pb else None
        rows.append(
            {
                "rule_id": rule.rule_id,
                "playbook_id": rule.playbook_id,
                "name": pb["name"] if pb else rule.rule_id.split(".")[-1].replace("_", " "),
                "category": pb["category"] if pb else rule.category.value,
                "layer": layer,
                # STRUCTURAL — evaluator/applicability filled/refined by LP-119/120; the
                # canonical_type + template we already know from the live rule.
                "evaluator": None,
                "applicability": authored or _default_applicability(rule),
                "canonical_type": rule.canonical_type,
                "message_template": rule.template,
                # TUNABLE.
                "params": params,
                "severity": rule.severity.value.upper(),
                "confidence_mode": _confidence_mode(layer),
                "enabled": True,  # the 18 live cross-source rules exist in code
                # Routing / scope (playbook vocab where mapped; live default otherwise).
                "status": pb["status"] if pb else "NOW",
                "scope": pb["scope"] if pb else "IN",
                "validated": validated,
            }
        )
    return rows


def _playbook_only_rows(
    playbook: dict[str, dict[str, str]], covered: set[str]
) -> list[dict[str, Any]]:
    """One seed row per playbook rule NOT covered by a live rule — not-yet-built rows."""
    rows: list[dict[str, Any]] = []
    for pid, pb in playbook.items():
        if pid in covered:
            continue
        rows.append(
            {
                "rule_id": f"pb.{pid.lower()}",  # derived placeholder id (LP-120 may replace)
                "playbook_id": pid,
                "name": pb["name"],
                "category": pb["category"],
                "layer": pb["layer"],
                "evaluator": None,  # not built yet — will not run until LP-120 fills it
                "applicability": None,
                "canonical_type": None,
                "message_template": None,
                "params": {},
                "severity": None,
                "confidence_mode": _confidence_mode(pb["layer"]),
                "enabled": False,
                "status": pb["status"],
                "scope": pb["scope"],
                "validated": False,
            }
        )
    return rows


def build_seed() -> list[dict[str, Any]]:
    """The merged seed: live rows first, then the remaining playbook-only rows."""
    playbook = _load_playbook()
    live = _live_rows(playbook)
    covered = {r.playbook_id for r in CROSS_SOURCE_RULES if r.playbook_id}
    return live + _playbook_only_rows(playbook, covered)


def main() -> None:
    seed = build_seed()
    _OUT_JSON.write_text(json.dumps(seed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    live = sum(1 for r in seed if r["enabled"])
    print(
        f"wrote {_OUT_JSON} — {len(seed)} rows ({live} live/enabled, {len(seed) - live} not-built)"
    )


if __name__ == "__main__":
    main()
