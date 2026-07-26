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
from types import MappingProxyType

# The canonical artifact — plain-text, git-diffable, co-located with the rules.
_CSV_PATH = Path(__file__).with_name("rule_kinds.csv")

# The exact CSV columns (header is validated against this — a renamed/missing column
# fails loud with the file+line, not a bare KeyError deep in a request).
_COLUMNS = (
    "rule_id",
    "name",
    "category",
    "kind",
    "evaluation_path",
    "numeric_check",
    "exact_match",
    "priya_validated",
    "threshold_needs_signoff",
    "rationale",
)


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


def _to_bool(value: str, *, column: str, rule_id: str) -> bool:
    """Strictly ``true``/``false`` — anything else (``1``/``yes``/a typo) raises.

    A routing/sign-off table must not silently coerce a malformed cell to ``False``
    (a threshold rule losing its sign-off gate is invisible), so an unrecognized
    token fails loud at load, like the ``StrEnum`` columns already do.
    """
    v = value.strip().lower()
    if v not in ("true", "false"):
        raise ValueError(f"rule_kinds.csv {rule_id}: {column} must be true/false, got {value!r}")
    return v == "true"


def _to_opt_bool(value: str, *, column: str, rule_id: str) -> bool | None:
    """``true``/``false`` or ``None`` (empty); any other token raises (see :func:`_to_bool`)."""
    if value.strip() == "":
        return None
    return _to_bool(value, column=column, rule_id=rule_id)


def _validate(rk: RuleKind) -> None:
    """Enforce the documented kind⇔path⇔flags contract — a bad row is UNLOADABLE.

    The routing table's whole job is "never send a regulatory/out-of-scope rule to
    AI", so the invariants are checked HERE (the choke point every consumer reads
    through), not only in the test suite — a CSV edit that slips CI still fails
    closed in prod instead of silently mis-routing.
    """

    def bad(msg: str) -> ValueError:
        return ValueError(f"rule_kinds.csv {rk.rule_id}: {msg}")

    if rk.kind is RuleKindName.CALCULATIVE:
        if not rk.numeric_check:
            raise bad("calculative rule must have numeric_check=true")
        if rk.evaluation_path not in (
            EvaluationPath.DETERMINISTIC_BOOKEND,
            EvaluationPath.DETERMINISTIC_BOOKEND_AI,
        ):
            raise bad(f"calculative path must be a deterministic bookend, got {rk.evaluation_path}")
        if rk.exact_match is not None:
            raise bad("exact_match applies to structural rules only")
    elif rk.kind is RuleKindName.STRUCTURAL:
        if rk.numeric_check:
            raise bad("numeric_check is calculative-only")
        if rk.exact_match is None:
            raise bad("structural rule must set exact_match (exact vs fuzzy)")
        expected = (
            EvaluationPath.DETERMINISTIC_ONLY if rk.exact_match else EvaluationPath.AI_FUZZY_MATCH
        )
        if rk.evaluation_path is not expected:
            raise bad(f"structural exact_match={rk.exact_match} → path must be {expected}")
    else:  # judgmental / out_of_scope: no numeric_check, no exact_match, one fixed path
        if rk.numeric_check:
            raise bad("numeric_check is calculative-only")
        if rk.exact_match is not None:
            raise bad("exact_match applies to structural rules only")
        expected = (
            EvaluationPath.AI_JUDGMENT
            if rk.kind is RuleKindName.JUDGMENTAL
            else EvaluationPath.STATIC_FILTER
        )
        if rk.evaluation_path is not expected:
            raise bad(f"{rk.kind} path must be {expected}, got {rk.evaluation_path}")

    if rk.threshold_needs_signoff and rk.kind is not RuleKindName.CALCULATIVE:
        raise bad("threshold_needs_signoff is calculative-only")


@lru_cache(maxsize=1)
def load_rule_kinds() -> MappingProxyType[str, RuleKind]:
    """Load the routing table → read-only ``{rule_id: RuleKind}`` (cached; CSV is truth).

    Read-only (``MappingProxyType``) so a consumer can't mutate the shared cached
    table. Fails loud on a malformed header, a short/None row, a duplicate id, an
    unparseable boolean, or any cross-field invariant violation (:func:`_validate`).
    """
    out: dict[str, RuleKind] = {}
    with _CSV_PATH.open(newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or tuple(reader.fieldnames) != _COLUMNS:
            raise ValueError(f"rule_kinds.csv header must be {_COLUMNS}, got {reader.fieldnames}")
        for row in reader:
            missing = [c for c in _COLUMNS if row.get(c) is None]
            if missing:  # a short row → DictReader fills trailing fields with None
                raise ValueError(f"rule_kinds.csv line {reader.line_num}: missing/short {missing}")
            rule_id = row["rule_id"].strip()
            rk = RuleKind(
                rule_id=rule_id,
                name=row["name"].strip(),
                category=row["category"].strip(),
                kind=RuleKindName(row["kind"].strip()),
                evaluation_path=EvaluationPath(row["evaluation_path"].strip()),
                numeric_check=_to_bool(
                    row["numeric_check"], column="numeric_check", rule_id=rule_id
                ),
                exact_match=_to_opt_bool(row["exact_match"], column="exact_match", rule_id=rule_id),
                priya_validated=_to_bool(
                    row["priya_validated"], column="priya_validated", rule_id=rule_id
                ),
                threshold_needs_signoff=_to_bool(
                    row["threshold_needs_signoff"],
                    column="threshold_needs_signoff",
                    rule_id=rule_id,
                ),
                rationale=row["rationale"].strip(),
            )
            if rk.rule_id in out:
                raise ValueError(f"duplicate rule_id in rule_kinds.csv: {rk.rule_id}")
            _validate(rk)
            out[rk.rule_id] = rk
    return MappingProxyType(out)


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
