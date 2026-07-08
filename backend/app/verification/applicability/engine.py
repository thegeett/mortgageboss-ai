"""Applicability filter engine (LP-119) — three-valued, data-driven classification.

``classify(applicability, snapshot)`` reads a rule's applicability (scope / triggers /
required_inputs, all DATA) against the LP-118.6 fact snapshot and returns one of
DOESNT_APPLY / COULDNT_CHECK / READY_TO_RUN. No rule-specific logic is hardcoded — a new rule is a
new ``verification_rules`` row, not an engine change. This classifies only; it runs no evaluator
and produces no finding (LP-120/121).

THE HONESTY CONTRACT (the whole point):

* scope/trigger **FALSE** → DOESNT_APPLY (silently excluded — irrelevant to this file).
* scope/trigger **UNKNOWN** or a required input **absent** → COULDNT_CHECK (surfaced, with the
  reason). **UNKNOWN NEVER collapses to doesn't-apply or ready-to-run** — the false-green guard: a
  file must never look checked-and-clean when the data to decide was missing.
* all TRUE + all required inputs present → READY_TO_RUN.

How present/empty/absent (the ``Fact`` tri-state, LP-118.6) maps to Ternary for a DECISION input:
a fact with a concrete value → its truth; **a fact with no value — ``absent`` OR empty
(``value is None``) — → UNKNOWN** (we cannot decide, so we must not guess). This is the
conservative reading ADR-239 mandates ("unset enum → None → applicability unknown").
"""

from __future__ import annotations

from typing import Any

from app.models.loan_file import LoanPurpose
from app.verification.applicability.schema import (
    Applicability,
    ApplicabilityState,
    Classification,
    Condition,
    DataField,
    DerivedField,
    DocumentPresent,
    EntityExists,
    FieldCondition,
    Ternary,
    TriggerGroup,
)
from app.verification.fact_namespace.snapshot import (
    Fact,
    FactNamespace,
    FileFacts,
    PropertyFacts,
)

_MISSING = object()  # sentinel: a path did not resolve at all


def _scope_path(dim: str) -> str | None:
    """The snapshot fact path a scope dimension constrains, DERIVED from the snapshot model fields
    (FIX 4) so it can't rot out of sync as fields are added. An unrecognized dimension → ``None`` →
    the caller fails CLOSED (couldn't-check), never "no constraint → applies everywhere"."""
    if dim in FileFacts.model_fields:
        return f"file.{dim}"
    if dim in PropertyFacts.model_fields:
        return f"property.{dim}"
    return None


# --------------------------------------------------------------------------- #
# Path resolution + Fact → Ternary
# --------------------------------------------------------------------------- #


def _resolve(snapshot: FactNamespace, path: str) -> Any:
    """Navigate a dotted path on the snapshot; return the terminal (Fact / list / plain / _MISSING).

    An intermediate ``None`` (e.g. ``property`` is None) resolves to ``_MISSING``.
    """
    node: Any = snapshot
    for part in path.split("."):
        if node is None:
            return _MISSING
        node = getattr(node, part, _MISSING)
        if node is _MISSING:
            return _MISSING
    return node


def _known_value(node: Any) -> tuple[bool, Any]:
    """(known, value) for a resolved decision input.

    - ``absent`` → NOT known (no answer → UNKNOWN → couldn't-check).
    - a concrete value → known.
    - **value None but NOT absent (FIX 6):** a *real* ``None`` answer iff it carries a ``source``
      (a deliberate determination, e.g. ``computed.mi_monthly`` = None = "MI not required") → known.
      An unset scalar (built via ``_scalar`` → ``source is None``) is empty/unset → NOT known.
    """
    if node is _MISSING:
        return False, None
    if isinstance(node, Fact):
        if node.absent:
            return False, None
        if node.value is not None:
            return True, node.value
        # value is None, not absent: a determined answer only if it has a source.
        return (True, None) if node.source is not None else (False, None)
    if node is None:
        return False, None
    return True, node


def _compare(value: Any, op: str, target: Any) -> Ternary:
    """Compare a known value to the condition target. Bad op/uncomparable → UNKNOWN (never a guess)."""
    try:
        if op == "eq":
            return Ternary.TRUE if value == target else Ternary.FALSE
        if op == "ne":
            return Ternary.TRUE if value != target else Ternary.FALSE
        if op == "in":
            return Ternary.TRUE if value in target else Ternary.FALSE
        if op == "not_in":
            return Ternary.TRUE if value not in target else Ternary.FALSE
        if op == "gt":
            return Ternary.TRUE if value > target else Ternary.FALSE
        if op == "lt":
            return Ternary.TRUE if value < target else Ternary.FALSE
        if op == "gte":
            return Ternary.TRUE if value >= target else Ternary.FALSE
        if op == "lte":
            return Ternary.TRUE if value <= target else Ternary.FALSE
    except TypeError:
        return Ternary.UNKNOWN
    return Ternary.UNKNOWN


# --------------------------------------------------------------------------- #
# Ternary combinators
# --------------------------------------------------------------------------- #


