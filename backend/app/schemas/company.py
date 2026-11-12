"""Company settings (LP-MB-Admin-02): the typed view of ``companies.settings``.

The column is free JSON and was ``{}`` everywhere before this ticket, so a missing key takes its
default and no data migration is needed. Unknown keys are KEPT (``extra="allow"``): another feature may
store its own, and a round-trip through this model must not drop them.
"""

from pydantic import BaseModel, ConfigDict


class CompanySettings(BaseModel):
    """The three switches an admin sets for the whole company."""

    model_config = ConfigDict(extra="allow")

    #: Processors hold `loan.create` (ADR-442). Off: only admins and loan officers create files.
    processors_can_create_loans: bool = True
    #: Processors hold `borrower.invite`. Takes effect when the borrower portal ships.
    processors_can_invite_borrowers: bool = True
    #: Stored and read back only; LP-MB-Admin-05 Part 2 enforces it. Changes nothing until then.
    restrict_loans_to_team: bool = False


class CompanySettingsUpdate(BaseModel):
    """``PATCH /company/settings``: any of the three; an omitted field is left as it is."""

    model_config = ConfigDict(extra="forbid")

    processors_can_create_loans: bool | None = None
    processors_can_invite_borrowers: bool | None = None
    restrict_loans_to_team: bool | None = None


class CompanySettingsPublic(BaseModel):
    """The three settings as the API returns them (unknown stored keys are not echoed)."""

    processors_can_create_loans: bool
    processors_can_invite_borrowers: bool
    restrict_loans_to_team: bool
