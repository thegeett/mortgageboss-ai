"""LP-635 — scrub ``verifications.error_detail`` in the readonly view.

C7 scrubs ``error_detail`` on ``readonly.communications`` and selects the identically-named column
BARE on ``readonly.verifications``. That asymmetry was defensible while the column only ever held
strings this repo composed: an engine-written reason has no borrower in it.

LP-635 widened who writes it. `_failure_detail` now asks an exception to explain itself through a
``user_detail`` attribute and writes the result verbatim, so the column's safety became a promise
about every exception that might ever define that attribute — the same "relies on every future call
site honouring it" shape that was just removed from `AiBackendUnavailable`'s constructor,
reintroduced one level up at the protocol.

`scrub` only redacts identifier SHAPES (``NNN-NN-NNNN``, ``NNN NN NNNN``, runs of nine or more
digits), which is why this is close to free. Verified against the live function:

    'The AI backend failed 5 calls in a row. Re-run …'  ->  unchanged
    'Verification ran out of time before it finished.'  ->  unchanged
    'failed for borrower 123-45-6789 on account 987654321'
                                                       ->  'failed for borrower [REDACTED-ID] on
                                                            account [REDACTED-ID]'

So today's messages read exactly as written, and the one thing that must never reach a transcript
cannot, whatever a future exception decides to say about itself.

The view SQL is INLINE in each function rather than hoisted into module constants — see the LP-635
migration that precedes this one for why that is load-bearing rather than style.

Revision ID: e3f7a1c9d4b2
Revises: ac1e2bddc9d1
Create Date: 2026-08-31 00:10:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3f7a1c9d4b2"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "ac1e2bddc9d1"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Wrap the column in ``readonly.scrub``.

    CREATE OR REPLACE is enough: the column list keeps its names, order and types, and only the
    expression behind ``error_detail`` changes.
    """
    op.execute(
        """
        CREATE OR REPLACE VIEW readonly.verifications AS
        SELECT id, loan_file_id, status, trigger, started_at, completed_at,
               red_count, yellow_count, green_count,
               total_tokens_used, total_cost_estimate,
               readonly.scrub(error_detail) AS error_detail,
               input_fingerprint,
               created_at, updated_at, deleted_at,
               cross_check_count, time_limit_seconds
        FROM public.verifications
        """
    )


def downgrade() -> None:
    """Back to the bare column."""
    op.execute(
        """
        CREATE OR REPLACE VIEW readonly.verifications AS
        SELECT id, loan_file_id, status, trigger, started_at, completed_at,
               red_count, yellow_count, green_count,
               total_tokens_used, total_cost_estimate, error_detail, input_fingerprint,
               created_at, updated_at, deleted_at,
               cross_check_count, time_limit_seconds
        FROM public.verifications
        """
    )
