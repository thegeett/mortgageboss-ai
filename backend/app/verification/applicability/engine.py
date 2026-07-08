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

from enum import Enum
from typing import Any

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
from app.verification.fact_namespace.snapshot import Fact, FactNamespace, FactSource

_MISSING = object()  # sentinel: a path did not resolve at all

# The ONLY scope dimensions — the CATEGORICAL (enumerable) fields (post-review FIX 3). Restricting
# to this fixed set (not every FileFacts/PropertyFacts field) means a numeric field or an unknown
# name can never masquerade as a scope dimension: ``{"loan_amount":["500000"]}`` would resolve a
# Decimal, always compare False, and SILENTLY HIDE the rule. Anything not here fails CLOSED.
_SCOPE_DIMENSIONS: dict[str, str] = {
    "program": "file.program",
    "loan_purpose": "file.loan_purpose",
    "refinance_type": "file.refinance_type",
    "occupancy": "property.occupancy",
    "property_type": "property.property_type",
}

# Fact sources for which a value of ``None`` is NOT a determination → treat as UNKNOWN (post-review
# FIX 2). ``UNMAPPED`` (the canonicalizer couldn't classify a raw type) is the LOAD-BEARING member: a
# value-None from a real determination source (``computed`` = "no MI") stays KNOWN, but an UNMAPPED
# value-None must not. The ``ABSENT_*`` members are belt-and-suspenders (round-3 FIX 9): by convention
# an ``absent_*`` source comes with ``absent=True`` (via ``Fact.missing``), so ``_known_value`` already
# catches it in the ``node.absent`` branch above — they are listed here only so a directly-constructed
# non-absent ``absent_*`` fact (unconventional) still fails closed. Do NOT trim the ``node.absent``
# branch on the assumption this set is the sole authority.
_NON_DETERMINATION_SOURCES = {
    FactSource.UNMAPPED,  # the only one that reaches here in practice (non-absent value-None)
    FactSource.ABSENT_NO_SCHEMA,
    FactSource.ABSENT_NOT_PERSISTED,
    FactSource.ABSENT_UNCOMPUTABLE,
}

# Collections that are RELIABLY fully loaded, so an EMPTY one is a determinate "none exist" → FALSE
# (round-3 review FIX 5). ``documents`` is always loaded from the file. Everything else is a plain-list
# fact that can't distinguish "zero rows" from "not loaded" → empty stays UNKNOWN (the FIX-8 default).
_RELIABLY_LOADED_COLLECTIONS = {"documents"}


def _scope_path(dim: str) -> str | None:
    """The snapshot path a categorical scope dimension constrains, or ``None`` for an unrecognized
    dimension (→ the caller fails CLOSED: couldn't-check, never a silent doesn't-apply)."""
    return _SCOPE_DIMENSIONS.get(dim)


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
    """(known, value) for a resolved decision input — THREE-way (post-review FIX 2).

    - ``absent`` → NOT known (no answer → UNKNOWN → couldn't-check).
    - a concrete value → known.
    - **value None but NOT absent:** known ONLY for a genuine determination — a real ``None`` answer
      from a determination source (``computed.mi_monthly`` = None = "MI not required"). An
      **UNMAPPED** value (the canonicalizer couldn't classify the raw type), an ``absent_*`` source,
      or an unset scalar (``source is None``) is UNDETERMINABLE → NOT known → couldn't-check. UNMAPPED
      belongs with unknown, never "known None".
    """
    if node is _MISSING:
        return False, None
    if isinstance(node, Fact):
        if node.absent:
            return False, None
        if node.value is not None:
            return True, node.value
        # value None, not absent: a determined answer only from a positive-determination source.
        if node.source is None or node.source in _NON_DETERMINATION_SOURCES:
            return False, None
        return True, None
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
        # An empty RELIABLY-LOADED collection is a determinate "none exist" → FALSE (doesn't-apply).
        # ``documents`` is always fully loaded, so a zero-document (or zero-bank-statement) file
        # correctly DOESN'T-APPLY a document-triggered rule (round-3 review FIX 5). The plain-list facts
        # (assets/liabilities/…) still can't tell "reviewed, zero rows" from "not loaded", so they stay
        # UNKNOWN (couldn't-check) — the FIX-8 conservative default (no false-green) until they become
        # Fact-wrapped.
        return Ternary.FALSE if cond.collection in _RELIABLY_LOADED_COLLECTIONS else Ternary.UNKNOWN
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
            results.append(Ternary.UNKNOWN)
            reasons.append(f"scope '{dim}' unknown (file value absent)")
        elif value in allowed:
            results.append(Ternary.TRUE)
        else:
            results.append(Ternary.FALSE)
            reasons.append(f"scope '{dim}'={value!r} not in {allowed}")
    return _and(results), reasons
    # NOTE (post-review FIX 10 / round-3 FIX 6A): the refinance_type-on-purchase case needs NO special
    # branch here — a refi rule ALWAYS carries BOTH dims (scope {loan_purpose:[refinance],
    # refinance_type:[…]}), so on a purchase the loan_purpose mismatch → FALSE → doesn't-apply via the
    # generic path above. That co-emission is enforced STRUCTURALLY at construction (the seed generator /
    # any applicability builder adds loan_purpose:[refinance] whenever a refinance_type scope is present),
    # NOT by a guard in this engine — a refi scope cannot exist without its loan_purpose.


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


