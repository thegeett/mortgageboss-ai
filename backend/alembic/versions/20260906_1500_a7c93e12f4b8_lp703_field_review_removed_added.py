"""LP-703 — a correction the rule engine can read, and the column that lets it survive.

Three things, all on ``field_reviews``.

``replaced_value`` — what the model said at the moment a processor overruled it. A
review is keyed to one extraction version (ADR-393), so a re-extraction retires it,
correctly: a person's confirmation must not vouch for a figure they never saw. But a
processor who fixed a gross pay should not retype it every time the document is
re-read. With this column the next version can be asked a precise question — is the
model STILL saying the thing that was overruled? — so a correction carries forward
silently when the answer is yes, and waits for a person when the model has changed
its mind.

It holds an EXTRACTED value, which is as sensitive as the hand-typed one beside it,
so it joins ``corrected_value`` and ``note`` outside the readonly view. The view's
column list is explicit, so it needs no change; ``EXCLUDED`` in
``tests/test_readonly_query.py`` records the decision, and ``test_no_model_column_drifts``
is what would have failed if nobody made one.

``removed`` and ``added`` on the verdict set — the two operations that change what
the snapshot CONTAINS rather than recording an opinion about it.

AND THE CHECK THAT WAS NEVER THERE. The model declares ``verdict`` as
``str_enum(FieldVerdict)``, which emits ``ck_field_reviews_fieldverdict`` under
``create_all`` — so the test suite has always had a constraint that no migrated
database has. LP-UI-033's migration created the column as a bare ``String(50)``.
A verdict value outside the enum was therefore rejected in tests and accepted in
staging, which is the wrong way round: the environment with real data was the
lenient one. Adding the two new values is the moment to notice, because a value set
is exactly what a CHECK is for.

(One drift is left alone deliberately: the column is ``VARCHAR(50)`` here and
``VARCHAR(32)`` in the model. Narrowing a column in a migration risks truncation for
no benefit — every value the CHECK now permits is under 32 characters, and the CHECK
is the constraint that actually governs. Recorded on the ticket rather than fixed
quietly.)

Hand-written, like every migration against this schema.

Revision ID: a7c93e12f4b8
Revises: d7e3a9b41f02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7c93e12f4b8"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "d7e3a9b41f02"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_field_reviews_fieldverdict"

# The full value set, in model-definition order. LISTED IN FULL because the constraint is
# recreated from this tuple: a partial list here would revoke the values it omits.
_NEW_VALUES = ("accepted", "corrected", "rejected", "removed", "added")
_OLD_VALUES = ("accepted", "corrected", "rejected")


def _swap_check(values: tuple[str, ...]) -> None:
    """Recreate the verdict CHECK with ``values``.

    ``IF EXISTS`` on the drop because this migration ADDS the constraint on a database
    that never had one — a plain DROP would fail on every environment migrated before
    today, which is all of them.
    """
    joined = ", ".join(f"'{value}'" for value in values)
    op.execute(f"ALTER TABLE field_reviews DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE field_reviews ADD CONSTRAINT {_CONSTRAINT} CHECK (verdict IN ({joined}))"
    )


def upgrade() -> None:
    op.add_column(
        "field_reviews",
        sa.Column("replaced_value", sa.String(1000), nullable=True),
    )
    _swap_check(_NEW_VALUES)


def downgrade() -> None:
    """Back to three verdicts — after removing the rows the other two created.

    THE DELETE IS NOT OPTIONAL. A CHECK is validated against existing rows when it is
    added, so a database holding a single ``removed`` verdict would refuse the
    narrowed constraint and the downgrade would fail halfway. Soft-deleting them
    instead would leave rows the new constraint still rejects; they are removed
    outright, and the activity log keeps the trail either way.
    """
    op.execute("DELETE FROM field_reviews WHERE verdict IN ('removed', 'added')")
    _swap_check(_OLD_VALUES)
    op.drop_column("field_reviews", "replaced_value")
