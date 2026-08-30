"""Overlay admin schemas (LP-87) — view + edit a lender's overlay without hand-editing JSON.

Closes the LP-80 deferral (overlays were hand-edited JSON on the ``lenders`` table). The
admin UI VIEWs a lender's overlay (each override's effective threshold made legible against
the investor base rule), EDITs the override thresholds + the required ``reason``, and the
edit is audited (who, from→to, when) in the overlay's own audit trail (the LP-80.5
value-recording posture).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OverlayOverrideView(BaseModel):
    """One override, with its effect made legible (base default → overlay effective)."""

    rule_id: str
    rule_description: str
    op: str  # the comparison operator (inherited from the base rule's condition)
    unit: str | None
    base_value: Decimal | None  # the investor default threshold
    effective_value: Decimal  # the lender's overlay threshold (what enforcement would use)
    reason: str | None


class OverlayAuditEntry(BaseModel):
    """One audit record of an overlay edit (from→to values, who, when, why)."""

    at: str  # ISO-8601
    actor_user_id: str | None
    reason: str
    changes: list[dict[str, object]]  # [{field: rule_id, from, to}]


class OverlayLenderSummary(BaseModel):
    """A lender in the admin list, led by its OVERLAY rather than its details.

    An overlay is the highest-leverage thing an admin touches — one change moves
    every file at that lender — so the list answers "what is different here, and
    when did it last change" before it answers "who do I call".

    Both numbers come off the `lenders.lender_overlays` blob the list query
    already loads. Fetching each lender's overlay separately to count them would
    be one request per row: the StatsCards pattern LP-UI-013 deleted.

    `override_count` of zero is a REAL ANSWER, not a gap — it means the agency
    guideline applies unchanged at this lender. The UI says so in words rather
    than rendering an empty space.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    supported_programs: list[str]
    override_count: int
    #: When the overlay was last edited, from its audit trail. `None` when it has
    #: never been edited — which is not the same as "edited a long time ago".
    last_changed_at: datetime | None = None


class LenderOverlayView(BaseModel):
    """A lender + its overlay (overrides made effect-legible + the audit trail)."""

    id: str
    name: str
    slug: str
    overrides: list[OverlayOverrideView]
    audit: list[OverlayAuditEntry]


class OverlayOverrideInput(BaseModel):
    """One override to set (the threshold value + this override's reason)."""

    rule_id: str
    value: Decimal
    reason: str | None = None


class OverlayUpdateRequest(BaseModel):
    """Replace the lender's overlay override set; a change ``reason`` is required (audit)."""

    overrides: list[OverlayOverrideInput]
    reason: str = Field(min_length=1)  # WHY this overlay change — required + audited
