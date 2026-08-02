"""The spec validator (LP-434) — the guide's §0 stop conditions. The load-bearing part.

A generator that silently produces broken code 108 times is far worse than one that
refuses 90 and explains why. So this runs BEFORE any emitter and returns a list of
:class:`Refusal`\\ s; a spec is generatable only when that list is empty.

The five stop conditions (guide §0), each a `condition` number for traceability:

1. an ``open_questions`` entry with ``blocks_implementation: true`` (unanswered) — it
   changes the *shape* of what gets built.
2. a field whose ``type`` has no coercer — only ``str`` / ``Decimal`` / ``date`` /
   ``int`` exist; anything else is a new coercer in ``parsing.py``, a code decision.
3. a ``pii.kind`` not in the real ``PiiKind`` enum — **DOB and ADDRESS do not exist
   today**; a new kind needs a mask strategy, not generation.
4. any nested list — ~5 bespoke files each, no generic mechanism (guide §4). The flat
   part is generatable; the list is its own ticket.
5. a field with no ``reason_class`` — the spec is incomplete; a field with no recorded
   reason does not go in.

The valid PII kinds are read from the live :class:`PiiKind` enum, not hard-coded, so
the day someone adds ``ADDRESS`` (with its mask strategy) the validator accepts it
without an edit here.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.ai.extraction.generator.spec import VALID_TYPES, Spec
from app.verification.snapshot.pii import PiiKind

# The PII kinds that exist today, from the live enum — {"SSN", "ACCOUNT"}.
VALID_PII_KINDS: frozenset[str] = frozenset(k.name for k in PiiKind)


@dataclass(frozen=True)
class Refusal:
    """One reason a spec cannot be generated. ``condition`` is the guide §0 number (1-5)."""

    condition: int
    field: str | None
    reason: str

    def __str__(self) -> str:
        where = f" [{self.field}]" if self.field else ""
        return f"condition {self.condition}{where}: {self.reason}"


def validate(spec: Spec) -> list[Refusal]:
    """Apply the five stop conditions; return every refusal (empty ⇒ generatable).

    Reports ALL refusals, not just the first — a spec author wants the full picture in
    one pass. Ordered by condition number, then field, for a stable report.
    """
    refusals: list[Refusal] = []

    # Condition 1 — an unresolved shape-changing open question.
    for oq in spec.open_questions:
        if oq.get("blocks_implementation") is True:
            qid = oq.get("id")
            question = oq.get("q")
            summary = question[:80] if isinstance(question, str) else "(no text)"
            refusals.append(
                Refusal(1, None, f"open_question #{qid} blocks_implementation is true — {summary}")
            )

    # Conditions 2, 3, 5 — per typed-core field.
    for f in spec.typed_core:
        # Condition 5 — a field with no reason_class does not go in.
        if not f.reason_class:
            refusals.append(Refusal(5, f.name, "field has no reason_class"))
        # Condition 2 — a type with no coercer.
        if f.type not in VALID_TYPES:
            refusals.append(
                Refusal(
                    2,
                    f.name,
                    f"type {f.type!r} has no coercer (only {', '.join(VALID_TYPES)} exist"
                    + (f"; degraded_from={f.degraded_from!r})" if f.degraded_from else ")"),
                )
            )
        # Condition 3 — a PII kind that does not exist in PiiKind.
        kind = f.pii_kind
        if kind is not None and kind not in VALID_PII_KINDS:
            refusals.append(
                Refusal(
                    3,
                    f.name,
                    f"pii.kind {kind!r} is not in PiiKind {sorted(VALID_PII_KINDS)} — "
                    "a new kind needs a mask strategy, its own ticket",
                )
            )

    # Condition 4 is RETIRED (LP-438). Nested lists are no longer bespoke ~5-file tickets:
    # LP-437's generic mechanism (ListRow / DocumentEntry.lists / _LIST_SPECS + the three helpers)
    # makes the STORAGE side a declaration the generator emits. The CONSUMER (a rule enumerator or a
    # derived recipe) is still per-list, but that is the rule's own logic, not a stop condition. A
    # nested-list ROW FIELD still needs a coercer, though — condition 2 extends to it (a row with a
    # bool/enum field cannot be typed any more than a flat one).
    for nested in spec.nested_lists:
        for rf in nested.fields:
            # An untyped row field defaults to ``str`` (coerce_str), like a flat degraded field; only
            # an EXPLICIT non-coercible type (bool/enum/…) refuses.
            if rf.type is not None and rf.type not in VALID_TYPES:
                refusals.append(
                    Refusal(
                        2,
                        f"{nested.name}.{rf.name}",
                        f"nested-list row field type {rf.type!r} has no coercer "
                        f"(only {', '.join(VALID_TYPES)} exist)",
                    )
                )

    refusals.sort(key=lambda r: (r.condition, r.field or ""))
    return refusals


def is_generatable(spec: Spec) -> bool:
    """True when the spec passes every stop condition."""
    return not validate(spec)
