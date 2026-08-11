"""Deterministic self-consistency checks on extracted values (LP-474).

The pipeline measures COVERAGE (did we capture the fields?); this layer measures a slice of
CORRECTNESS — two extracted values that a document's structure says must **differ**, but which
came out equal. It **FLAGS** (a distinct ``CONSISTENCY`` finding), **never corrects** the value,
never fails the extraction; and it is **deterministic — no model call**, so it survives a model
change (the same error class appeared on Sonnet in the free-reader comparison, and doc 244 resisted
two escalating prompt fixes: this class does not yield to better prompts).

**Declaration-driven** (the LP-437/460 lesson — a declaration scaled to 60+ lists where bespoke
per-type files did not): each check is a :class:`MustDiffer` naming two value-references; adding the
fourth is a line in :data:`CHECKS`, not new code. It extends the philosophy of the LP-445
``count_field`` cross-check (a declared equality that must HOLD → PARTIAL) with its dual — a declared
equality that must NOT hold → a finding.

**Proven on the stored v2 corpus at ZERO false positives** (LP-474 Phase A / C):
  - ``w2``: ``state_income_tax == federal_income_tax_withheld``  → 088 (0 FP / 22 W-2s)
  - ``w2``: a ``box_12_items`` amount ``== medicare_tax_withheld`` → 096 (0 FP / 22 W-2s)
  - ``bank_statement``: a transaction ``amount == running_balance`` → 049 (0 FP / 24 statements)

Value-reference grammar (a string):
  * ``"NAME"``           — a typed-core scalar field.
  * ``"LIST[].FIELD"``   — a nested list's field. Two ``LIST[].`` operands on the SAME list compare
                           PER ROW (049); one ``LIST[].`` operand against a scalar flags if ANY row's
                           value equals the scalar (096).

Numeric equality only (money/tax figures), and a zero value never flags — two independent figures
that are both ``0`` (a no-tax W-2, a $0 line) are trivially equal, not an error.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class MustDiffer:
    """A distinctness assertion: two extracted values that SHOULD differ. Equality → a violation."""

    left: str
    right: str
    label: str


#: The declared checks, keyed by document_type. Adding a fourth is a line here, not new code.
#: Every entry below is measured at ZERO false positives across the stored v2 corpus (LP-474).
CHECKS: dict[str, tuple[MustDiffer, ...]] = {
    "w2": (
        MustDiffer(
            "state_income_tax",
            "federal_income_tax_withheld",
            "State income tax equals federal income tax withheld",
        ),
        MustDiffer(
            "box_12_items[].amount",
            "medicare_tax_withheld",
            "A Box 12 amount equals Medicare tax withheld",
        ),
    ),
    "bank_statement": (
        MustDiffer(
            "transactions[].amount",
            "transactions[].running_balance",
            "A transaction amount equals its own running balance",
        ),
    ),
}


@dataclass(frozen=True)
class Violation:
    """One flagged inconsistency: the check it broke + a human detail naming the equal values."""

    check: MustDiffer
    detail: str


# --------------------------------------------------------------------------- #
# Normalized view — one evaluator over both the live model and a stored record #
# --------------------------------------------------------------------------- #
#: ``{"typed": {field: raw}, "lists": {name: [ {field: raw} ]}}`` — a shape both the production
#: extraction model and a stored bench record reduce to, so ONE evaluator serves both (no drift).
Normalized = dict[str, Any]


def _dec(value: Any) -> Decimal | None:
    """Coerce to Decimal for numeric comparison; ``None`` for missing / non-numeric (never raises)."""
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError, ArithmeticError):
        return None


def normalize_result(data: Any) -> Normalized:
    """From a live extraction model: typed fields are ``TypedField`` → ``value``; nested lists are
    rows of dicts. Uses ``model_dump(mode="json")`` so the shape matches a stored record."""
    dump = data.model_dump(mode="json")
    typed: dict[str, Any] = {}
    lists: dict[str, list[dict[str, Any]]] = {}
    for key, val in dump.items():
        if isinstance(val, dict) and "value" in val:
            typed[key] = val["value"]
        elif isinstance(val, list):
            lists[key] = [row for row in val if isinstance(row, dict)]
    return {"typed": typed, "lists": lists}


def normalize_bench_record(extraction: dict[str, Any]) -> Normalized:
    """From a stored bench record's ``extraction`` dict (``typed_core`` flat, ``lists`` by name)."""
    return {
        "typed": dict(extraction.get("typed_core") or {}),
        "lists": {k: list(v) for k, v in (extraction.get("lists") or {}).items()},
    }


# --------------------------------------------------------------------------- #
# Evaluation                                                                   #
# --------------------------------------------------------------------------- #
def _is_list_ref(ref: str) -> bool:
    return "[]." in ref


def _split_list_ref(ref: str) -> tuple[str, str]:
    name, field = ref.split("[].", 1)
    return name, field


def _row_val(row: Any, field: str) -> Decimal | None:
    """A row is a dict (both normalize paths produce dicts)."""
    return _dec(row.get(field)) if isinstance(row, dict) else None


def _eval_one(norm: Normalized, check: MustDiffer) -> list[Violation]:
    left_is_list, right_is_list = _is_list_ref(check.left), _is_list_ref(check.right)

    if left_is_list and right_is_list:
        # Per-row on the SAME list (049): flag each row where the two fields are equal.
        lname, lfield = _split_list_ref(check.left)
        rname, rfield = _split_list_ref(check.right)
        if lname != rname:
            return []
        out: list[Violation] = []
        for i, row in enumerate(norm["lists"].get(lname, [])):
            a, b = _row_val(row, lfield), _row_val(row, rfield)
            if a is not None and a == b and a != 0:
                out.append(Violation(check, f"{lname} row {i}: {lfield} ({a}) == {rfield} ({b})"))
        return out

    if left_is_list ^ right_is_list:
        # A list field against a scalar (096): flag if ANY row's value equals the scalar.
        list_ref, scalar_ref = (
            (check.left, check.right) if left_is_list else (check.right, check.left)
        )
        lname, lfield = _split_list_ref(list_ref)
        scalar = _dec(norm["typed"].get(scalar_ref))
        if scalar is None or scalar == 0:
            return []
        out = []
        for i, row in enumerate(norm["lists"].get(lname, [])):
            v = _row_val(row, lfield)
            if v is not None and v == scalar:
                out.append(Violation(check, f"{list_ref} row {i} ({v}) == {scalar_ref} ({scalar})"))
        return out

    # Scalar vs scalar (088).
    a, b = _dec(norm["typed"].get(check.left)), _dec(norm["typed"].get(check.right))
    if a is not None and a == b and a != 0:
        return [Violation(check, f"{check.left} ({a}) == {check.right} ({b})")]
    return []


def evaluate(norm: Normalized, checks: tuple[MustDiffer, ...]) -> list[Violation]:
    """Run every declared check over a normalized extraction; return the violations (never raises)."""
    out: list[Violation] = []
    for check in checks:
        out.extend(_eval_one(norm, check))
    return out


def run_consistency_checks(document_type: str | None, data: Any) -> list[Violation]:
    """Production entry point: the declared checks for this type, over a live extraction model."""
    checks = CHECKS.get(document_type or "", ())
    if not checks:
        return []
    return evaluate(normalize_result(data), checks)


def run_on_bench_record(document_type: str | None, extraction: dict[str, Any]) -> list[Violation]:
    """Phase-C / test entry point: the same checks over a STORED bench record's extraction dict."""
    checks = CHECKS.get(document_type or "", ())
    if not checks:
        return []
    return evaluate(normalize_bench_record(extraction), checks)
