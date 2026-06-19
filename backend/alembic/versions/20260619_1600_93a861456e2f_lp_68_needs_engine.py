"""LP-68: needs-list engine — five-state lifecycle + disposition/source/reasoning

Revision ID: 93a861456e2f
Revises: 73cb809cbd56
Create Date: 2026-06-19 16:00:00.000000

Evolves ``needs_items`` for the LP-68 engine:

  * **status** — rename ``outstanding`` → ``pending`` (the default) and add
    ``verified`` + ``rejected`` (the document-arrival lifecycle:
    pending → received → verified|rejected; any → waived). ``requested`` is kept
    (LP-19 borrower-outreach, orthogonal).
  * **origin** — add ``floor`` / ``suggestion`` / ``ai_reasoning`` (the
    source-agnostic provenance: the deterministic floor, LP-67 suggestions, LP-69
    AI proposals).
  * **disposition** (new) — the human-confirmation lifecycle
    (proposed/confirmed/waived/dismissed; default proposed). Existing rows backfill
    to ``confirmed`` (they are real, pre-existing needs).
  * **reasoning** / **reason** (new TEXT) — the explainability "why" + the
    rejected/waived reason.
  * **source_finding_id** (new) — FK to ``document_findings`` (SET NULL) for a need
    ingested from an LP-67 finding-implication suggestion.

Enums are VARCHAR + CHECK (ADR-037), so the status/origin changes are CHECK swaps.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "93a861456e2f"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "73cb809cbd56"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS_CK = "ck_needs_items_needsitemstatus"
_ORIGIN_CK = "ck_needs_items_needsitemorigin"

_STATUS_NEW = ("pending", "requested", "received", "verified", "rejected", "waived")
_STATUS_OLD = ("outstanding", "requested", "received", "waived")
_ORIGIN_NEW = (
    "manual",
    "finding",
    "condition",
    "template",
    "floor",
    "suggestion",
    "ai_reasoning",
)
_ORIGIN_OLD = ("manual", "finding", "condition", "template")


def _drop_check(constraint: str) -> None:
    op.execute(f"ALTER TABLE needs_items DROP CONSTRAINT {constraint}")


def _add_check(constraint: str, column: str, values: tuple[str, ...]) -> None:
    joined = ", ".join(f"'{v}'" for v in values)
    op.execute(
        f"ALTER TABLE needs_items ADD CONSTRAINT {constraint} CHECK ({column} IN ({joined}))"
    )


def upgrade() -> None:
    """Migrate status values, swap CHECKs, and add the LP-68 columns.

    Each CHECK swap is drop → migrate-data → add, so the data is updated while no
    CHECK constrains it (the new value 'pending' is invalid under the old CHECK).
    """
    # 1) status: drop CHECK, rename outstanding → pending, re-add the widened CHECK.
    _drop_check(_STATUS_CK)
    op.execute("UPDATE needs_items SET status = 'pending' WHERE status = 'outstanding'")
    _add_check(_STATUS_CK, "status", _STATUS_NEW)
    # 2) origin: widen the CHECK to include the new source values (no data change).
    _drop_check(_ORIGIN_CK)
    _add_check(_ORIGIN_CK, "origin", _ORIGIN_NEW)

    # 3) disposition — new; existing rows are real needs → confirmed.
    op.add_column(
        "needs_items",
        sa.Column(
            "disposition",
            sa.Enum(
                "proposed",
                "confirmed",
                "waived",
                "dismissed",
                name="needsitemdisposition",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
            server_default="proposed",
        ),
    )
    op.execute("UPDATE needs_items SET disposition = 'confirmed'")
    op.create_index(
        op.f("ix_needs_items_disposition"), "needs_items", ["disposition"], unique=False
    )

    # 4) reasoning + reason (explainability + rejected/waived reason).
    op.add_column("needs_items", sa.Column("reasoning", sa.Text(), nullable=True))
    op.add_column("needs_items", sa.Column("reason", sa.Text(), nullable=True))

    # 5) source_finding_id → document_findings (SET NULL).
    op.add_column("needs_items", sa.Column("source_finding_id", sa.Uuid(), nullable=True))
    op.create_index(
        op.f("ix_needs_items_source_finding_id"),
        "needs_items",
        ["source_finding_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_needs_items_source_finding_id_document_findings"),
        "needs_items",
        "document_findings",
        ["source_finding_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Reverse: drop the new columns + restore the original status/origin CHECKs."""
    op.drop_constraint(
        op.f("fk_needs_items_source_finding_id_document_findings"),
        "needs_items",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_needs_items_source_finding_id"), table_name="needs_items")
    op.drop_column("needs_items", "source_finding_id")
    op.drop_column("needs_items", "reason")
    op.drop_column("needs_items", "reasoning")
    op.drop_index(op.f("ix_needs_items_disposition"), table_name="needs_items")
    op.drop_column("needs_items", "disposition")

    # origin: drop CHECK, collapse the new sources to manual, re-add the old CHECK.
    _drop_check(_ORIGIN_CK)
    op.execute(
        "UPDATE needs_items SET origin = 'manual' "
        "WHERE origin IN ('floor', 'suggestion', 'ai_reasoning')"
    )
    _add_check(_ORIGIN_CK, "origin", _ORIGIN_OLD)
    # status: drop CHECK, collapse the new states to old ones, re-add the old CHECK.
    _drop_check(_STATUS_CK)
    op.execute("UPDATE needs_items SET status = 'received' WHERE status = 'verified'")
    op.execute(
        "UPDATE needs_items SET status = 'outstanding' WHERE status IN ('pending', 'rejected')"
    )
    _add_check(_STATUS_CK, "status", _STATUS_OLD)
