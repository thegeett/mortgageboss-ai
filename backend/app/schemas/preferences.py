"""User preference schemas (LP-79) — the user-level verification defaults.

The first user-preference surface: the **default aggression level** (the
verification thoroughness applied to a file unless a per-file override dials it
up/down). Read + update shapes for ``/users/me/preferences``.
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator

from app.models.user import RowDensity
from app.verification.confidence import AggressionLevel


class UserPreferences(BaseModel):
    """The caller's preferences (LP-79: the default verification thoroughness)."""

    default_aggression_level: AggressionLevel
    density: RowDensity
    #: Where this user put the reviewer's two dividers (LP-UI-030), as
    #: `[list_pct, canvas_pct]`. `None` means never adjusted — the UI shows its
    #: own default rather than a value nobody chose.
    reviewer_pane_split: list[int] | None = None

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
    reviewer_pane_split: list[int] | None = None

    @field_validator("reviewer_pane_split")
    @classmethod
    def _two_sane_percentages(cls, value: list[int] | None) -> list[int] | None:
        """Two percentages that leave room for the third pane.

        Validated because it is stored as JSON: a client could otherwise persist
        `[0, 0]` or `[90, 90]` and give itself a layout with a pane it cannot
        reach — and the value survives to the next session, so a bad write is
        not a refresh away from being fixed.
        """
        if value is None:
            return None
        if len(value) != 2:
            raise ValueError("A split is two percentages: the list and canvas panes.")
        if any(pct < 10 for pct in value):
            raise ValueError("Each pane keeps at least 10% of the width.")
        if sum(value) > 90:
            raise ValueError("The fields pane keeps at least 10% of the width.")
        return value
