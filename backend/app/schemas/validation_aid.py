"""Validation-aid schemas (LP-89) — the starter inventory + the verdict capture.

The inventory lays out EVERY grounded-starter item (each rule LP-82..86 + each calculator
methodology LP-87) with its citation + current value + starter marker, so the developer can
walk Priya through them systematically and record her verdict per item. HONEST: the
``validation_status`` defaults to ``grounded_starter`` (nothing is validated until her session
records a verdict); the verdict CAPTURES her judgment, it does not fabricate validation.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class VerdictView(BaseModel):
    """A recorded verdict on an item (the captured domain-expert judgment)."""

    kind: str  # validated / corrected / flagged_remove / add_new
    corrected_value: str | None
    title: str | None
    note: str | None
    recorded_at: str | None  # ISO-8601


class InventoryItem(BaseModel):
    """One grounded-starter item — a rule or a calculator methodology — + its verdict."""

    item_id: str
    item_kind: str  # "rule" | "cross_source" | "calculator"
    program: str | None  # conventional / fha / null (program-agnostic)
    category: str
    description: str
    value: str | None  # the threshold / rate / methodology value
    op: str | None  # the comparison operator (rules)
    unit: str | None
    citation: str | None  # the source citation (Fannie B-section / HUD section / Form 1084)
    source_type: str | None  # fannie_selling_guide / hud_handbook_4000_1 / ...
    to_verify: bool  # the rule flagged its own citation/value as uncertain
    starter: bool
    validation_status: str  # grounded_starter (default) / validated / corrected / flagged_remove
    verdict: VerdictView | None


class ValidationInventory(BaseModel):
    """The full inventory + the at-a-glance counts (how much still needs validation)."""

    total: int
    grounded_starter: int  # still unvalidated (the honest default)
    validated: int
    corrected: int
    flagged_remove: int
    additions: list[VerdictView]  # ADD_NEW proposals (missing rules Priya named)
    items: list[InventoryItem]


class VerdictInput(BaseModel):
    """Record (or update) a verdict on an item during the validation session.

    ``item_id`` is the inventory item id (a rule_id / methodology id), or ``null`` for an
    ADD_NEW proposal (a missing rule Priya named — describe it in ``title`` + ``note``).
    """

    item_id: str | None = None
    kind: str = Field(pattern="^(validated|corrected|flagged_remove|add_new)$")
    corrected_value: str | None = None
    title: str | None = None
    note: str | None = None
