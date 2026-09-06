"""lp636_persist_document_name

Persist the classifier's free-text ``document_name`` on the document (LP-636 defect 5).

LP-463 added ``document_name`` to the classification result — the model's own name for what the
document IS, emitted BEFORE it makes the constrained ``document_type`` pick, and documented there
as "a more reliable signal than the constrained pick" and "on an ``unknown`` this names the missing
catalog type".

It was never persisted. The pipeline used it for the ``type_matches_document`` self-check and then
dropped it: not stored, not in the activity detail, not logged. So a document the model had
already named correctly and then filed as a confident ``unknown`` — routed to Tier 3 free
extraction instead of its Tier 1 typed extractor — left no trace of the better answer anywhere, and
the frequency of that could not be measured retrospectively at all. LF-ZE9N had four.

This revision only stores the value. It changes no routing and no status: on its own it makes the
problem visible, which is the precondition for fixing it.

NOT ADDED TO THE readonly.* VIEWS, deliberately. It is model prose over the document, the same
category as ``documents.summary`` and ``documents.generic_analysis``, both of which C7 drops. The
scrub matches identifier SHAPES and a person's name is not digit-shaped, so a name embedded in the
prose would pass a view intact. The views are an explicit whitelist, so a new column is invisible
to them by default; ``tests/test_readonly_query.py`` fails until the exclusion is recorded, which
is where the decision is written down.

No view depends on the column, so this needs no drop/recreate of the readonly schema.

Revision ID: b7d34e9a1c22
Revises: c4a71fe28b93
Create Date: 2026-08-30 01:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d34e9a1c22"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "c4a71fe28b93"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable column. Existing rows keep NULL — the value is only knowable at
    classification time, so there is nothing to backfill."""
    op.add_column("documents", sa.Column("document_name", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "document_name")
