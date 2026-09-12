"""lp1000_document_content_digest

The identity that did not exist: a SHA-256 of the uploaded bytes on every document.

Nothing in this system could express "is this the same document?". There was no hash, no checksum
and no digest on `documents`, and `create_document` performed no duplicate check at all — so the
only way to ask was to compare `file_size_bytes` and hope. The one duplicate mechanism that exists
(`Document.possible_duplicate`, LP-33) runs ONLY on the email-triage path, tests by document TYPE
rather than content, and its own docstring records that nothing has ever written True to it.

What that cost, measured on staging before this ran: 22 groups of (loan file, type, byte size) held
more than one copy, across eight document types — pay stubs, bank statements, mortgage statements,
lease agreements, a credit report, purchase agreements, a USCIS notice. Three purchase-agreement
pairs were byte-identical at 3,037,074 bytes, one of each pair named `… (1).pdf` — the rename a
browser makes when the same file is downloaded twice. And one file carried the same credit report
twice, each extraction listing the same 24 tradelines, so every row-level gather over that file saw
48 rows where 24 exist.

NULLABLE, AND IT STAYS NULLABLE. Every row predating this column has no digest and there is nothing
to backfill from without re-reading every blob out of object storage. A NULL therefore means
"uploaded before LP-1000", never "this file has no content", and the duplicate check treats NULL as
no-match — the fail-open direction, on purpose: refusing an upload because an old row happens to be
unhashed is a worse error than accepting a duplicate.

AN INDEX, NOT A UNIQUE CONSTRAINT. The lookup is always (this loan file, this digest), so the index
carries both. Uniqueness is deliberately NOT enforced in the database: the existing rows already
hold the duplicates described above, so `CREATE UNIQUE INDEX` would fail outright until they are
reconciled — and a constraint would turn the collision into a 500 where the service raises a 409
naming the document that was already there. Worth revisiting once the existing duplicates are
cleaned up; the column and index are what make that cleanup possible to write.

EXPOSED IN `readonly.documents`, deliberately, which is why this migration recreates the view. A
digest is not content — it is a fixed-width hex fingerprint that reveals nothing about the bytes it
covers, unlike `full_text` or `summary`, which C7 drops because a scrub matching identifier SHAPES
cannot redact prose. And it is the column that makes "are these two documents the same?" answerable
from the read-only layer at all: the investigation that produced this ticket had to proxy the
question with `file_size_bytes`, which cannot distinguish two different 3 MB scans from one file
uploaded twice.

Hand-written, like every migration against this schema.

Revision ID: d5c1a8f3e720
Revises: c7d2e94f1a35
Create Date: 2026-09-12 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5c1a8f3e720"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "c7d2e94f1a35"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The grant is conditional because the role exists in the deployed environments and not in a local
#: or CI database built by `create_all` — the same shape every readonly migration uses. Safe as a
#: module constant: `tests/test_readonly_query.py` scans for `CREATE ... VIEW ... FROM public.<t>`,
#: and a GRANT is neither.
_GRANT = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
        EXECUTE 'GRANT SELECT ON readonly.documents TO mbai_readonly';
    END IF;
END
$$;
"""

# ⚠️ THE VIEW SQL STAYS INSIDE THE FUNCTION THAT RUNS IT, and the first cut of this migration got it
# wrong. Both statements were hoisted to module constants, which put the ROLLBACK definition above
# `def downgrade(` — the line the drift scanner in `tests/test_readonly_query.py` splits on to find
# what the live database has. The rollback then won, the guard checked a definition the database
# does not hold, and `_later_view_redefinitions()` raised: 24 failures in that file, from 0.


def upgrade() -> None:
    op.add_column("documents", sa.Column("content_sha256", sa.String(length=64), nullable=True))
    op.create_index(
        "ix_documents_loan_file_content_sha256",
        "documents",
        ["loan_file_id", "content_sha256"],
    )
    # Dropped before recreating, because `CREATE OR REPLACE VIEW` cannot add a column in the MIDDLE
    # of the list, and appending `content_sha256` at the end would leave the readonly column order
    # diverging from the table's for no reason.
    #
    # The column list is C7's plus `content_sha256`. `original_filename` keeps its scrub, and
    # `full_text` / `generic_analysis` / `summary` / `storage_path` / `document_name` stay dropped —
    # this view is an explicit whitelist, so recreating it must not quietly widen anything else.
    op.execute("DROP VIEW IF EXISTS readonly.documents")
    op.execute(
        """
        CREATE VIEW readonly.documents AS
        SELECT id, loan_file_id,
               readonly.scrub(original_filename) AS original_filename,
               mime_type, file_size_bytes, content_sha256, document_type, category,
               classification_confidence, status, processing_error, upload_source,
               tier, version, is_current, version_group_id, supersedes_document_id,
               staleness_resolution, possible_duplicate, uploaded_by_user_id,
               created_at, updated_at, deleted_at
        FROM public.documents
        """
    )
    op.execute(_GRANT)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS readonly.documents")
    # C7's definition, restored exactly — without `content_sha256`, which the column drop below
    # would otherwise leave the view referencing.
    op.execute(
        """
        CREATE VIEW readonly.documents AS
        SELECT id, loan_file_id,
               readonly.scrub(original_filename) AS original_filename,
               mime_type, file_size_bytes, document_type, category,
               classification_confidence, status, processing_error, upload_source,
               tier, version, is_current, version_group_id, supersedes_document_id,
               staleness_resolution, possible_duplicate, uploaded_by_user_id,
               created_at, updated_at, deleted_at
        FROM public.documents
        """
    )
    op.execute(_GRANT)
    op.drop_index("ix_documents_loan_file_content_sha256", table_name="documents")
    op.drop_column("documents", "content_sha256")
