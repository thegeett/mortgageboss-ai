"""Database-backed enums and the convention for defining them.

Convention: enums are Python ``StrEnum`` subclasses, stored as their **string
value** in the database (readable and debuggable) rather than integers. Each
enum lives next to the model that owns it; only genuinely shared enums live here.

Map an enum on a model with the :func:`str_enum` helper::

    from sqlalchemy.orm import Mapped, mapped_column

    from app.models.enums import RecordStatus, str_enum

    status: Mapped[RecordStatus] = mapped_column(
        str_enum(RecordStatus),
        default=RecordStatus.ACTIVE,
        nullable=False,
    )

Why the helper exists: SQLAlchemy's ``Enum`` stores the enum *member name*
(``ARCHIVED``) by default, but for a ``StrEnum`` we want the *value*
(``archived``). :func:`str_enum` sets ``values_callable`` so the value is what's
persisted, and ``native_enum=False`` so the column is a bounded ``VARCHAR`` with
a CHECK constraint instead of a PostgreSQL native ``ENUM`` type — far easier to
evolve (adding a value needs no ``ALTER TYPE`` migration). See ADR-037.
"""

from enum import StrEnum

from sqlalchemy import Enum as SAEnum


def str_enum(enum_cls: type[StrEnum], *, length: int = 32) -> SAEnum:
    """Build a SQLAlchemy ``Enum`` for a ``StrEnum``, stored as its value.

    Persists the enum's string value (not its member name) in a bounded
    ``VARCHAR`` with a CHECK constraint. Use for every enum column so storage
    is consistent across the schema.
    """

    def values(cls: type[StrEnum]) -> list[str]:
        return [member.value for member in cls]

    return SAEnum(
        enum_cls,
        native_enum=False,
        create_constraint=True,
        length=length,
        values_callable=values,
    )


class RecordStatus(StrEnum):
    """Generic active/archived status for simple cases.

    Most models define their own domain-specific status enum alongside the
    model. This one is provided both as the canonical example of the pattern
    and for simple records that only need active/archived.
    """

    ACTIVE = "active"
    ARCHIVED = "archived"
