"""LP-UI-030 — remember the reviewer's pane split per user.

The document reviewer is three resizable panes, and where a processor puts the
dividers is a working preference like row density: theirs, not the screen's, and
worth keeping between sessions.

Stored as JSON rather than two columns because the value is one thing — a split —
and splitting it across columns invites them to disagree. Nullable, so "never
adjusted" stays distinguishable from "adjusted back to the default"; the UI shows
its default layout for NULL rather than writing one on first load.

KEPT OUT OF THE READONLY VIEWS (`tests/test_readonly_query.py::EXCLUDED`). The
readonly surface exists to answer questions about loan data from staging, and a
processor's pane geometry answers none of them. It is not sensitive — it is two
integers — so this is a noise decision rather than a privacy one, and rebuilding
`readonly.users` to carry it would add a column no query will ever select.

Hand-written. `--autogenerate` proposes eighteen destructive operations against
this schema (drops `finding_prose`, borrower address columns, `properties.county`
and more), so every migration here is written by hand.

Revision ID: b7c14e29d3af
Revises: a8d3f70b41c2
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7c14e29d3af"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "a8d3f70b41c2"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("reviewer_pane_split", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "reviewer_pane_split")
