"""People as the admin API reads and writes them (LP-MB-Admin-03)."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.models.user import User, UserRole

#: The 50 states, DC, and the three territories NMLS licenses (Puerto Rico, Guam, the US Virgin
#: Islands): a loan officer's state licence is issued by one of these.
US_STATE_CODES = frozenset(
    {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
        "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
        "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT",
        "VA", "WA", "WV", "WI", "WY", "DC", "PR", "GU", "VI",
    }
)  # fmt: skip


class UserAdminView(BaseModel):
    """One person on the People page. Never the password hash."""

    id: UUID
    email: str
    first_name: str
    last_name: str
    phone: str | None
    title: str | None
    nmls_id: str | None
    licensed_states: list[str]
    sees_all_loans: bool
    roles: list[UserRole]
    is_owner: bool
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    #: Live loan files this person is on the team of (LP-MB-Admin-05).
    file_count: int = 0

    @classmethod
    def of(cls, user: User, *, owner_user_id: UUID | None, file_count: int = 0) -> "UserAdminView":
        return cls(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            phone=user.phone,
            title=user.title,
            nmls_id=user.nmls_id,
            licensed_states=list(user.licensed_states),
            sees_all_loans=user.sees_all_loans,
            roles=sorted(user.role_set),
            is_owner=user.id == owner_user_id,
            is_active=user.is_active,
            last_login_at=user.last_login_at,
            created_at=user.created_at,
            file_count=file_count,
        )


#: A name: surrounding spaces dropped, then at least one character, so " " is refused (review
#: finding 5) rather than shown as a blank row and a blank name in every audit line.
_Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class UserDetailsUpdate(BaseModel):
    """``PATCH /users/{id}``: only what is sent changes. Email is not here (ADR-042).

    ``phone``, ``title`` and ``nmls_id`` may be sent as ``null`` to clear them. The others may not:
    a name, the states list and the flag always have a value.
    """

    model_config = ConfigDict(extra="forbid")

    first_name: _Name | None = None
    last_name: _Name | None = None
    phone: str | None = Field(default=None, max_length=32)
    title: str | None = Field(default=None, max_length=100)
    nmls_id: str | None = Field(default=None, max_length=16)
    licensed_states: list[str] | None = None
    sees_all_loans: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def _required_fields_are_not_null(cls, data: Any) -> Any:
        if isinstance(data, dict):
            nulls = sorted(
                key
                for key in ("first_name", "last_name", "licensed_states", "sees_all_loans")
                if key in data and data[key] is None
            )
            if nulls:
                raise ValueError(f"cannot be null: {', '.join(nulls)}")
        return data

    @field_validator("licensed_states")
    @classmethod
    def _valid_states(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        unknown = sorted({code for code in value if code not in US_STATE_CODES})
        if unknown:
            raise ValueError(f"not a two-letter US state code: {', '.join(unknown)}")
        if len(set(value)) != len(value):
            raise ValueError("a state is listed twice")
        return sorted(value)


class UserRolesUpdate(BaseModel):
    """``PUT /users/{id}/roles``: the full set the person will hold."""

    model_config = ConfigDict(extra="forbid")

    roles: list[UserRole]
