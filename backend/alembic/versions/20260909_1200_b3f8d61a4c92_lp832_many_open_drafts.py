"""LP-832 — a request creates a new draft, so a file may hold several unsent ones.

Revision ID: b3f8d61a4c92
Revises: a6c3e8d47f21
Create Date: 2026-09-09 12:00:00

DROPS `uq_communications_open_draft`, the partial unique index on (loan_file_id, template_key)
where status = 'draft'. That index is the guarantee this ticket removes: a request now creates a
NEW draft each time, carrying everything requested since the last send, so more than one unsent
draft per file is the ordinary state rather than a bug.

WHAT IT WAS REALLY BUYING IS NOT LOST. LP-809's comment gave the reason as two near-simultaneous
requests each creating a draft "with no basis for choosing between them". Under the new model two
drafts are correct; two drafts each missing the OTHER's new document is not, and that is what a
concurrent pair produces when both compute the outstanding set from the same pre-state.
`add_needs_to_draft` takes a row lock on the loan file instead — a guarantee the application holds
rather than the index.

A NON-UNIQUE INDEX REPLACES IT on (loan_file_id, status): the drafts list, the header count and the
outstanding-set union all read by exactly that pair, and they went from "at most one row" to "as
many as the processor has made".

THE DOWNGRADE CAN FAIL, AND THAT IS CORRECT. Recreating a unique index over data this ticket makes
legal will raise if any file holds two unsent drafts — which is the state the upgrade exists to
allow. A downgrade that silently deleted drafts to fit the old shape would destroy a processor's
unsent work to satisfy a constraint; raising tells whoever is rolling back that there is a decision
to make. The message says which files, so it is answerable.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3f8d61a4c92"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "a6c3e8d47f21"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("uq_communications_open_draft", table_name="communications")
    op.create_index(
        "ix_communications_loan_file_status",
        "communications",
        ["loan_file_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_communications_loan_file_status", table_name="communications")
    # THE CHECK BEFORE THE INDEX, so the failure names the problem rather than reporting a
    # duplicate-key violation on an index the reader did not know was being created.
    conflicts = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT loan_file_id, template_key, count(*) AS n "
                "FROM communications "
                "WHERE status = 'draft' AND deleted_at IS NULL "
                "GROUP BY loan_file_id, template_key HAVING count(*) > 1"
            )
        )
        .fetchall()
    )
    if conflicts:
        raise RuntimeError(
            "Cannot restore uq_communications_open_draft: "
            f"{len(conflicts)} (loan_file, template_key) pair(s) hold more than one unsent draft, "
            "which LP-832 made legal. Send or delete the extras first — this migration will not "
            "choose which of a processor's unsent drafts to destroy. "
            f"Affected: {[(str(row[0]), row[1], row[2]) for row in conflicts]}"
        )
    op.create_index(
        "uq_communications_open_draft",
        "communications",
        ["loan_file_id", "template_key"],
        unique=True,
        postgresql_where=sa.text("status = 'draft' AND deleted_at IS NULL"),
    )
