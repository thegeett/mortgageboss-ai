"""LP-855 — where this processor writes their email.

Nothing in a browser can detect which mail client a person uses, so LP-855 asks, once, on the first
draft. The answer is a working preference like row density: theirs, not the screen's, and worth
keeping between sessions.

NULLABLE, AND NULL IS A REAL ANSWER — unlike every other preference on this table. The others
default to the value the product would use anyway (`compact` density, the standard thoroughness),
because "never chosen" and "chose the default" are the same thing for them. They are not the same
thing here: `mailto` is both the safe answer AND what "Not now" selects, so a server default would
make "nobody has been asked" indistinguishable from "they picked the desktop default", and the
picker would then either never appear or appear forever. Until an answer exists the button reads
"Copy & open mail app" and behaves as `mailto`.

KEPT OUT OF THE READONLY VIEWS (`tests/test_readonly_query.py::EXCLUDED`), following LP-UI-030's
decision for `reviewer_pane_split`: the readonly surface exists to answer questions about loan data
from staging, and which mail client a processor prefers answers none of them. It is not sensitive —
it is one of four fixed words — so this is a noise decision rather than a privacy one, and
rebuilding `readonly.users` to carry it would add a column no query will ever select.

Hand-written. `--autogenerate` proposes eighteen destructive operations against this schema, so
every migration here is written by hand.

Revision ID: c9e4a7b12d36
Revises: b8d1f6e40c25
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9e4a7b12d36"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "b8d1f6e40c25"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("mail_client", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "mail_client")
