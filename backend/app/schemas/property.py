"""Property request/response schemas (LP-29).

The subject property is a per-file singleton (one Property per loan file). No
sensitive data here — plain address/classification/valuation fields.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.property import OccupancyType, PropertyType


class PropertyCreate(BaseModel):
    """Fields accepted when attaching the subject property. All optional — the
    property is often 'TBD' early and filled in later."""

    address_line: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    property_type: PropertyType | None = None
    occupancy_type: OccupancyType | None = None
    estimated_value: Decimal | None = None
    purchase_price: Decimal | None = None


class PropertyUpdate(BaseModel):
    """Partial update (PATCH). Only provided fields are applied."""

    address_line: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    property_type: PropertyType | None = None
    occupancy_type: OccupancyType | None = None
    estimated_value: Decimal | None = None
    purchase_price: Decimal | None = None
    # MISMO-specific core fields (LP-56) — editable after import.
    valuation_amount: Decimal | None = None
    attachment_type: str | None = None
    construction_method: str | None = None
    financed_unit_count: int | None = None


class PropertyResponse(BaseModel):
    """The subject property view."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    address_line: str | None
    address_line_2: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    property_type: PropertyType | None
    occupancy_type: OccupancyType | None
    estimated_value: Decimal | None
    purchase_price: Decimal | None
    # The MISMO PropertyValuationAmount (LP-90). Exposed so the Overview can display +
    # edit it: the LTV's appraised-value basis reads ``valuation_amount or estimated_value``
    # (valuation_amount wins), so it must be visible + editable — not a hidden field that
    # silently shadows estimated_value edits.
    valuation_amount: Decimal | None
    created_at: datetime
    updated_at: datetime
