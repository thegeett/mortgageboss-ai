"""The company audit log as the API returns it (LP-MB-Admin-03)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class AuditActor(BaseModel):
    """Who did it. ``null`` on the entry means the system (a migration or a platform script)."""

    id: UUID
    name: str


class AuditEntry(BaseModel):
    id: UUID
    created_at: datetime
    actor: AuditActor | None
    action: str
    target_type: str
    target_id: UUID | None
    #: The person's or company's name now, resolved at read time; ``null`` if it no longer exists.
    target_name: str | None
    summary: str
    detail: dict[str, Any]


class AuditPage(BaseModel):
    """One page, newest first. Pass ``next_cursor`` as ``before`` for the next; ``null`` at the end."""

    items: list[AuditEntry]
    next_cursor: str | None
    #: Rows matching the filters, all pages together. On the first page only (no ``before``); a
    #: later page is ``null`` rather than paying for the same count again.
    total: int | None
