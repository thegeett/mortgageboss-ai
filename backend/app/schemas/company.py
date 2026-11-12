"""Company settings over the API (LP-MB-Admin-02).

The settings model itself is :class:`app.core.company_settings.CompanySettings`; these are the
request and response shapes of ``/company/settings``.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator


class CompanySettingsUpdate(BaseModel):
    """``PATCH /company/settings``: any of the three; an omitted field is left as it is.

    Strict: an unknown field and an explicit ``null`` are both refused (422). ``null`` would
    otherwise read as "omitted" and change nothing while returning 200.
    """

    model_config = ConfigDict(extra="forbid")

    processors_can_create_loans: bool | None = None
    processors_can_invite_borrowers: bool | None = None
    restrict_loans_to_team: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def _no_explicit_null(cls, data: Any) -> Any:
        if isinstance(data, dict):
            nulls = sorted(key for key, value in data.items() if value is None)
            if nulls:
                raise ValueError(f"must be true or false, not null: {', '.join(nulls)}")
        return data


class CompanySettingsPublic(BaseModel):
    """The three settings as the API returns them (unknown stored keys are not echoed)."""

    processors_can_create_loans: bool
    processors_can_invite_borrowers: bool
    restrict_loans_to_team: bool
