"""The typed view of ``companies.settings`` (LP-MB-Admin-02).

In ``app.core`` rather than ``app.schemas`` because the ``Company`` model parses its own settings, and a
model must not import the API schema layer. The request and response shapes stay in
``app/schemas/company.py``.

The column is free JSON and was ``{}`` everywhere before this ticket, so a missing key takes its
default and no data migration is needed. Unknown keys are KEPT (``extra="allow"``): another feature may
store its own, and a round-trip through this model must not drop them.
"""

from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, ValidationError

logger = structlog.get_logger(__name__)


class CompanySettings(BaseModel):
    """The three switches an admin sets for the whole company."""

    model_config = ConfigDict(extra="allow")

    #: Processors hold `loan.create` (ADR-442). Off: only admins and loan officers create files.
    processors_can_create_loans: bool = True
    #: Processors hold `borrower.invite`. Takes effect when the borrower portal ships.
    processors_can_invite_borrowers: bool = True
    #: On: a loan officer or processor sees only the files they are on (LP-MB-Admin-06, ADR-446),
    #: decided per request by `FileScope.for_actor`.
    restrict_loans_to_team: bool = False


def parse_stored_settings(raw: Any, *, company_id: object) -> CompanySettings:
    """``companies.settings`` as a :class:`CompanySettings`, never raising.

    READ ON EVERY REQUEST (the actor's permissions come from it), so a stored value that does not
    parse must not fail the request: that would lock every user of the company out, the admin who
    could fix it included. A bad setting takes its default and is logged by name (never its value);
    a column that is not an object at all is read as ``{}``. Writes stay strict
    (``CompanySettingsUpdate``), so the app itself cannot store a bad value.
    """
    if raw is None:  # a company not yet flushed: the column default has not applied
        return CompanySettings()
    if not isinstance(raw, dict):
        logger.warning("company_settings_not_an_object", company_id=str(company_id))
        return CompanySettings()
    stored: dict[str, Any] = raw
    try:
        return CompanySettings.model_validate(stored)
    except ValidationError as exc:
        bad = sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"]})
        logger.warning("company_settings_invalid", company_id=str(company_id), fields=bad)
        return CompanySettings.model_validate({k: v for k, v in stored.items() if k not in bad})
