"""User preference schemas (LP-79) — the user-level verification defaults.

The first user-preference surface: the **default aggression level** (the
verification thoroughness applied to a file unless a per-file override dials it
up/down). Read + update shapes for ``/users/me/preferences``.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.models.user import RowDensity
from app.verification.confidence import AggressionLevel


class UserPreferences(BaseModel):
    """The caller's preferences (LP-79: the default verification thoroughness)."""

    default_aggression_level: AggressionLevel
    density: RowDensity

    model_config = {"from_attributes": True}


class UserPreferencesUpdate(BaseModel):
    """Update the caller's preferences. Only the provided fields change.

    Both fields are optional so that saying "only the provided fields change" is
    true. Before LP-UI-010 `default_aggression_level` was required, so a client
    changing density alone had to send back a thoroughness it was not changing —
    and a stale one would have silently overwritten the real value.
    """

    default_aggression_level: AggressionLevel | None = None
    density: RowDensity | None = None
