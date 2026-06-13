"""Activity-log response schema (LP-34).

A read-only public view of a loan file's activity entries, for the overview
feed. ``detail`` is type-specific structured data written by ``log_activity``;
it carries no secrets (e.g. status from/to, needs count) — never SSNs or tokens.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.activity_log import ActivityType


class ActivityPublic(BaseModel):
    """One activity-log entry as shown in the overview feed."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    activity_type: ActivityType
    summary: str
    actor_user_id: UUID | None
    detail: dict[str, Any]
    created_at: datetime
