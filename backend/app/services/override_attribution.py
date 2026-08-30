"""Who set a calculator override, and why (LP-UI-021).

Every override model — `CalculatorOverride`, `DtiOverride`, `LtvOverride` —
already records `actor_user_id` and `note`. All three services dropped both on
the way out, keeping `{field_key: value}`, so the screen could say a figure was
overridden but never by whom. On a compliance file "someone changed this number"
is a different statement from "Priya changed this number, and here is why".

One helper for the three, because three copies of a join is how the three
`{field_key: value}` comprehensions came to be identical in the first place.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class _OverrideRow(Protocol):
    """The shape the three override models share."""

    field_key: str
    value: Decimal
    note: str | None
    actor_user_id: UUID | None


class OverrideAttribution(BaseModel):
    """An override's value together with its provenance."""

    value: Decimal
    #: The actor's display name. `None` when no actor was recorded — an override
    #: written before the column existed, or by a process rather than a person.
    #: Never a placeholder: "—" in an audit trail reads as a name nobody checked.
    by: str | None = None
    note: str | None = None


async def attribute_overrides(
    db: AsyncSession, rows: list[_OverrideRow]
) -> dict[str, OverrideAttribution]:
    """Index overrides by field key, resolving each actor to a display name.

    One query for every actor rather than one per row: a DTI with eight
    overridden lines would otherwise issue eight lookups to render one panel.
    """
    actor_ids = {row.actor_user_id for row in rows if row.actor_user_id is not None}
    names: dict[UUID, str] = {}
    if actor_ids:
        users = (await db.scalars(select(User).where(User.id.in_(actor_ids)))).all()
        names = {
            user.id: f"{user.first_name} {user.last_name}".strip() or user.email for user in users
        }

    return {
        row.field_key: OverrideAttribution(
            value=row.value,
            by=names.get(row.actor_user_id) if row.actor_user_id is not None else None,
            note=row.note,
        )
        for row in rows
    }
