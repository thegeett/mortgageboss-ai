"""The finding apply-impact preview schema — the "View fix" dry-run response (LP-97).

Reuses the existing, already-line-itemized calculator schemas (:class:`DtiCalculation` /
:class:`LtvCalculation`) for the before/after — so the preview carries the SAME itemization the
live calculators show (each debt line, the totals, the income, the ratio, the limit status). The
frontend renders the before→after diff (the new line highlighted, the deltas, the status change).
Only the calculators the apply actually moves are populated.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.schemas.dti import DtiCalculation
from app.schemas.ltv import LtvCalculation


class FindingImpactPreview(BaseModel):
    """The dry-run before/after impact of applying a finding (LP-97)."""

    finding_id: UUID
    summary: str  # the change, in one line (e.g. "Add to monthly debts: … — $500.00/mo")
    applied_record: dict[str, Any]  # what the real apply WOULD record (matches apply_finding)
    affects: list[str]  # which calculators change — "dti" / "ltv"
    dti_before: DtiCalculation | None = None
    dti_after: DtiCalculation | None = None
    ltv_before: LtvCalculation | None = None
    ltv_after: LtvCalculation | None = None
    # LP-578 — the state this preview was computed against. The client hands it back on confirm and
    # the apply refuses if the file has moved since, so a processor cannot approve one before/after
    # and have a different one written.
    fingerprint: str


class ApplyRequest(BaseModel):
    """LP-578 — the optional confirm-time body for POST .../apply.

    Carries the fingerprint the preview was computed against. Optional so a caller that never opened
    a preview still works; the UI always sends one.
    """

    expected_fingerprint: str | None = None
