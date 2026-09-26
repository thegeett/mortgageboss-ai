"""LP-912 — the two status tracks move: eight columns, four CHECKs, and the view rebuilt (ADR-408).

EVERY CHECK CONSTRAINT HERE IS RAW SQL, AND THE FIRST VERSION OF THIS FILE USED `op.*` AND WAS
WRONG. `Base.metadata` carries a naming convention (`app/models/base.py`) whose `ck` template is
`ck_%(table_name)s_%(constraint_name)s`, so Alembic's `op.create_check_constraint` and
`op.drop_constraint` RE-PREFIX a name that already carries the prefix:
`ck_conditions_ownerhintsource` becomes `ck_conditions_ck_conditions_ownerhintsource`. Measured
against a scratch database, not reasoned about. Every other migration in this directory (~20 of them)
uses `op.execute("ALTER TABLE ... ADD CONSTRAINT ...")` for exactly this reason, and LP-71's migration
states it in as many words: "does not re-prefix it (`op.drop_constraint` would otherwise build ...)".

TWO PRE-EXISTING FACTS THIS FILE HAS TO COPE WITH, both found while verifying the above.

1. **LP-904's condition CHECKs are DOUBLE-PREFIXED in any migrated database.** It declared them as
   `sa.CheckConstraint(..., name="ck_conditions_...")` inside `create_table`, so the convention
   doubled every one. The TEST database does not have those names at all: `conftest` builds from
   `Base.metadata.create_all`, where `str_enum` passes only the enum's own name and the convention
   produces the SINGLE form. So production and the suite disagree about what these constraints are
   called, which is why nothing has ever noticed.

2. **`b6d1e93f57ac` (LP-909) is therefore broken on any migrated database, and this file fixes it.**
   Its raw `ADD CONSTRAINT ck_condition_events_conditioneventkind` created the SINGLE name with 11
   values, while LP-904's DOUBLED name with 10 values was still there — and its
   `DROP ... IF EXISTS <single>` was a no-op, because the single name did not yet exist. A column's
   effective constraint is the **AND** of all of them, so `round_reparse_requested` has been rejected
   since LP-909 shipped. Dropping both names below is what repairs it.

   The other five doubled LP-904 constraints (`bucketkind`, `ownerhint`, `conditionprepstatus`,
   `conditionlenderstatus`, `conditionorigin`) are left alone: each exists only once, so each is
   FUNCTIONALLY correct and merely oddly named. They are a landmine for the next migration that swaps
   one by its single name — recorded in `docs/tickets/LP-912.md` with a follow-up rather than fixed
   here, because renaming five constraints is not this ticket's job.

THE CANONICAL NAME IS THE SINGLE-PREFIXED ONE. It is what raw SQL produces, what `create_all`
produces in the suite, and what `tests/test_activity_type_migrations.py::_CASES` lists. Each swap below
therefore drops BOTH spellings with `IF EXISTS` and adds the single one.

FOUR HELPERS, EACH NAMING EXACTLY ONE CONSTRAINT, AND THAT IS A REQUIREMENT RATHER THAN A STYLE.
The guard in `_swap_helper_constraints` collects every `ck_`-prefixed string in a helper's body and
reports a helper naming SEVERAL as unreadable rather than guessing. So the legacy double-prefixed names
are dropped in `upgrade()` itself, never inside a helper — a helper that mentioned both spellings would
make the guard unable to read this migration at all. `"swap"` in each helper's NAME is load-bearing for
the same reason: that is how the guard finds them. Two of the four install a constraint that did not
exist before; they are still drop-if-exists-then-add, which is what every swap in this directory does.

`readonly.conditions` IS REBUILT, with `CREATE VIEW` above `def downgrade(` and the rollback's copy
INLINE below it. `_later_view_redefinitions()` reads every `CREATE VIEW readonly.X` above that line as
the LIVE definition, so hoisting the rollback's version into a constant would make the drift guard
check a shape the database does not have (LP-1000 and LP-813 both hit it).

AND THE GRANT RUNS INSIDE `upgrade()`. Dropping a view drops its privileges and nothing else notices:
the rebuilt view has the right columns, passes the drift guard, and `mbai_readonly` cannot read it.
`test_every_migration_that_recreates_a_readonly_view_regrants_it` slices the `upgrade()` BODY precisely
so a module constant that is never executed cannot satisfy it. (`mbai_readonly` does not exist on a
developer machine, which is why the grant is wrapped in `IF EXISTS` — so this path is exercised on
staging and merely skipped locally.)

WHAT THE VIEW EXPOSES OF THE NEW COLUMNS. `prep_note` is dropped: prose a processor typed about one
borrower's file, where a name arrives in a shape no scrubber matches — it is in `EXCLUDED` and in
`NEVER_EXPOSED`. `verdict` is dropped as a column and projected as its PROVENANCE only, because
`source_kind` and `source_date` are what make "cleared on the 12th" checkable while
`verdict ->> 'note'` is the processor's own words. That pair cannot be protected by `NEVER_EXPOSED` —
the check is a `\bverdict\b` search of the select list and naming the column is how the provenance is
produced — so a test pins the view to those two keys instead.

Hand-written, like every migration against this schema.

Revision ID: f3a9c05d81e7
Revises: b6d1e93f57ac
Create Date: 2026-09-26 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3a9c05d81e7"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "b6d1e93f57ac"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The canonical (single-prefixed) names — see the docstring.
_OWNER_HINT_SOURCE_CK = "ck_conditions_ownerhintsource"
_EVENT_KIND_CK = "ck_condition_events_conditioneventkind"
_WAITING_ON_CK = "ck_conditions_waiting_on"
_OWNER_OVERRIDE_CK = "ck_conditions_owner_override"

#: The double-prefixed spellings LP-904 actually installed, dropped in `upgrade()` rather than inside
#: any helper. Listed as full literals because they are what the database holds, and a name built at
#: runtime would be unreadable to the migration guard and to the next person alike.
_LEGACY_DOUBLED = (
    ("conditions", "ck_conditions_ck_conditions_ownerhintsource"),
    ("condition_events", "ck_condition_events_ck_condition_events_conditioneventkind"),
)

#: `OwnerHintSource` with `manual` (A2). ALL FIVE: a swap recreates the constraint from this tuple
#: alone, and whatever it omits is revoked (the LP-UI-033 defect).
_OWNER_HINT_SOURCE = ("prefix", "bucket", "code_map", "none", "manual")

#: `OwnerHint`, unchanged. Spelled out because the two new columns constrain it and a migration cannot
#: rely on `create_all` to materialise a CHECK.
_OWNER_HINT = ("borrower", "title", "insurance", "lender", "broker", "processor", "unknown")

#: The eleven `ConditionEventKind` values before this migration, in enum order.
_EVENT_KIND_BEFORE = (
    "round_received",
    "round_parsed",
    "round_parse_failed",
    "round_reparse_requested",
    "round_imported",
    "round_discarded",
    "round_enriched",
    "condition_created",
    "condition_seen_again",
    "condition_note_added",
    "condition_edited",
)

#: 19 — the eleven above plus LP-912's six and LP-915's two, taken from the enum rather than a grep.
_EVENT_KIND_AFTER = (
    *_EVENT_KIND_BEFORE,
    "condition_prep_moved",
    "condition_verdict_recorded",
    "condition_reopened",
    "condition_came_back",
    "condition_owner_changed",
    "condition_superseded",
    "round_compared",
    "round_completeness_changed",
)

#: The eight kinds this migration adds — the rows a downgrade must delete before narrowing.
_EVENT_KIND_ADDED = _EVENT_KIND_AFTER[len(_EVENT_KIND_BEFORE) :]


def _in(column: str, values: Sequence[str]) -> str:
    return column + " IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _swap(table: str, constraint: str, condition: str) -> None:
    """Drop the constraint if it is there and add it from `condition`. Raw SQL, never `op.*`."""
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}")
    op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {constraint} CHECK ({condition})")


def _swap_owner_hint_source_check(values: Sequence[str]) -> None:
    """Rewrite `ck_conditions_ownerhintsource`. One constraint, named from one module constant."""
    _swap("conditions", _OWNER_HINT_SOURCE_CK, _in("owner_hint_source", values))


def _swap_event_kind_check(values: Sequence[str]) -> None:
    """Rewrite `ck_condition_events_conditioneventkind`. Its own helper, per the docstring."""
    _swap("condition_events", _EVENT_KIND_CK, _in("kind", values))


def _swap_waiting_on_check(values: Sequence[str]) -> None:
    """Install `ck_conditions_waiting_on`. NULL is permitted: the column is only set while waiting."""
    _swap("conditions", _WAITING_ON_CK, "waiting_on IS NULL OR " + _in("waiting_on", values))


def _swap_owner_override_check(values: Sequence[str]) -> None:
    """Install `ck_conditions_owner_override`. NULL means no override, which is the common case."""
    _swap(
        "conditions",
        _OWNER_OVERRIDE_CK,
        "owner_override IS NULL OR " + _in("owner_override", values),
    )


def upgrade() -> None:
    # --- the eight columns -------------------------------------------------
    op.add_column("conditions", sa.Column("waiting_on", sa.String(32), nullable=True))
    op.add_column("conditions", sa.Column("prep_note", sa.String(256), nullable=True))
    op.add_column("conditions", sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "conditions", sa.Column("prep_status_changed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "conditions",
        sa.Column("lender_status_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("conditions", sa.Column("verdict", sa.dialects.postgresql.JSONB(), nullable=True))
    op.add_column("conditions", sa.Column("owner_override", sa.String(32), nullable=True))
    # SELF-REFERENTIAL, RESTRICT: the successor must not be deletable out from under a row whose whole
    # meaning is "see that one instead". Nothing disappears (spec §6 rule 3).
    op.add_column(
        "conditions",
        sa.Column(
            "superseded_by_id",
            sa.UUID(),
            sa.ForeignKey("conditions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )

    # --- LP-904's double-prefixed spellings, dropped here and not in a helper --------------------
    #
    # A migrated database holds these; the suite's `create_all` database does not. Dropping the events
    # one is what repairs LP-909: its 10-value copy has been ANDed with the live constraint since that
    # migration shipped, rejecting `round_reparse_requested` the whole time.
    for table, legacy in _LEGACY_DOUBLED:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {legacy}")

    # --- the four CHECKs, each under its canonical single-prefixed name --------------------------
    _swap_owner_hint_source_check(_OWNER_HINT_SOURCE)
    _swap_event_kind_check(_EVENT_KIND_AFTER)
    _swap_waiting_on_check(_OWNER_HINT)
    _swap_owner_override_check(_OWNER_HINT)

    # --- `readonly.conditions` rebuilt for the new non-NPI columns -------------------------------
    #
    # `CREATE OR REPLACE VIEW` cannot change a column list, so this is DROP then CREATE — which takes
    # the privileges with the old view, hence the regrant below, inside this function.
    op.execute("DROP VIEW IF EXISTS readonly.conditions")
    op.execute(
        """
        CREATE VIEW readonly.conditions AS
        SELECT id, company_id, loan_file_id, lender_id,
               first_round_id, last_seen_round_id, sequence,
               lender_code, lender_category, bucket_heading, bucket_kind,
               text_fingerprint, owner_hint, owner_hint_source,
               owner_override,
               COALESCE(owner_override, owner_hint) AS effective_owner,
               info_only, canonical_type_id, prep_status, lender_status, origin,
               waiting_on, sent_at, prep_status_changed_at, lender_status_changed_at,
               superseded_by_id,
               (verdict ->> 'source_kind') AS verdict_source_kind,
               (verdict ->> 'source_date') AS verdict_source_date,
               jsonb_array_length(underwriter_notes) AS underwriter_note_count,
               created_at, updated_at, deleted_at
        FROM public.conditions
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
                EXECUTE 'GRANT SELECT ON readonly.conditions TO mbai_readonly';
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    # INLINE, not a module constant: `_later_view_redefinitions()` reads every `CREATE VIEW
    # readonly.X` ABOVE `def downgrade(` as the LIVE definition, so hoisting this would make the drift
    # guard check a shape the database does not have. This is LP-904's definition, restored verbatim.
    op.execute("DROP VIEW IF EXISTS readonly.conditions")
    op.execute(
        """
        CREATE VIEW readonly.conditions AS
        SELECT id, company_id, loan_file_id, lender_id,
               first_round_id, last_seen_round_id, sequence,
               lender_code, lender_category, bucket_heading, bucket_kind,
               text_fingerprint, owner_hint, owner_hint_source,
               info_only, canonical_type_id, prep_status, lender_status, origin,
               jsonb_array_length(underwriter_notes) AS underwriter_note_count,
               created_at, updated_at, deleted_at
        FROM public.conditions
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
                EXECUTE 'GRANT SELECT ON readonly.conditions TO mbai_readonly';
            END IF;
        END
        $$;
        """
    )

    # ROWS CARRYING A REVOKED VALUE ARE DELETED FIRST, or the ADD CONSTRAINT is rejected by them and
    # the downgrade cannot complete. `condition_events` is APPEND-ONLY and is what the history panels
    # render, so this is a real loss of audit trail — the honest consequence of removing values the
    # application has already written, and the reason a downgrade past this point is not routine.
    op.execute("DELETE FROM condition_events WHERE " + _in("kind", _EVENT_KIND_ADDED))
    _swap_event_kind_check(_EVENT_KIND_BEFORE)

    # A row whose source is `manual` would refuse the narrower constraint. `none` is the truthful value
    # once the override column is gone.
    op.execute(
        "UPDATE conditions SET owner_hint_source = 'none' WHERE owner_hint_source = 'manual'"
    )
    _swap_owner_hint_source_check(_OWNER_HINT_SOURCE[:-1])

    # NOT RESTORED: LP-904's double-prefixed spellings. A downgrade returns the schema to what that
    # migration MEANT — one constraint per column under the canonical name — rather than reinstating
    # the duplicate that made `round_reparse_requested` unwritable. Recorded because a downgrade that
    # is not an exact inverse should say so out loud.
    op.execute(f"ALTER TABLE conditions DROP CONSTRAINT IF EXISTS {_OWNER_OVERRIDE_CK}")
    op.execute(f"ALTER TABLE conditions DROP CONSTRAINT IF EXISTS {_WAITING_ON_CK}")

    op.drop_column("conditions", "superseded_by_id")
    op.drop_column("conditions", "owner_override")
    op.drop_column("conditions", "verdict")
    op.drop_column("conditions", "lender_status_changed_at")
    op.drop_column("conditions", "prep_status_changed_at")
    op.drop_column("conditions", "sent_at")
    op.drop_column("conditions", "prep_note")
    op.drop_column("conditions", "waiting_on")
