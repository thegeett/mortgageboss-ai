"""LP-89 validation_verdicts table (the rule/calculator validation aid)

Revision ID: f4d1a7c0e2b9
Revises: e3c9a1f5b2d7
Create Date: 2026-06-29 21:00:00.000000

Creates the ``validation_verdicts`` table (LP-89): the captured verdict on a grounded-starter
rule / calculator methodology item — the domain expert's (Priya's) judgment recorded during
her validation session (validated / corrected / flagged_remove / add_new). Company-scoped,
self-audited (actor + timestamps + corrected value). One active verdict per (company, item);
NULL item_id (ADD_NEW proposals) are exempt. Constraint/index names match the model so a
fresh ``create_all`` and this migration converge.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4d1a7c0e2b9"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "e3c9a1f5b2d7"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VERDICT_KINDS = ("validated", "corrected", "flagged_remove", "add_new")


def upgrade() -> None:
    """Create the validation_verdicts table."""
    op.create_table(
        "validation_verdicts",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.String(length=32), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(*_VERDICT_KINDS, name="ck_validation_verdicts_verdictkind", native_enum=False),
            nullable=False,
        ),
        sa.Column("corrected_value", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=128), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("recorded_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_validation_verdicts_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_user_id"],
            ["users.id"],
            name=op.f("fk_validation_verdicts_recorded_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_validation_verdicts")),
        sa.UniqueConstraint("company_id", "item_id", name="uq_validation_verdicts_company_item"),
    )
    op.create_index(
        op.f("ix_validation_verdicts_company_id"),
        "validation_verdicts",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_validation_verdicts_item_id"), "validation_verdicts", ["item_id"], unique=False
    )


def downgrade() -> None:
    """Drop the validation_verdicts table."""
    op.drop_index(op.f("ix_validation_verdicts_item_id"), table_name="validation_verdicts")
    op.drop_index(op.f("ix_validation_verdicts_company_id"), table_name="validation_verdicts")
    op.drop_table("validation_verdicts")
