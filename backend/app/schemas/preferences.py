"""User preference schemas (LP-79) — the user-level verification defaults.

The first user-preference surface: the **default aggression level** (the
verification thoroughness applied to a file unless a per-file override dials it
up/down). Read + update shapes for ``/users/me/preferences``.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.verification.confidence import AggressionLevel


class UserPreferences(BaseModel):
    """The caller's preferences (LP-79: the default verification thoroughness)."""

    default_aggression_level: AggressionLevel

    model_config = {"from_attributes": True}


class UserPreferencesUpdate(BaseModel):
    """Update the caller's preferences. Only the provided fields change."""

    default_aggression_level: AggressionLevel
