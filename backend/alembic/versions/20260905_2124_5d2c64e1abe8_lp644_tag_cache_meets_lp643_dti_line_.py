"""Join the two migration chains the raspberrypi-work merge created.

A MERGE REVISION ONLY — no schema change, no data change. Both sides are already correct; what was
missing is a single head for `alembic upgrade head` to aim at.

WHY THERE WERE TWO. `bedrock_integration_with_rules_staging` and `raspberrypi-work` each added a
migration after their common ancestor, so the chain forked:

    c8b1e47da920 -> a1c8734a7978   LP-644, tag_cache_entries      (raspberrypi-work)
    e4a1c9f3b028 -> b3f7a2d19c46   LP-643, dti line activity types (this branch)

Merging the branches merged the FILES without merging the CHAIN — nothing in a normal git merge
notices that two revisions now claim to be head, and the test suite cannot see it either, because
`tests/conftest.py` builds its schema with `Base.metadata.create_all` and never runs a migration.
So it surfaced where it costs the most: a staging deploy, at the migration step, after both images
had already been built and pushed.

The deploy stopped safely — `b3f7a2d19c46` was the deployed head, the services were still on the
previous image, and nothing had been written. `a1c8734a7978` had not been applied.

THE GUARD FOR NEXT TIME is `alembic heads` returning exactly one line, and it is worth running after
any merge that touches `alembic/versions/`, not only before a deploy.
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "5d2c64e1abe8"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = (
    "a1c8734a7978",  # pragma: allowlist secret
    "b3f7a2d19c46",  # pragma: allowlist secret
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
