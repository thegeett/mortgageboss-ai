"""LP-925 — the round's package for the lender: one PDF and one note per ready condition.

- `condition_packages`: round, status (built / submitted), the rows as she sees and edits them, the DU
  re-run she marked done, and who submitted it when. Notes carry figures (NPI): excluded from the
  readonly layer.

RAW SQL, the DDL `create_all` prints (ADR-037, LP-932). No enum or event-kind change: Mark submitted
moves our status through Stage 2's `condition_prep_moved`.

Revision ID: 08828fa86ffc
Revises: 52239e18fd5d
Create Date: 2026-09-29 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "08828fa86ffc"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "52239e18fd5d"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE condition_packages (
            company_id UUID NOT NULL,
            loan_file_id UUID NOT NULL,
            round_id UUID,
            status VARCHAR(32) DEFAULT 'built' NOT NULL,
            rows JSONB NOT NULL,
            du_rerun_done_at TIMESTAMP WITH TIME ZONE,
            submitted_at TIMESTAMP WITH TIME ZONE,
            submitted_by_user_id UUID,
            id UUID NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            CONSTRAINT pk_condition_packages PRIMARY KEY (id),
            CONSTRAINT fk_condition_packages_company_id_companies FOREIGN KEY (company_id)
                REFERENCES companies (id) ON DELETE CASCADE,
            CONSTRAINT fk_condition_packages_loan_file_id_loan_files FOREIGN KEY (loan_file_id)
                REFERENCES loan_files (id) ON DELETE CASCADE,
            CONSTRAINT fk_condition_packages_round_id_condition_rounds FOREIGN KEY (round_id)
                REFERENCES condition_rounds (id) ON DELETE SET NULL,
            CONSTRAINT ck_condition_packages_packagestatus CHECK (status IN ('built', 'submitted')),
            CONSTRAINT fk_condition_packages_submitted_by_user_id_users
                FOREIGN KEY (submitted_by_user_id) REFERENCES users (id) ON DELETE SET NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_condition_packages_loan_file_id ON condition_packages (loan_file_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS condition_packages")
