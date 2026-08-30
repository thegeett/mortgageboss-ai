"""Saved-view schemas (LP-UI-015).

The filter payload is stored as JSON but is **not** free-form: it round-trips
through `SavedViewFilters`, so a view can only hold filters the pipeline can
actually apply. A saved view that silently ignores half of what it says it
filters on is worse than no saved view.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.loan_file import LoanFileStatus
from app.models.saved_view import DEFAULT_SORT, SavedViewSort


class SavedViewFilters(BaseModel):
    """What a view filters on.

    Deliberately the same vocabulary the list endpoint already accepts — statuses
    and a search string — because a filter the endpoint cannot apply is a lie.
    New filters land here and in `list_loan_files` together, never separately.

    **Not present, and not an oversight:** an assignee filter. LP-UI-014 asks for
    "current user" as a filter value so one shared view serves a whole team, and
    the mockup shows "My files" and "Unassigned". Neither is expressible: a loan
    file has no owner in the data model — no `assigned_to_user_id`, no
    association table. `loan_officer_name` is free text for an external contact
    and `uploaded_by_user_id` is per document. File assignment is its own
    feature; see docs/tickets/LP-UI-015.md.
    """

    model_config = ConfigDict(extra="forbid")

    statuses: list[LoanFileStatus] = Field(default_factory=list)
    search: str | None = Field(default=None, max_length=128)

    @field_validator("search")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        """An empty search box is no filter, not a filter matching everything."""
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("statuses")
    @classmethod
    def _dedupe(cls, value: list[LoanFileStatus]) -> list[LoanFileStatus]:
        """Order carries no meaning here, and a repeat would widen nothing."""
        seen: list[LoanFileStatus] = []
        for status in value:
            if status not in seen:
                seen.append(status)
        return seen


class SavedViewCreate(BaseModel):
    """Create a view. The owner and company come from the caller, never the body."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=256)
    filters: SavedViewFilters = Field(default_factory=SavedViewFilters)
    sort: SavedViewSort = DEFAULT_SORT
    is_shared: bool = False

    @field_validator("name")
    @classmethod
    def _trim(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("A view needs a name.")
        return trimmed


class SavedViewUpdate(BaseModel):
    """Update a view. Only the provided fields change.

    Every field optional, and the endpoint applies only what it was sent — the
    lesson from LP-UI-010, where a required field meant a client changing one
    preference had to restate another it was not changing.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=256)
    filters: SavedViewFilters | None = None
    sort: SavedViewSort | None = None
    is_shared: bool | None = None

    @field_validator("name")
    @classmethod
    def _trim(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("A view needs a name.")
        return trimmed


class SavedViewPublic(BaseModel):
    """A view as the client sees it."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    filters: SavedViewFilters
    sort: SavedViewSort
    is_shared: bool
    owner_user_id: UUID
    #: True when the caller owns it — the client needs this to decide whether to
    #: offer edit and delete, and computing it here keeps that judgement in one
    #: place rather than in every consumer.
    is_mine: bool
    #: How many files this view currently matches. Server-computed so the
    #: context column does not fire one `pageSize: 1` request per view — the
    #: StatsCards pattern LP-UI-013 deleted. `None` when counts were not asked
    #: for, which is different from a view that matches nothing.
    count: int | None = None
    created_at: datetime
    updated_at: datetime
