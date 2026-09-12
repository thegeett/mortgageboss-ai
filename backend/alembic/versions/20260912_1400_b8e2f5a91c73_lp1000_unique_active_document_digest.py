"""lp1000_unique_active_document_digest

The duplicate check becomes mutual exclusion, because a SELECT followed by an INSERT never was.

WHAT THIS CLOSES. `find_duplicate` runs in stage 1 of the bulk upload and the INSERT lands in stage
2, with an object-storage write PER FILE in between and the COMMIT after all of them — so the window
between "no duplicate" and "the row is visible" spans an upload, not a microsecond. Two requests for
the same loan file overlapping anywhere in there both read clean, both insert, and both commit. A
double-click does it; so does the email-triage worker racing a manual upload. LP-1000 recorded this
in `find_duplicate`'s own docstring and left it, on the grounds that the outcome was the state that
existed before that ticket. That is true and it is still a hole, and a UNIQUE INDEX is the only thing
that closes it — a lock narrows the window, the database refuses outright.

⚠️ LP-1000 SAID THIS COULD NOT BE DONE YET, AND THAT REASONING WAS WRONG. Its migration reads: "the
existing rows already hold the duplicates described above, so `CREATE UNIQUE INDEX` would fail
outright until they are reconciled". It would not. Every row predating LP-1000 has
`content_sha256 IS NULL` — nothing backfills it — and this index is PARTIAL on
`content_sha256 IS NOT NULL`, so those rows are not in it at all. (Postgres would treat NULLs as
distinct even in a total index; the predicate makes it explicit rather than incidental.) The 22
duplicate groups measured on staging were found by PROXY — `(loan_file, document_type,
file_size_bytes)` — not by digest, and they carry no digests to collide. So the cleanup LP-1000
treated as a prerequisite is not one, and the constraint is available today.

THE PREDICATE IS `deleted_at IS NULL`, AND IT MATCHES `only_active` EXACTLY. That is the filter
`find_duplicate` applies (`models/helpers.py:31`), so the index and the service agree on what a
duplicate IS. It deliberately does NOT include `is_current`: a replaced document stays active and
merely historical (`is_current=False`, `deleted_at` still NULL), which is why `find_duplicate` needed
an `exclude_id` at all — and an index that ignored superseded rows would disagree with the check
above it. A soft-deleted twin stays exempt, so a processor who deletes a bad upload can still
re-upload it.

REPLACING THE PLAIN INDEX RATHER THAN JOINING IT. `ix_documents_loan_file_content_sha256` covered the
same two columns without the predicate, and every query that reads them (`find_duplicate`, with and
without `exclude_id`) also filters `deleted_at IS NULL` — which is exactly the partial index's
predicate, so the planner can use it. Keeping both would cost a second write on every insert to serve
no query that exists.

NO VIEW CHANGE. `readonly.documents` already exposes `content_sha256` (LP-1000 recreated it for that),
and an index is not a column, so nothing about the read-only layer moves here.

⚠️ A COLLISION IS NOW AN `IntegrityError`, WHICH IS A 500 UNLESS SOMEBODY TRANSLATES IT. That is the
other half of this change and it lives in `create_document`: the insert runs inside `begin_nested()`
so the violation rolls back a SAVEPOINT rather than poisoning the session, and is re-raised as the
same `DuplicateDocumentError` the pre-check raises, naming the document that won the race. Without
that half this migration converts a friendly 409 into a 500, which is why they ship together.

Hand-written, like every migration against this schema.

Revision ID: b8e2f5a91c73
Revises: d5c1a8f3e720
Create Date: 2026-09-12 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8e2f5a91c73"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "d5c1a8f3e720"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The partial predicate, in one place — the model declares the same index for `create_all`-built
#: databases (tests, CI), and the two must not drift.
_ACTIVE_AND_HASHED = "deleted_at IS NULL AND content_sha256 IS NOT NULL"


#: Active rows that already share a digest on one loan file — what `CREATE UNIQUE INDEX` would fail
#: on, asked BEFORE it does.
_EXISTING_COLLISIONS = """
    SELECT loan_file_id::text AS loan_file_id,
           content_sha256,
           string_agg(id::text, ', ' ORDER BY created_at) AS ids
    FROM documents
    WHERE deleted_at IS NULL AND content_sha256 IS NOT NULL
    GROUP BY loan_file_id, content_sha256
    HAVING count(*) > 1
"""


def _refuse_rather_than_fail_obscurely() -> None:
    """Name the rows that would break the index, instead of letting Postgres raise over them.

    ⚠️ THE WINDOW THIS EXISTS FOR IS REAL, and the reasoning in the docstring above does not cover
    it. "Every pre-LP-1000 row has a NULL digest" is true, and says nothing about rows written AFTER
    LP-1000 shipped and BEFORE this migration runs — which is exactly the period in which the race
    being closed here still operates. One double-click in that window leaves two active rows with one
    digest, and `CREATE UNIQUE INDEX` then takes the deploy down with a bare driver error at the
    worst possible moment.

    IT DOES NOT RECONCILE THEM, deliberately. Choosing which copy survives is a judgment — the
    documents may have different filenames, different extractions, different findings already
    attached — and a migration silently picking one is how a person's work disappears. It reports
    what to look at and stops.
    """
    rows = op.get_bind().execute(sa.text(_EXISTING_COLLISIONS)).mappings().all()
    if not rows:
        return
    detail = "\n".join(
        f"  loan_file {row['loan_file_id']} · digest {row['content_sha256'][:12]}… · ids {row['ids']}"
        for row in rows
    )
    raise RuntimeError(
        f"{len(rows)} group(s) of active documents already share a content digest on one loan "
        f"file, so the unique index cannot be created yet:\n{detail}\n"
        "Soft-delete the redundant copy in each group (keeping the one whose extractions and "
        "findings you want to preserve), then run this migration again."
    )


def upgrade() -> None:
    _refuse_rather_than_fail_obscurely()
    op.create_index(
        "uq_documents_loan_file_content_sha256",
        "documents",
        ["loan_file_id", "content_sha256"],
        unique=True,
        postgresql_where=sa.text(_ACTIVE_AND_HASHED),
    )
    # Dropped AFTER the replacement exists, so no window has neither index.
    op.drop_index("ix_documents_loan_file_content_sha256", table_name="documents")


def downgrade() -> None:
    op.create_index(
        "ix_documents_loan_file_content_sha256",
        "documents",
        ["loan_file_id", "content_sha256"],
    )
    op.drop_index("uq_documents_loan_file_content_sha256", table_name="documents")