def _and(results: list[Ternary]) -> Ternary:
    if any(r is Ternary.FALSE for r in results):
        return Ternary.FALSE
    if any(r is Ternary.UNKNOWN for r in results):
        return Ternary.UNKNOWN
    return Ternary.TRUE


def _or(results: list[Ternary]) -> Ternary:
    if any(r is Ternary.TRUE for r in results):
        return Ternary.TRUE
    if any(r is Ternary.UNKNOWN for r in results):
        return Ternary.UNKNOWN
    return Ternary.FALSE


def _not(result: Ternary) -> Ternary:
    if result is Ternary.TRUE:
        return Ternary.FALSE
    if result is Ternary.FALSE:
        return Ternary.TRUE
    return Ternary.UNKNOWN


# --------------------------------------------------------------------------- #
# Condition + trigger evaluation
# --------------------------------------------------------------------------- #


def _eval_field_condition(snapshot: FactNamespace, cond: FieldCondition) -> Ternary:
    known, value = _known_value(_resolve(snapshot, cond.path))
    if not known:
        return Ternary.UNKNOWN  # no value to decide with → UNKNOWN (false-green guard)
    return _compare(value, cond.op, cond.value)


def _eval_entity_exists(snapshot: FactNamespace, cond: EntityExists) -> Ternary:
    """Three-valued existence: TRUE if any element matches; UNKNOWN if the collection is EMPTY (no
    data to decide existence) or an element's field is unknown; FALSE only when there ARE elements
    and none matches."""
    collection = _resolve(snapshot, cond.collection)
    if collection is _MISSING or not isinstance(collection, list):
        return Ternary.UNKNOWN
    per_element: list[Ternary] = []
    for element in collection:
        known, value = _known_value(getattr(element, cond.field, _MISSING))
        per_element.append(Ternary.UNKNOWN if not known else _compare(value, cond.op, cond.value))
    if any(r is Ternary.TRUE for r in per_element):
        return Ternary.TRUE
    if not collection:
        # FIX 8 (accepted + documented): the plain-list collections (assets/liabilities/…) can't
        # distinguish "reviewed, zero rows" from "not loaded", so an EMPTY collection → UNKNOWN
        # (couldn't-check), not FALSE. This errs SAFE (no false-green) — a no-asset file carries a
        # gift-rule couldn't-check until these collections become Fact-wrapped (a future ticket).
        return Ternary.UNKNOWN
    if any(r is Ternary.UNKNOWN for r in per_element):
        return Ternary.UNKNOWN
    return Ternary.FALSE


def _eval_condition(snapshot: FactNamespace, cond: Condition) -> Ternary:
    if isinstance(cond, EntityExists):
        return _eval_entity_exists(snapshot, cond)
    return _eval_field_condition(snapshot, cond)


def _eval_triggers(snapshot: FactNamespace, triggers: TriggerGroup) -> Ternary:
    groups: list[Ternary] = []
    if triggers.all_:
        groups.append(_and([_eval_condition(snapshot, c) for c in triggers.all_]))
    if triggers.any_:
        groups.append(_or([_eval_condition(snapshot, c) for c in triggers.any_]))
    if triggers.none_:
        groups.append(_not(_or([_eval_condition(snapshot, c) for c in triggers.none_])))
    if not groups:
        return Ternary.TRUE  # no triggers → always relevant
    return _and(groups)


def _eval_scope(snapshot: FactNamespace, scope: dict[str, list[str]]) -> tuple[Ternary, list[str]]:
    """Scope is AND over its dimensions. Empty constraint = no constraint. Returns (ternary, reasons)."""
    results: list[Ternary] = []
    reasons: list[str] = []
    for dim, allowed in scope.items():
        if not allowed:  # empty constraint → applies to all
            continue
        path = _scope_path(dim)
        if path is None:
            # FIX 4 — an unrecognized dimension FAILS CLOSED (UNKNOWN → couldn't-check), never
            # "no constraint → applies everywhere" (e.g. scope {"state":["TX"]} must NOT fire
            # nationwide).
            results.append(Ternary.UNKNOWN)
            reasons.append(
                f"scope dimension '{dim}' not recognized → cannot evaluate (fail closed)"
            )
            continue
        known, value = _known_value(_resolve(snapshot, path))
        if not known:
            # FIX 5 — absent-because-IRRELEVANT (a purchase has no refinance_type) → DOESN'T-APPLY,
            # not couldn't-check (mirrors purpose_applies). Distinguish it from absent-because-missing.
            if dim == "refinance_type" and _is_known_purchase(snapshot):
                results.append(Ternary.FALSE)
                reasons.append("refinance_type-scoped rule on a known purchase → doesn't apply")
            else:
                results.append(Ternary.UNKNOWN)
                reasons.append(f"scope '{dim}' unknown (file value absent)")
        elif value in allowed:
            results.append(Ternary.TRUE)
        else:
            results.append(Ternary.FALSE)
            reasons.append(f"scope '{dim}'={value!r} not in {allowed}")
    return _and(results), reasons


