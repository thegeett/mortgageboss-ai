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

DISCIPLINE (round-3 FIX 3/4): seeding is INSERT-ONLY (``rule_registry.seed_verification_rules`` skips
existing rule_ids). Regenerating this file changes only what a FRESH DB gets — it does NOT touch an
already-seeded DB. So any change to an EXISTING row's value or shape here (a column like
``confidence_mode``, an ``applicability`` shape) MUST be paired with an Alembic DATA MIGRATION that
updates existing rows (mirror the LP-122R validated migration ``b6f2d9c4e1a8``). Regenerate seed ⇒ write
the matching data migration.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from app.verification.applicability.authoring import finalize_applicability
from app.verification.cross_source.rules import CROSS_SOURCE_RULES
from app.verification.evaluators import get_evaluator
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

# NON-THRESHOLD rules certified validated (LP-122R). The criterion — applied ~123 times, so it must
# be strict: a rule seeds validated=True ONLY if it has NO tunable numeric threshold (nothing for Priya
# to confirm) AND it reproduces known-correct behaviour (the live rule's verdict). AS-5's trigger is a
# boolean ``is_gift``, not a Priya-threshold, and its evaluator matches the live gift-without-letter
# rule — so it qualifies. Threshold-bearing rules (AS-1, DT-1, PR-1, MI-1, …) stay validated=False
# until Priya confirms the number, even after they are built.
_VALIDATED_NO_THRESHOLD: set[str] = {
    "xsrc.asset.gift_without_letter",  # AS-5 — LP-122R certified (no threshold, live-verdict parity)
    # LP-124R — reproduces the live rule; exact count equality, no threshold → validated.
    "xsrc.income.employer_count_matches_items",
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

# BUILT playbook rules — a playbook-only rule that has been BUILT (its evaluator exists) but has NO live
# ``CrossSourceRule`` counterpart. It keeps its ``pb.<id>`` rule_id (the evaluator's registry dispatch
# key, LP-120 "fills it when built") and becomes ``enabled=True`` with a real applicability. Round-3
# discipline: because seeding is insert-only, this seed change ships with a data migration that updates
# existing DBs (the same pattern as LP-122R's validated flip).
_BUILT_PLAYBOOK: dict[str, dict[str, Any]] = {
    "AS-8": {  # bank-statement continuity (LP-123R) — NEW rule, self-defined spec, provisional
        "applicability": {
            "scope": {},  # applies to any file with bank statements
            "triggers": {
                "all": [
                    {
                        "kind": "entity_exists",
                        "collection": "documents",
                        "field": "document_type",
                        "op": "eq",
                        "value": "bank_statement",  # the exact classifier string (catalog.py)
                    }
                ]
            },
            # A bank statement must be present; the 2+/grouping/continuity logic is evaluator-side
            # (the schema can't express counts or account grouping).
            "required_inputs": [{"kind": "document", "document_type": "bank_statement"}],
        },
        "canonical_type": "bank_statement_discontinuity",
        "message_template": "Bank-statement continuity is broken or unverified for one or more accounts.",
        "severity": "YELLOW",
        # validated=False (provisional): self-defined spec; exact-match tolerance + one-statement handling
        # are Priya decisions (there is no live rule to reproduce).
        "validated": False,
    },
}


def _confidence_mode(layer: str | None) -> str | None:
    """deterministic (pure-DET) vs computed (DET-FUZZY). ONE vocabulary end-to-end (post-review
    FIX 6) — the same values the runner emits via ``ConfidenceMode`` ({deterministic, computed}), so
    a downstream trust surface can join the rule row and the run outcome with no translation."""
    if not layer:
        return None
    return "computed" if "FUZZY" in layer.upper() else "deterministic"


def _declared_confidence_mode(rule_id: str) -> str | None:
    """The rule's EVALUATOR-declared confidence_mode — the single source of truth (round-5 FIX 7).

    A built rule's seeded mode must equal what its evaluator emits, so it can't drift from a playbook-layer
    guess. ``None`` when no evaluator is registered (the caller falls back to the layer a-priori)."""
    evaluator = get_evaluator(rule_id)
    return evaluator.confidence_mode.value if evaluator is not None else None


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
    if rule.purpose is None:
        pass  # None = applies to every purpose — no loan_purpose constraint (the default)
    elif rule.purpose is PurposeScope.PURCHASE:
        scope["loan_purpose"] = ["purchase"]
    elif rule.purpose is PurposeScope.REFINANCE:
        scope["loan_purpose"] = ["refinance"]
    elif rule.purpose in (PurposeScope.CASH_OUT, PurposeScope.RATE_TERM):
        # Emit refinance_type; loan_purpose:[refinance] is co-emitted by the structural invariant
        # (round-3 FIX 6A) so the generic FALSE-precedence path handles purchase files.
        scope["refinance_type"] = [rule.purpose.value]
    else:
        # Round-3 FIX 2 — an unhandled PurposeScope member must break seeding LOUD, never silently
        # degrade to a purpose-less scope (which _eval_scope reads as "no constraint → applies to all"
        # → false-green nationwide, the exact failure the FIX 3/4 whitelist prevents at the engine layer).
        raise ValueError(
            f"unhandled PurposeScope member {rule.purpose!r} in _default_applicability — a new purpose "
            "must map to a scope explicitly, not degrade to no-constraint"
        )
    return {"scope": scope, "triggers": {}, "required_inputs": []}


def _live_rows(playbook: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """One seed row per live CrossSourceRule — real rule_id + known structural facts."""
    rows: list[dict[str, Any]] = []
    for rule in CROSS_SOURCE_RULES:
        pb = playbook.get(rule.playbook_id) if rule.playbook_id else None
        # An authored LP-119 applicability overrides the default; otherwise the valid empty shape.
        authored = _AUTHORED_APPLICABILITY.get(rule.rule_id)

        params: dict[str, Any] = {}
        if rule.rule_id in _VALIDATED_PARAMS:
            params = dict(_VALIDATED_PARAMS[rule.rule_id])
        elif rule.threshold is not None:
            params = {"threshold": str(rule.threshold.value), "unit": rule.threshold.unit}
        # Validated by the LP-122R criterion: a Priya-confirmed threshold, OR a non-threshold rule
        # certified to reproduce known-correct behaviour (AS-5). Everything else stays provisional.
        validated = rule.rule_id in _VALIDATED_PARAMS or rule.rule_id in _VALIDATED_NO_THRESHOLD
        # Round-3 FIX 6B — ENFORCE the criterion in code: _VALIDATED_NO_THRESHOLD is only legal for
        # genuinely threshold-free rules. A threshold-bearing rule_id added to it (→ non-empty params)
        # must break seeding LOUD, never seed validated=true beside an unconfirmed threshold.
        if rule.rule_id in _VALIDATED_NO_THRESHOLD and params:
            raise ValueError(
                f"{rule.rule_id} is in _VALIDATED_NO_THRESHOLD but carries params {params} — "
                "validated=true is only legal for threshold-free rules (LP-122R criterion)"
            )

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
                "applicability": finalize_applicability(authored or _default_applicability(rule)),
                "canonical_type": rule.canonical_type,
                "message_template": rule.template,
                # TUNABLE.
                "params": params,
                "severity": rule.severity.value.upper(),
                # The EVALUATOR's declared mode is the source of truth (FIX 7); else the playbook-layer
                # a-priori; else, for a validated off-list rule with no layer (LP-124R), deterministic.
                "confidence_mode": _declared_confidence_mode(rule.rule_id)
                or _confidence_mode(layer)
                or ("deterministic" if validated else None),
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
        built = _BUILT_PLAYBOOK.get(
            pid
        )  # a BUILT playbook rule (evaluator exists) vs a placeholder
        rows.append(
            {
                "rule_id": f"pb.{pid.lower()}",  # the evaluator's registry dispatch key (kept when built)
                "playbook_id": pid,
                "name": pb["name"],
                "category": pb["category"],
                "layer": pb["layer"],
                "evaluator": None,  # dispatch is by rule_id via the code registry (as for AS-5)
                "applicability": finalize_applicability(built["applicability"]) if built else None,
                "canonical_type": built["canonical_type"] if built else None,
                "message_template": built["message_template"] if built else None,
                "params": {},
                "severity": built["severity"] if built else None,
                # A built playbook rule's mode is its evaluator's declared mode (FIX 7); an unbuilt
                # placeholder uses the playbook-layer a-priori.
                "confidence_mode": _declared_confidence_mode(f"pb.{pid.lower()}")
                or _confidence_mode(pb["layer"]),
                "enabled": bool(
                    built
                ),  # a built playbook rule is enabled; placeholders stay disabled
                "status": pb["status"],
                "scope": pb["scope"],
                "validated": built["validated"] if built else False,
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
