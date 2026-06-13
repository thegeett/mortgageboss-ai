"""Reusable column type aliases and length conventions for models.

Using these instead of ad-hoc column types keeps precision, scale, and string
lengths consistent across the schema. They are SQLAlchemy 2.x *annotated*
column types: use them as the parameter to ``Mapped[...]`` and the column
configuration comes along automatically.

Example::

    from app.models.types import Money, ShortStr

    class Account(Base):
        name: Mapped[ShortStr]
        balance: Mapped[Money]

Money rule: currency is **always** ``Decimal`` in Python, **never** ``float``.
Floats cannot represent decimal amounts exactly; use Decimal end-to-end.
"""

from decimal import Decimal
from typing import Annotated

from sqlalchemy import Numeric, String
from sqlalchemy.orm import mapped_column

# --- String length conventions ---------------------------------------------
# Pick a length by content type so string columns stay consistent across models.
SHORT_STRING = 64  # names, short codes, slugs, enum-ish labels
MEDIUM_STRING = 256  # emails, titles, single-line addresses
LONG_STRING = 1024  # descriptions, notes, URLs

# --- Currency / money ------------------------------------------------------
# 14 digits total, 2 decimal places: supports values up to 999,999,999,999.99.
# Always use Decimal in Python, never float, for money.
MONEY_PRECISION = 14
MONEY_SCALE = 2

# Annotated column type for money. Stored as NUMERIC(14, 2), read back as Decimal.
Money = Annotated[
    Decimal,
    mapped_column(Numeric(MONEY_PRECISION, MONEY_SCALE)),
]

# Annotated column types for the common string lengths above.
ShortStr = Annotated[str, mapped_column(String(SHORT_STRING))]
MediumStr = Annotated[str, mapped_column(String(MEDIUM_STRING))]
LongStr = Annotated[str, mapped_column(String(LONG_STRING))]
