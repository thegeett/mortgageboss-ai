"""LP-635 review — scrub ``extractions.error_detail`` in the readonly view.

THE SIBLING OF THE COLUMN JUST FIXED. Round 4 scrubbed ``verifications.error_detail`` because the
view selected it bare. There are three ``error_detail`` columns in the readonly schema and C7
scrubs exactly one of them:

    readonly.communications   scrub(error_detail)   <- C7, line 452
    readonly.verifications    error_detail          <- fixed in round 4
    readonly.extractions      error_detail          <- this one, still bare

And this is the one carrying the most sensitive text of the three. It is written from
``failure_detail(status, reasoning)``, i.e. ``result.reasoning`` — the model's FREE TEXT for why an
extraction failed.

The codebase already knows what that text can contain. ``app/tasks/document_processing.py`` refuses
to put it in the document's ``processing_error`` for exactly this reason:

    DON'T interpolate ``result.reasoning`` here: for an all-null-parse FAILED it is the model's
    free-text reasoning and can quote document details. The raw reason is already persisted in the
    FAILED extraction version's ``error_detail`` above, THE ACCESS-CONTROLLED PLACE FOR IT.

That reasoning holds only if the column really is access-controlled. Through ``readonly.extractions``
it was not: the query stage returns rows into a terminal and a transcript, which is the path the
whole C7 design exists to make safe to read.

Scrubbing costs nothing we want. ``scrub`` redacts identifier SHAPES only — ``NNN-NN-NNNN``, runs of
nine or more digits — so ordinary model prose passes through unchanged, while an SSN or an account
number quoted out of a W-2 does not.

Revision ID: f4a2c8e91b73
Revises: e3f7a1c9d4b2
Create Date: 2026-08-31 01:20:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4a2c8e91b73"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "e3f7a1c9d4b2"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Wrap the column in ``readonly.scrub``.

    ``CREATE OR REPLACE`` is enough: the column keeps its name, its type and its position, so no
    dependency is dropped and the grant is untouched — only the expression behind ``error_detail``
    changes.

    THE SQL IS INLINE, NOT HOISTED TO A MODULE CONSTANT, and that is not style. The readonly drift
    guard reads migrations as TEXT and treats everything above the rollback function as the live
    definition. Hoisting both statements to module constants puts the ROLLBACK one inside that
    slice, where it wins, and the guard then reports a freshly scrubbed column as bare. This
    migration's first draft did exactly that.

    Its second draft hit the other half: this very docstring quoted the marker the guard splits on,
    which truncated the slice above its own SQL and made the migration invisible. Both traps were
    recorded as latent one revision ago and both fired inside one file, which is why the guard now
    fails loudly instead — see ``tests/test_readonly_query.py``.
    """
    op.execute(
        """
        CREATE OR REPLACE VIEW readonly.extractions AS
        SELECT id, document_id, version, is_current,
               readonly.scrub_json(extracted_data) AS extracted_data,
               extraction_status, model_used, tokens_used, cost_estimate,
               confidence, confidence_source,
               readonly.scrub(error_detail) AS error_detail,
               created_at, updated_at, deleted_at
        FROM public.extractions
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE VIEW readonly.extractions AS
        SELECT id, document_id, version, is_current,
               readonly.scrub_json(extracted_data) AS extracted_data,
               extraction_status, model_used, tokens_used, cost_estimate,
               confidence, confidence_source, error_detail,
               created_at, updated_at, deleted_at
        FROM public.extractions
        """
    )
