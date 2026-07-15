"""The generic DERIVED producer (LP-326) — compute a tag deterministically from other facts.

A ``derived`` tag's ``production_data`` is a RECIPE KEY resolved against the recipe registry (one
entry per recipe, reusable across families — never per-family branching). A recipe reads the snapshot
and returns ``(value, reasoning)`` for its subject; the producer wraps it in a ``derived`` tag citing
its subject. A recipe that cannot compute returns ``("unknown", reason)`` — honest, never fabricated.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import JsonValue

from app.verification.snapshot.model import Snapshot
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.declarations import TagDeclaration
from app.verification.tag_materialization.subjects import LOAN_SUBJECT

# A recipe: snapshot -> (value, reasoning). Deterministic; "unknown" when it cannot compute.
Recipe = Callable[[Snapshot], tuple[JsonValue, str]]

# The 1003 fields a complete application must carry (a STARTER set — the authoritative required set
# incl. Declarations + co-borrower is a Priya/guideline value, LP-323-ID-A §5). Keys are MISMO fact
# keys; a blank/absent one counts as missing.
_APP_REQUIRED_FIELDS = (
    "borrower.1.name",
    "borrower.1.ssn",
    "loan.amount",
    "property.address",
)


def _app_required_fields_present(snapshot: Snapshot) -> tuple[JsonValue, str]:
    """id.app_required_fields_present — 'complete' iff every required 1003 field is present."""
    if snapshot.mismo.absent:
        return "unknown", "the 1003 (MISMO) facts are absent — cannot check completeness"
    facts = snapshot.mismo.facts
    missing = [
        key
        for key in _APP_REQUIRED_FIELDS
        if (field := facts.get(key)) is None or not field.is_present
    ]
    if not missing:
        return "complete", "all required 1003 fields are present"
    return "incomplete + list", f"missing required 1003 field(s): {', '.join(missing)}"


_RECIPES: dict[str, Recipe] = {
    "app_required_fields_present": _app_required_fields_present,
}

KNOWN_RECIPES = frozenset(_RECIPES)


def produce_derived_tags(decl: TagDeclaration, snapshot: Snapshot) -> dict[str, dict[str, Tag]]:
    """Produce a derived tag for its subject (``loan`` today), keyed ``{subject_id: {tag_id: Tag}}``."""
    recipe = _RECIPES.get(decl.data)
    if recipe is None:
        raise KeyError(f"unknown derived recipe {decl.data!r} (known: {sorted(_RECIPES)})")
    # Recipes are snapshot -> ONE value, so they attach to the single loan subject; a non-loan subject
    # would be misrouted here (validate_declarations rejects it at load, but never route silently).
    if decl.subject != LOAN_SUBJECT:
        raise KeyError(
            f"derived tag {decl.tag_id!r}: subject {decl.subject!r} is unsupported — "
            f"derived recipes are loan-level (snapshot -> one value) today"
        )
    value, reasoning = recipe(snapshot)
    subject_id = LOAN_SUBJECT
    tag = Tag(
        value=value,
        confidence=None,
        reasoning=reasoning,
        source_facts=(subject_id,),
        produced_by=TagProducedBy.DERIVED,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )
    return {subject_id: {decl.tag_id: tag}}


__all__ = ["KNOWN_RECIPES", "Recipe", "produce_derived_tags"]
