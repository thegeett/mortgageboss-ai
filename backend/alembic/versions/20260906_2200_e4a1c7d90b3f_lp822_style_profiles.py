"""LP-822 — one row per processor holding the voice their drafts are written in.

WHY IT IS KEYED ON A USER AND NOT ON A LOAN FILE. Spec 4.1 wants drafted emails to sound like the
processor, and that collides with LP-810's scoping of the per-draft fact bundle to "the requested
needs plus borrower name and file basics — nothing else" (bug-008: a wide bundle reworded every
draft whenever anything in it changed). Voice belongs to a person and moves when they edit it;
facts belong to a draft and move when the file does. Two caches, keyed apart, so neither
invalidates the other.

NO ``company_id``. The row hangs off exactly one user, and a user carries their company, so scoping
is transitive — ADR-052's reasoning for file-owned children, applied to a user-owned row. A copy
here would be a second answer to "which company is this?" that drifts when a person moves, for a
column no query needs.

THE READONLY VIEW DROPS EVERY FREE-TEXT COLUMN, which is a stronger decision than it looks. The
exemplars are excerpts of real borrower-request emails, so they are the one place in this table
where another borrower's name, address or balance can end up — and unlike a scrubbable identifier,
a name has no shape to match. `greeting`, `closing` and `signature_block` are hand-typed for the
same reason `dti_custom_lines.label` is excluded: a hand-typed field is where an identifier arrives
in a form no scrubber predicts. The view answers how many people have set up a voice and when they
last changed it, and none of the content.

The view does NOT count the exemplars, and that is a deliberate cost. `cardinality(exemplars)`
would answer a genuinely useful operational question, but `tests/test_readonly_query.py` asserts
over the view TEXT that certain columns are never named in any select list at all — crude on
purpose, because a per-column exposure check can be satisfied by a column appearing in a predicate
about itself. `exemplars` is on that list for the strong reason above, so the count goes rather
than the guarantee. If the number is ever needed, it belongs in a maintained boolean or integer
column that carries no content, not in an expression over this one.

Hand-written, like every migration against this schema.

Revision ID: e4a1c7d90b3f
Revises: a7c93e12f4b8
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e4a1c7d90b3f"  # pragma: allowlist secret
down_revision: str | None = "a7c93e12f4b8"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VIEW = """
    CREATE VIEW readonly.style_profiles AS
    SELECT id, user_id,
           (signature_block <> '') AS has_signature_block,
           created_at, updated_at
    FROM public.style_profiles
    """

_GRANT = """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON readonly.style_profiles TO mbai_readonly';
        END IF;
    END
    $$;
    """


def upgrade() -> None:
    op.create_table(
        "style_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("greeting", sa.String(length=256), nullable=False),
        sa.Column("closing", sa.String(length=256), nullable=False),
        sa.Column("signature_block", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "exemplars",
            postgresql.ARRAY(sa.String(length=1200)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_style_profiles_user_id"),
    )
    op.create_index("ix_style_profiles_user_id", "style_profiles", ["user_id"])
    op.execute("DROP VIEW IF EXISTS readonly.style_profiles")
    op.execute(_VIEW)
    op.execute(_GRANT)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS readonly.style_profiles")
    op.drop_index("ix_style_profiles_user_id", table_name="style_profiles")
    op.drop_table("style_profiles")
