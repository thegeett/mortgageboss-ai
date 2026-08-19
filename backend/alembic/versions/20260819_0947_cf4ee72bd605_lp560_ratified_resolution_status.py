"""lp560 ratified resolution status

Revision ID: cf4ee72bd605
Revises: e91c4d7b3f65
Create Date: 2026-08-19 09:47:54.691440

"""

from collections.abc import Sequence

from alembic import op

# LP-560 — `ratified` records that a human reviewed an AI judgment and AGREED. The act ADR-336's safety
# story rests on: an uncalibrated judgment rule may run BECAUSE a person signs each verdict, and until
# now there was no way to perform that — the only route to clearing one was Override, so every
# agreement was recorded as a rejection.
# The name is not guessed: migration b8d3f06a1c54 already ran `DROP CONSTRAINT` on it against this
# database, so a wrong name would have failed there first. (LP-521 shipped a migration with an
# assumed constraint name and it failed on staging — worth checking rather than recalling.)
_CONSTRAINT = "ck_findings_findingresolutionstatus"
_OLD = ("open", "applied", "overridden", "resolved", "accepted_risk", "waived")
_NEW = (*_OLD, "ratified")


def _swap_check(values: tuple[str, ...]) -> None:
    joined = ", ".join(f"'{value}'" for value in values)
    op.execute(f"ALTER TABLE findings DROP CONSTRAINT {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE findings ADD CONSTRAINT {_CONSTRAINT} CHECK (resolution_status IN ({joined}))"
    )


# revision identifiers, used by Alembic.
revision: str = "cf4ee72bd605"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "e91c4d7b3f65"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Widen the resolution CHECK to admit `ratified`."""
    _swap_check(_NEW)


def downgrade() -> None:
    """Narrow it back. Any ratified row must be re-opened first, or the constraint would reject it —
    a ratification is a signature, so it is reopened rather than silently rewritten to another state."""
    op.execute(
        "UPDATE findings SET resolution_status = 'open' WHERE resolution_status = 'ratified'"
    )
    _swap_check(_OLD)
