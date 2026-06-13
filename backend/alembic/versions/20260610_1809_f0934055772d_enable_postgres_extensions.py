"""enable_postgres_extensions

Revision ID: f0934055772d
Revises:
Create Date: 2026-06-10 18:09:43.045128

Enables the PostgreSQL extensions the schema relies on:

* ``pgcrypto`` — column-level encryption functions for sensitive PII (SSN,
  account numbers) added in later tickets (LP-14).
* ``uuid-ossp`` — database-side UUID generation. We generate UUIDs in Python
  via ``uuid4`` today, but having this available keeps the option open.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f0934055772d"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Enable required PostgreSQL extensions."""
    # pgcrypto: column-level encryption (SSN, account numbers)
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    # uuid-ossp: database-level UUID generation (we use uuid4 in Python, but
    # this keeps DB-side generation available)
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')


def downgrade() -> None:
    """Drop the extensions."""
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
    op.execute('DROP EXTENSION IF EXISTS "uuid-ossp"')