class _Leaf(Enum):
    """The status of a nested required-input leaf on ONE branch (round-3 FIX 1)."""

    PRESENT = "present"  # a relevant element exists and carries the leaf → data to run on
    ABSENT = "absent"  # a relevant element exists but the leaf is missing/unextracted → fail-closed
    SKIP = (
        "skip"  # nothing relevant to check on this branch (an empty sub-collection along the way)
    )


def _nested_leaf_status(node: Any, segments: list[str]) -> _Leaf:
    """The RELEVANT-ELEMENT status of a (possibly nested) leaf field (round-3 FIX 1 — the precise
    condition, neither ``all`` nor ``any``).

    ``segments`` are the ``"[]"``-delimited parts AFTER the outer collection, e.g.
    ``[".income_items", ".monthly_amount"]``. The distinction that matters for the honesty contract:

    * An element with an **empty** sub-collection has nothing to check → :attr:`_Leaf.SKIP` (it must
      NOT sink the rule — a co-borrower with no income items while the primary has full data is still
      runnable; that was the "too strict" ``all`` failure).
    * An element with a **non-empty** sub-collection whose leaf is absent → :attr:`_Leaf.ABSENT`
      (fail-closed — a borrower who HAS income whose amount wasn't extracted means incomplete
      household data; that was the "too loose" ``any`` failure).

    So the rule is runnable only when every element that HAS the sub-collection carries the leaf.
    """
    seg = segments[0].lstrip(".")
    if len(segments) == 1:  # the leaf field itself, on this element
        child = _resolve_from(node, seg) if seg else node
        return _Leaf.PRESENT if _known_value(child)[0] else _Leaf.ABSENT
    child = _resolve_from(node, seg) if seg else node
    if not isinstance(child, list) or not child:
        return _Leaf.SKIP  # empty/absent sub-collection → nothing relevant here
    statuses = [_nested_leaf_status(element, segments[1:]) for element in child]
    if any(s is _Leaf.ABSENT for s in statuses):
        return _Leaf.ABSENT  # a relevant element is missing the leaf → fail-closed
    if any(s is _Leaf.PRESENT for s in statuses):
        return _Leaf.PRESENT
    return _Leaf.SKIP  # every element skipped (all sub-collections empty)


def _required_input_satisfied(
    snapshot: FactNamespace, req: DataField | DocumentPresent | DerivedField
) -> bool:
    if isinstance(req, DocumentPresent):
        return any(d.document_type == req.document_type and d.present for d in snapshot.documents)
    # DataField / DerivedField — a snapshot path that must carry usable data.
    path = req.path
    if "[]" in path:
        # The RELEVANT-ELEMENT rule (round-3 FIX 1 / review FIX 6), applied CONSISTENTLY to single-level
        # and nested ``[]`` paths via the same ``_nested_leaf_status``:
        #   * single-level (``assets[].value``): the leaf is a scalar directly on each element, so EVERY
        #     element is relevant — any element missing it → not satisfied (couldn't-check).
        #   * nested (``borrowers[].income_items[].monthly_amount``): an element whose sub-collection is
        #     empty is SKIPPED (nothing to check); an element that HAS the sub-collection but is missing
        #     the leaf → not satisfied.
        # Satisfied iff at least one relevant element carries the leaf AND no relevant element is missing
        # it. (A multi-element test pins this — it has silently drifted four times.)
        parts = path.split("[]")
        collection = _resolve(snapshot, parts[0])
        if not isinstance(collection, list) or not collection:
            return False
        statuses = [_nested_leaf_status(element, parts[1:]) for element in collection]
        if any(s is _Leaf.ABSENT for s in statuses):
            return False  # a relevant element is missing the leaf → couldn't-check
        return any(
            s is _Leaf.PRESENT for s in statuses
        )  # else ready iff some relevant element had it
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
