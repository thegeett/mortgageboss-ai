"""LP-820 — three parties that had no address anywhere in the schema.

THE MEASUREMENT. LP-800 sorts 166 document types to eight parties; before this migration only one
could be written to. Counted: 113 borrower, 24 processor (who orders them and needs no request),
16 lender (reachable since LP-813 gave `lenders.contact_email` a writer) — and 13 across title,
agent, CPA, insurer and employer, of which only `title` and `agent` had even a ROLE on
`loan_file_participants`, and neither had anything writing one.

The build plan's words for the consequence are exact: those needs *"sit at PENDING forever, never
get `requested_at`, and are invisible to LP-814."* A per-party clock without a per-party address is
a reminder nobody can act on.

`employer`, `cpa` and `insurer` join the role tuple. The CHECK is recreated from its own COMPLETE
tuple (ADR-037) rather than altered — a swap that lists seven values because it forgot the three
being added is the failure this style exists to make visible.

NO VIEW REBUILD. `readonly.loan_file_participants` already exposes `role` and no column is added, so
the view is unchanged — noted because every other migration in this phase rebuilt one and its
absence here should read as checked rather than forgotten.

Hand-written, like every migration against this schema.

Revision ID: f4d7b2e91c58
Revises: e2a9c4f18b63
Create Date: 2026-09-09 15:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f4d7b2e91c58"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "e2a9c4f18b63"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLES_AFTER = (
    "borrower",
    "co_borrower",
    "loan_officer",
    "agent",
    "title",
    "underwriter",
    "employer",
    "cpa",
    "insurer",
    "other",
)
_ROLES_BEFORE = (
    "borrower",
    "co_borrower",
    "loan_officer",
    "agent",
    "title",
    "underwriter",
    "other",
)

_CONSTRAINT = "ck_loan_file_participants_role"


def _check(values: tuple[str, ...]) -> str:
    return "role IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    op.execute(f"ALTER TABLE loan_file_participants DROP CONSTRAINT {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE loan_file_participants ADD CONSTRAINT {_CONSTRAINT} "
        f"CHECK ({_check(_ROLES_AFTER)})"
    )


def downgrade() -> None:
    # A participant in one of the three new roles cannot be described by the older tuple. Rewritten
    # to `other`, which is true — they are somebody on the file who is not one of the roles that
    # existed — rather than deleted, because an address a processor typed in is not ours to discard.
    op.execute(
        "UPDATE loan_file_participants SET role = 'other' "
        "WHERE role IN ('employer', 'cpa', 'insurer')"
    )
    op.execute(f"ALTER TABLE loan_file_participants DROP CONSTRAINT {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE loan_file_participants ADD CONSTRAINT {_CONSTRAINT} "
        f"CHECK ({_check(_ROLES_BEFORE)})"
    )
