"""LP-932 — rename the 24 CHECK constraints a migrated database names differently from the models.

WHAT WAS DIFFERENT, MEASURED. A scratch database built by `alembic upgrade head` (at `fb263dfd0473`)
and one built by `Base.metadata.create_all`, compared column by column: 24 of 76 constrained columns
carry a different CHECK name. The full list, with how each came about, is in `docs/tickets/LP-932.md`.

- **19 doubled.** A migration passed an already-prefixed name (`name="ck_conditions_bucketkind"`) to
  `sa.CheckConstraint` or `op.create_check_constraint`, and `Base.metadata`'s naming convention
  prefixed it again. Two of them were then too long for PostgreSQL's 63-character limit and
  SQLAlchemy truncated them with a hash suffix (`..._conditionroundc_2acb`, `..._len_9a13`); those
  literals are what the databases hold, so they are what this file names.
- **5 named differently.** The migration named the constraint after the column
  (`ck_inbound_attachments_disposition`) where `str_enum` names it after the enum class
  (`..._attachmentdisposition`).

WHY RENAME WHEN THE VALUES ALREADY MATCH. A name is not what a write fails on, and
`test_migrated_checks_match_models.py` already compares values column by column. But every swap is
written against a name, and a swap by the model's name on a migrated database drops nothing and adds
a second CHECK beside the old one. Postgres ANDs them, which is exactly how LP-909 made
`round_reparse_requested` unwritable. After this, the name in the models is the name in every
database, and the guard now checks names too.

`RENAME CONSTRAINT` HAS NO `IF EXISTS`, SO EACH RENAME IS A `DO` BLOCK THAT READS THE CATALOG FIRST.
A database may hold either spelling: one migrated through this file's parents holds the old one; one
built another way, or where a later hand repair already renamed it, holds the new one.

- old present, new absent: rename.
- new present, old absent: already done; nothing to do.
- **both present: refuse.** That is two CHECKs on one column, the LP-909 shape. Which one is right is
  a decision, and dropping either is destructive, so the migration stops and names the table.
- **neither present: refuse.** The column has lost its CHECK, and renaming nothing would hide that.

Downgrade runs the same blocks with the names reversed, so earlier migrations' downgrades, which name
the old spellings (LP-521's, LP-912's), still find what they expect.

Constraint names are unique per table, not per schema, so the catalog lookups filter on `conrelid`.
No function here has `swap` in its name: `test_activity_type_migrations.py` reads any such function
as a constraint swap.

Revision ID: bac8810abe90
Revises: fb263dfd0473
Create Date: 2026-09-28 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "bac8810abe90"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "fb263dfd0473"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (table, name on a migrated database before this file, name the models give it)
_RENAMES: tuple[tuple[str, str, str], ...] = (
    # Doubled by the naming convention.
    (
        "communication_evidence",
        "ck_communication_evidence_ck_communication_evidence_event",
        "ck_communication_evidence_evidenceevent",
    ),
    (
        "condition_rounds",
        "ck_condition_rounds_ck_condition_rounds_conditionroundc_2acb",
        "ck_condition_rounds_conditionroundcompleteness",
    ),
    (
        "condition_rounds",
        "ck_condition_rounds_ck_condition_rounds_conditionsheetformat",
        "ck_condition_rounds_conditionsheetformat",
    ),
    (
        "condition_rounds",
        "ck_condition_rounds_ck_condition_rounds_conditionroundstatus",
        "ck_condition_rounds_conditionroundstatus",
    ),
    ("conditions", "ck_conditions_ck_conditions_bucketkind", "ck_conditions_bucketkind"),
    (
        "conditions",
        "ck_conditions_ck_conditions_conditionlenderstatus",
        "ck_conditions_conditionlenderstatus",
    ),
    ("conditions", "ck_conditions_ck_conditions_conditionorigin", "ck_conditions_conditionorigin"),
    ("conditions", "ck_conditions_ck_conditions_ownerhint", "ck_conditions_ownerhint"),
    (
        "conditions",
        "ck_conditions_ck_conditions_conditionprepstatus",
        "ck_conditions_conditionprepstatus",
    ),
    (
        "finding_events",
        "ck_finding_events_ck_finding_events_finding_event_from_outcome",
        "ck_finding_events_finding_event_from_outcome",
    ),
    (
        "finding_events",
        "ck_finding_events_ck_finding_events_finding_event_to_outcome",
        "ck_finding_events_finding_event_to_outcome",
    ),
    (
        "lender_condition_codes",
        "ck_lender_condition_codes_ck_lender_condition_codes_bucket_kind",
        "ck_lender_condition_codes_lender_condition_code_bucket_kind",
    ),
    (
        "lender_condition_codes",
        "ck_lender_condition_codes_ck_lender_condition_codes_owner_hint",
        "ck_lender_condition_codes_lender_condition_code_owner_hint",
    ),
    (
        "lender_condition_codes",
        "ck_lender_condition_codes_ck_lender_condition_codes_len_9a13",
        "ck_lender_condition_codes_lendercodestatus",
    ),
    (
        "lender_contacts",
        "ck_lender_contacts_ck_lender_contacts_role",
        "ck_lender_contacts_lendercontactrole",
    ),
    (
        "mailbox_connections",
        "ck_mailbox_connections_ck_mailbox_connections_kind",
        "ck_mailbox_connections_mailboxconnectionkind",
    ),
    (
        "mailbox_connections",
        "ck_mailbox_connections_ck_mailbox_connections_status",
        "ck_mailbox_connections_mailboxconnectionstatus",
    ),
    (
        "mailbox_connections",
        "ck_mailbox_connections_ck_mailbox_connections_verification",
        "ck_mailbox_connections_mailboxverification",
    ),
    (
        "reminder_snoozes",
        "ck_reminder_snoozes_ck_reminder_snoozes_kind",
        "ck_reminder_snoozes_reminderkind",
    ),
    # Named after the column rather than the enum.
    (
        "inbound_attachments",
        "ck_inbound_attachments_disposition",
        "ck_inbound_attachments_attachmentdisposition",
    ),
    (
        "inbound_attachments",
        "ck_inbound_attachments_safety_state",
        "ck_inbound_attachments_attachmentsafetystate",
    ),
    (
        "inbound_messages",
        "ck_inbound_messages_routingstate",
        "ck_inbound_messages_inboundroutingstate",
    ),
    (
        "loan_file_participants",
        "ck_loan_file_participants_role",
        "ck_loan_file_participants_participantrole",
    ),
    (
        "suppressed_addresses",
        "ck_suppressed_addresses_reason",
        "ck_suppressed_addresses_suppressionreason",
    ),
)


def _rename(table: str, old: str, new: str) -> None:
    """Rename one CHECK from ``old`` to ``new`` if ``old`` is what the table holds.

    See the module docstring for the four cases. Both refusals raise, so the whole migration rolls
    back in its transaction and nothing is left half-renamed.
    """
    op.execute(
        f"""
        DO $$
        DECLARE
            has_old boolean;
            has_new boolean;
        BEGIN
            SELECT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'public.{table}'::regclass AND contype = 'c' AND conname = '{old}'
            ) INTO has_old;
            SELECT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'public.{table}'::regclass AND contype = 'c' AND conname = '{new}'
            ) INTO has_new;
            IF has_old AND has_new THEN
                RAISE EXCEPTION USING MESSAGE = 'LP-932: {table} carries both {old} and {new}. '
                    || 'Two CHECKs on one column are ANDed; decide which is right and drop the '
                    || 'other by hand, then rerun. Nothing was changed.';
            ELSIF has_old THEN
                ALTER TABLE public.{table} RENAME CONSTRAINT {old} TO {new};
            ELSIF NOT has_new THEN
                RAISE EXCEPTION USING MESSAGE = 'LP-932: {table} has neither {old} nor {new}, '
                    || 'so the column has no CHECK to rename. Nothing was changed.';
            END IF;
        END
        $$
        """
    )


def upgrade() -> None:
    for table, old, new in _RENAMES:
        _rename(table, old, new)


def downgrade() -> None:
    for table, old, new in reversed(_RENAMES):
        _rename(table, new, old)
