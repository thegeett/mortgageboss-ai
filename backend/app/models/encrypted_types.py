"""Custom SQLAlchemy column type for transparently encrypted strings (LP-14).

:class:`EncryptedString` lets a model declare a column that is plaintext to
Python code but ciphertext at rest. It is a thin :class:`~sqlalchemy.types.
TypeDecorator` over ``Text`` that encrypts on the way to the database (bind) and
decrypts on the way back (result), delegating the actual crypto to
:mod:`app.core.encryption`. Model code declares it like any other column::

    from app.models.encrypted_types import EncryptedString

    ssn: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)

and reads/writes ``borrower.ssn`` as a normal string; the encryption is
invisible.

The underlying storage is ``Text`` (not a fixed ``VARCHAR(n)``): Fernet
ciphertext is ~1.3x the plaintext plus a fixed overhead and is itself
urlsafe-base64, so a generous, unbounded text column avoids guessing a length.

Caveat — querying: because encryption is non-deterministic (a fresh IV per
write, see :mod:`app.core.encryption`), the same plaintext produces different
ciphertext each time, so an encrypted column CANNOT be used in a SQL ``WHERE``
equality, ``ORDER BY``, index, or unique constraint. Filter on a separate
non-sensitive column, or decrypt-and-compare in Python. For SSN this is fine:
we never query by it.
"""

from typing import Any

from sqlalchemy import Dialect, Text
from sqlalchemy.types import TypeDecorator

from app.core.encryption import decrypt_value, encrypt_value


class EncryptedString(TypeDecorator[str]):
    """A ``Text`` column whose value is encrypted at rest (Fernet, app-level).

    ``process_bind_param`` runs on write (Python value -> stored value) and
    encrypts; ``process_result_value`` runs on read (stored value -> Python
    value) and decrypts. ``None`` passes through unchanged so a nullable column
    stays SQL ``NULL`` rather than ciphertext.
    """

    impl = Text
    # The type takes no parameters that affect the generated SQL, so it is safe
    # to participate in SQLAlchemy's compiled-statement cache.
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        """Encrypt the Python value before it is written to the database."""
        return encrypt_value(value)

    def process_result_value(self, value: Any | None, dialect: Dialect) -> str | None:
        """Decrypt the stored ciphertext back to plaintext when read."""
        return decrypt_value(value)