def _is_known_purchase(snapshot: FactNamespace) -> bool:
    """The file's loan_purpose is a KNOWN purchase (so refinance_type is definitively irrelevant)."""
    known, value = _known_value(_resolve(snapshot, "file.loan_purpose"))
    return known and value == LoanPurpose.PURCHASE.value


# --------------------------------------------------------------------------- #
# Required inputs
# --------------------------------------------------------------------------- #


def _resolve_from(node: Any, path: str) -> Any:
    """Navigate a dotted path FROM ``node`` (like :func:`_resolve` but not rooted at the snapshot)."""
    for part in path.split("."):
        if node is None or node is _MISSING:
            return _MISSING
        node = getattr(node, part, _MISSING)
        if node is _MISSING:
            return _MISSING
    return node


def _nested_field_present(node: Any, segments: list[str]) -> bool:
    """Whether the (possibly nested) leaf field is PRESENT on ``node`` (FIX 1).

    ``segments`` are the "[]"-delimited parts AFTER the outer collection, e.g.
    ``["income_items", "monthly_amount"]``. A non-leaf segment must be a NON-EMPTY collection whose
    EVERY element carries the field (fail closed — incomplete data → not present). The leaf must be
    a KNOWN value.
    """
    seg = segments[0].lstrip(".")
    child = _resolve_from(node, seg) if seg else node
    if len(segments) == 1:  # leaf field
        return _known_value(child)[0]
    if not isinstance(child, list) or not child:  # nested collection missing/empty → not present
        return False
    return all(_nested_field_present(element, segments[1:]) for element in child)


def _required_input_satisfied(
    snapshot: FactNamespace, req: DataField | DocumentPresent | DerivedField
) -> bool:
    if isinstance(req, DocumentPresent):
        return any(d.document_type == req.document_type and d.present for d in snapshot.documents)
    # DataField / DerivedField — a snapshot path that must carry usable data.
    path = req.path
    if "[]" in path:
        # FIX 1 — inspect the NAMED (nested) leaf field, not just the outer collection. A
        # collection path ("assets[].value", "borrowers[].income_items[].monthly_amount") is
        # satisfied only when the collection is non-empty AND every element has the named field
        # PRESENT (not absent). Otherwise couldn't-check — the false-green guard.
        parts = path.split("[]")
        collection = _resolve(snapshot, parts[0])
        if not isinstance(collection, list) or not collection:
            return False
        return all(_nested_field_present(element, parts[1:]) for element in collection)
    known, _ = _known_value(_resolve(snapshot, path))
    return known


# --------------------------------------------------------------------------- #
# The classification entry point
# --------------------------------------------------------------------------- #


def classify(applicability: Applicability, snapshot: FactNamespace) -> Classification:
    """Classify one rule against a fact snapshot (LP-119). Read-only; runs no evaluator.

    FALSE precedence: a definitively-false scope/trigger → DOESNT_APPLY regardless of missing
    inputs. Else any UNKNOWN scope/trigger, or any absent required input → COULDNT_CHECK (with
    reasons). Else → READY_TO_RUN.
    """
    scope_t, scope_reasons = _eval_scope(snapshot, applicability.scope)
    trigger_t = _eval_triggers(snapshot, applicability.triggers)

    if scope_t is Ternary.FALSE or trigger_t is Ternary.FALSE:
        reasons = list(scope_reasons)
        if trigger_t is Ternary.FALSE:
            reasons.append("triggers not satisfied")
        return Classification(state=ApplicabilityState.DOESNT_APPLY, reasons=reasons)

    if scope_t is Ternary.UNKNOWN or trigger_t is Ternary.UNKNOWN:
        reasons = list(scope_reasons)
        if trigger_t is Ternary.UNKNOWN:
            reasons.append("trigger data unknown (decision input absent)")
        return Classification(state=ApplicabilityState.COULDNT_CHECK, reasons=reasons)

    # Applies (scope + triggers TRUE) — do we have the data to run it?
    missing = [
        _input_label(req)
        for req in applicability.required_inputs
        if not _required_input_satisfied(snapshot, req)
    ]
    if missing:
        return Classification(
            state=ApplicabilityState.COULDNT_CHECK,
            reasons=[f"missing required input: {m}" for m in missing],
            missing_inputs=missing,
        )
    return Classification(state=ApplicabilityState.READY_TO_RUN)


def _input_label(req: DataField | DocumentPresent | DerivedField) -> str:
    if isinstance(req, DocumentPresent):
        return f"document:{req.document_type}"
    return f"{req.kind}:{req.path}"


def classify_from_json(
    applicability_json: dict[str, Any] | None, snapshot: FactNamespace
) -> Classification:
    """Parse a rule's stored ``applicability`` JSON (``None`` → universal) and classify it.

    ``None``/empty applicability → no scope/triggers/required inputs → READY_TO_RUN.
    """
    applicability = Applicability.model_validate(applicability_json or {})
    return classify(applicability, snapshot)
