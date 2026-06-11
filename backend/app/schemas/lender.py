"""Lender response schemas (LP-32).

A lean public view of a company's configured lenders, for the intake-form
dropdown. No sensitive data — just what's needed to pick a lender.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class LenderSummary(BaseModel):
    """A lender as shown in a picker: id, display name, supported programs."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    supported_programs: list[str]
