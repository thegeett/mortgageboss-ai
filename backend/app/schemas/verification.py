"""Verification schemas (LP-78) — the run + the cross-source status/findings.

The minimal shapes the trigger/staleness UI needs: a verification run summary, the
uniform finding shape (deterministic + AI findings look identical), and the file's
verification status (the staleness flag + the latest run + the findings). The rich
findings UI + resolution flow is LP-81.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.models.finding import Finding
from app.models.verification import Verification


class VerificationRunPublic(BaseModel):
    """A verification run summary (status + counts + AI cost)."""

    id: UUID
    status: str
    trigger: str
    started_at: datetime | None
    completed_at: datetime | None
    red_count: int
    yellow_count: int
    green_count: int
    total_cost_estimate: float | None

    @classmethod
    def from_model(cls, run: Verification) -> VerificationRunPublic:
        return cls(
            id=run.id,
            status=run.status.value,
            trigger=run.trigger.value,
            started_at=run.started_at,
            completed_at=run.completed_at,
            red_count=run.red_count,
            yellow_count=run.yellow_count,
            green_count=run.green_count,
            total_cost_estimate=run.total_cost_estimate,
        )


class FindingPublic(BaseModel):
    """One finding in the uniform shape (deterministic or AI — same shape, LP-75)."""

    id: UUID
    rule_id: str
    origin: str
    status: str
    category: str
    message: str
    confidence: float
    source_page: int | None
    source_snippet: str | None
    resolution_status: str
    details: dict[str, Any]

    @classmethod
    def from_model(cls, finding: Finding) -> FindingPublic:
        return cls(
            id=finding.id,
            rule_id=finding.rule_id,
            origin=finding.origin.value,
            status=finding.status.value,
            category=finding.category.value,
            message=finding.message,
            confidence=finding.confidence,
            source_page=finding.source_page,
            source_snippet=finding.source_snippet,
            resolution_status=finding.resolution_status.value,
            details=finding.details,
        )


class VerificationStatusPublic(BaseModel):
    """The file's verification status — staleness + the latest run + the findings."""

    stale: bool
    latest_run: VerificationRunPublic | None
    findings: list[FindingPublic]
