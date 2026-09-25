"""LP-909 — one new condition event kind for the reparse, and the whole CHECK rewritten to keep it.

`ROUND_REPARSE_REQUESTED` is what `POST /api/condition-rounds/{round_id}/reparse` writes. Adding it
means rewriting the `condition_events.kind` CHECK, because `str_enum` (ADR-037) stores these as
VARCHAR + CHECK rather than as a native enum — so the enum member alone changes what the CODE writes
and nothing about what the database accepts.

⚠️ NO TEST WOULD HAVE DEMANDED THIS FILE, AND THAT IS WHY IT IS EASY TO SKIP. `tests/conftest.py`
builds the schema with `Base.metadata.create_all`, which regenerates the CHECK from the very enum
being changed — so the suite is green against a database that would reject the value on the first
real write. That is precisely the LP-637 defect: `document_reprocessed` was added with no migration,
the suite was fully green throughout, and the first click on the endpoint would have raised
`IntegrityError` on commit.

⚠️ AND THE GUARD THAT CATCHES THAT FOR `activity_type` COULD NOT SEE THIS CONSTRAINT.
`tests/test_activity_type_migrations.py` hardcoded `ck_activity_logs_activitytype`, and its swap
detector requires a call whose function name contains "swap" — while `ck_condition_events_conditioneventkind`
had no swap at all, only the inline `sa.CheckConstraint` inside LP-904's `create_table`. The same
failure was therefore available one enum over, in a corner the guard could not reach. That guard is
widened in this commit to cover both constraints and to count a create-table ORIGIN as a definition.

⚠️ THE SWAP LISTS ALL ELEVEN VALUES, NOT JUST THE NEW ONE. Each swap DROPS the constraint and
recreates it from its own tuple, so whatever this tuple omits is REVOKED even though an earlier
definition permitted it — the defect LP-UI-033 shipped for `activity_type`, where four live values
were silently revoked.

⚠️ AND THE LIST CAME FROM THE ENUM AT RUNTIME, NOT FROM A GREP, for the reason LP-905's swap
records: grepping member declarations misses any that do not match the assumed shape, and the ten
below were taken from `[m.value for m in ConditionEventKind]` before `round_reparse_requested` was
added to the enum.

`_EXISTING` is a module constant unpacked with `*`, a form the guard's `ast` folder resolves
deliberately — it must stay a literal tuple it can fold, never a comprehension or a call.

Revision ID: b6d1e93f57ac
Revises: c4b8f1a72e95
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b6d1e93f57ac"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | None = "c4b8f1a72e95"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_condition_events_conditioneventkind"

#: Every value the enum declared before this migration — ten, in enum order, taken from the enum
#: itself rather than from a grep. LP-904 installed these inline inside `create_table`.
_EXISTING = (
    "round_received",
    "round_parsed",
    "round_parse_failed",
    "round_imported",
    "round_discarded",
    "round_enriched",
    "condition_created",
    "condition_seen_again",
    "condition_note_added",
    "condition_edited",
)

#: 11 — the ten above plus the one LP-909's reparse endpoint adds.
_NEW_VALUES = (*_EXISTING, "round_reparse_requested")


def _swap_check(values: tuple[str, ...]) -> None:
    joined = ", ".join(f"'{value}'" for value in values)
    op.execute(f"ALTER TABLE condition_events DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE condition_events ADD CONSTRAINT {_CONSTRAINT} CHECK (kind IN ({joined}))"
    )


def upgrade() -> None:
    """Permit `round_reparse_requested` alongside everything already permitted."""
    _swap_check(_NEW_VALUES)


def downgrade() -> None:
    """Back to the ten.

    ⚠️ ROWS CARRYING THE REVOKED VALUE ARE DELETED FIRST, or the ADD CONSTRAINT fails against them
    and the downgrade cannot complete. `condition_events` is APPEND-ONLY and is what screen S1-09
    renders as a round's history, so this is a real loss of audit trail — the honest consequence of
    removing a value the application has already written, and the reason a downgrade past this point
    is not a routine operation.
    """
    op.execute("DELETE FROM condition_events WHERE kind = 'round_reparse_requested'")
    _swap_check(_EXISTING)
