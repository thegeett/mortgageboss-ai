"""LP-810 — the email-draft prose cache.

A PURE CACHE keyed on a hash of the facts, with no foreign key to anything. Same terms as
`finding_prose` and `needs_prose`: a row is a function of its key alone, so it can be truncated at
any time and two files whose facts coincide share the wording.

DETERMINISM IS WHY IT EXISTS, and it matters more here than in the two caches before it. LP-809
regenerates a draft on every add and every remove. Without a cache, a processor who adds one document
finds the other five paragraphs reworded underneath their cursor — bug-008's lesson arriving where it
does the most damage, on text a person has been editing.

THE VIEW DROPS THE BODY ENTIRELY rather than scrubbing it, which is stricter than `needs_prose`'s
treatment of `why` and deliberately so. A composed need reason is a sentence about one document; a
composed draft body is a whole borrower-facing email — a name, a list of what they owe us, and
whatever the model wrote around it. `readonly.communications` already drops `body` for exactly that
reason (C7: "outbound email to borrowers ... the envelope is enough to debug the comms pipeline; the
content never is"), and this table holds the same content one step earlier. Scrubbing catches the
identifier shapes it knows; an email is prose, and prose is where a name crosses intact.

What the view keeps answers the operational questions: how big the cache is, which template shape
each row replaces, and how old the entries are.

Hand-written, like every migration against this schema.

Revision ID: c9f1a4b73e08
Revises: b8d5e0a17c42
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9f1a4b73e08"  # pragma: allowlist secret
down_revision: str | None = "b8d5e0a17c42"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VIEW = """
    CREATE VIEW readonly.email_draft_prose AS
    SELECT fact_hash, template_key, created_at
    FROM public.email_draft_prose
    """

_GRANT = """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON readonly.email_draft_prose TO mbai_readonly';
        END IF;
    END
    $$;
    """


def upgrade() -> None:
    op.create_table(
        "email_draft_prose",
        sa.Column("fact_hash", sa.String(length=64), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("fact_hash"),
    )
    op.execute("DROP VIEW IF EXISTS readonly.email_draft_prose")
    op.execute(_VIEW)
    op.execute(_GRANT)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS readonly.email_draft_prose")
    op.drop_table("email_draft_prose")
