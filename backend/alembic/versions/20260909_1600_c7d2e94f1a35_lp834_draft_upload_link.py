"""LP-834 — a draft remembers the secure upload link it carries.

Revision ID: c7d2e94f1a35
Revises: b3f8d61a4c92
Create Date: 2026-09-09 16:00:00

ONE NULLABLE COLUMN, AND IT HOLDS A BEARER CREDENTIAL. The plaintext upload token exists only in
`MintedLink` at the moment of minting — `upload_links` stores a hash — so a draft that regenerates
(which it does on every add and remove) would lose its link the first time anything changed, with no
way to rebuild it.

It is the same secret already present in `communications.body`, which is `NEVER_EXPOSED` in every
readonly view. This column is excluded there for the same reason, and the drift guard in
`tests/test_readonly_query.py` is what enforces that rather than this comment.

NO BACKFILL. Existing drafts carry no link and are complete emails without one: LP-824's wording
offers to send one on request. NULL means "no link", not "unknown".
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7d2e94f1a35"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "b3f8d61a4c92"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("communications", sa.Column("upload_link_url", sa.Text(), nullable=True))


def downgrade() -> None:
    # DROPPING THIS DESTROYS THE ONLY COPY OF A LIVE TOKEN outside the body it was rendered into.
    # That is acceptable and worth saying: the body still holds the URL a borrower was sent, so the
    # link keeps working for them; what is lost is the draft's ability to regenerate with it. A
    # rollback therefore degrades a draft to the no-link wording rather than breaking a borrower.
    op.drop_column("communications", "upload_link_url")
