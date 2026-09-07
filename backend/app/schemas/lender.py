"""Lender schemas — the picker view (LP-32), the admin write shapes and contacts (LP-813).

`LenderSummary` stays exactly as it was: the intake dropdown needs a name and the programs, and
widening it would put a lender's contact details on every processor's picker for no reason.
`LenderDetail` is the admin view, and it is a separate class rather than an optional-field superset
so the narrow one cannot quietly grow.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class LenderSummary(BaseModel):
    """A lender as shown in a picker: id, display name, supported programs."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    supported_programs: list[str]


class LenderDetail(BaseModel):
    """A lender as an admin configures it."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    supported_programs: list[str]
    contact_email: str | None
    contact_phone: str | None
    portal_url: str | None
    notes: str | None
    is_active: bool


class LenderCreate(BaseModel):
    """A new lender. ``slug`` is derived from the name when omitted."""

    name: str = Field(min_length=1, max_length=128)
    slug: str | None = Field(default=None, max_length=64)
    supported_programs: list[str] = Field(default_factory=list)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=64)
    portal_url: str | None = Field(default=None, max_length=512)
    notes: str | None = Field(default=None, max_length=512)


class LenderUpdate(BaseModel):
    """A partial update. Only fields the caller sends are written.

    `company_id` and `lender_overlays` are absent deliberately: ownership is not editable, and
    overlays have their own audited path (LP-87) that requires a change reason.
    """

    name: str | None = Field(default=None, min_length=1, max_length=128)
    slug: str | None = Field(default=None, max_length=64)
    supported_programs: list[str] | None = None
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=64)
    portal_url: str | None = Field(default=None, max_length=512)
    notes: str | None = Field(default=None, max_length=512)
    is_active: bool | None = None


class LenderContactPublic(BaseModel):
    """One person at a lender.

    THE EMAIL IS RETURNED. It is not a sender's text — it is a value this company's own admin typed
    into their own configuration, and a processor choosing an underwriter has to see which address
    they are choosing. It is dropped from the readonly view, because a contact is a person.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    lender_id: UUID
    name: str
    email: str | None
    phone: str | None
    role: str
    notes: str | None
    is_active: bool


def _known_role(value: str | None) -> str | None:
    """The role, or a message naming the ones that exist. ``None`` passes: an update may omit it."""
    from app.models.lender_contact import LenderContactRole

    if value is None:
        return None
    try:
        return LenderContactRole(value).value
    except ValueError as exc:
        allowed = ", ".join(role.value for role in LenderContactRole)
        raise ValueError(f"role must be one of: {allowed}") from exc


class LenderContactCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=64)
    role: str = Field(default="underwriter")
    notes: str | None = Field(default=None, max_length=512)

    _role_is_known = field_validator("role")(_known_role)


class LenderContactUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=64)
    role: str | None = None
    notes: str | None = Field(default=None, max_length=512)
    is_active: bool | None = None

    # THE SAME VALIDATOR, not a second copy of the rule. Written twice, an added role reaches one
    # shape and not the other — and the half that silently accepts anything is the update.
    _role_is_known = field_validator("role")(_known_role)


class UnderwriterAssignment(BaseModel):
    """Who the file's underwriter is. ``null`` clears the assignment."""

    contact_id: UUID | None = None
