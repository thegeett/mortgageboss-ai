"""Merge the LP-UI-033 and LP-643 heads, and repair the activity_type CHECK.

TWO THINGS, and the second is the one that matters.

THE MERGE. `mbai-ui-improvement` and `bedrock_integration_with_rules_staging`
each grew their own migration lineage, so the merged branch has two alembic
heads and `alembic upgrade head` refuses to run at all. This joins them.

THE READONLY VIEWS for the two tables the other branch added. `tests/test_readonly_query.py`
lives on the UI branch, so `dti_custom_lines` and `tag_cache_entries` had never been put to
it — the merge is the first moment anyone is asked to decide, which is what that guard is
for. Both expose their structure and drop what a person typed or an AI wrote.

THE CHECK CONSTRAINT, which would have failed silently instead. `activity_type`
is a VARCHAR + CHECK (ADR-037), so every migration that adds a value REWRITES the
constraint with a complete list — and both lineages did, from a common ancestor
that had neither side's additions:

  * LP-UI-033 (``c3f81a24e7b9``) shipped 27 values including ``field_reviewed``
    and ``field_review_reverted``.
  * LP-643 (``b3f7a2d19c46``) shipped 29 including ``document_reprocessed``,
    ``dti_line_added``, ``dti_line_removed`` and ``dti_ungated``.

Neither list contains the other's. Whichever ran LAST would win, and the values it
had never heard of would be rejected by the database while remaining perfectly
valid members of the Python enum — so the failure arrives as an IntegrityError on
a processor's action (recording a field verdict, or ungating a DTI), not as
anything a test or a type checker would notice. Nothing in either branch is wrong;
the damage is done by the merge, which is why the repair belongs here.

The list below is the UNION, 31 values, verified equal to the merged
``ActivityType`` enum. Written out in model-definition order rather than derived
from the live schema: a migration that reads its own target from the database
cannot be reviewed and cannot repair a database that is already wrong.

Revision ID: d7e3a9b41f02
Revises: c3f81a24e7b9, 5d2c64e1abe8
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d7e3a9b41f02"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = (
    "c3f81a24e7b9",  # pragma: allowlist secret  (LP-UI-033 field_reviews)
    "5d2c64e1abe8",  # pragma: allowlist secret  (LP-644 tag cache meets LP-643)
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_activity_logs_activitytype"

#: The union of both lineages, in `ActivityType` order.
#:
#: NAMED `_NEW_VALUES` on purpose: `tests/test_activity_type_migrations.py` discovers swaps by
#: that name and by literal-eval, so a tuple called anything else is invisible to the guard —
#: which is how LP-UI-033's computed `_NEW_ACTIVITY_TYPES` slipped past it and let this merge
#: reach a state the guard was written to prevent.
_NEW_VALUES = (
    "file_created",
    "file_updated",
    "file_deleted",
    "status_changed",
    "document_uploaded",
    "document_processed",
    "document_type_overridden",
    "document_replaced",
    "document_staleness_resolved",
    "document_reprocessed",
    "finding_resolved",
    "finding_undone",
    "verification_run",
    "dti_overridden",
    "dti_line_added",
    "dti_line_removed",
    "dti_ungated",
    "ltv_overridden",
    "calculator_overridden",
    "lender_overlay_updated",
    "needs_item_created",
    "needs_item_satisfied",
    "needs_item_confirmed",
    "needs_item_adjusted",
    "needs_item_dismissed",
    "needs_item_waived",
    "communication_sent",
    "communication_received",
    "note_added",
    "field_reviewed",
    "field_review_reverted",
)


#: A processor's own DTI line (LP-643). The SHAPE is exposed — which section, how much, how
#: often — and the two free-text columns are not: `label` and `note` are typed by hand about one
#: borrower's file, and a hand-typed field is where an identifier arrives in a form no scrubber
#: predicts. Same decision, for the same reason, as `field_reviews.corrected_value`.
_DTI_CUSTOM_LINES_VIEW = """
    CREATE VIEW readonly.dti_custom_lines AS
    SELECT id, loan_file_id, section, value,
           (label IS NOT NULL) AS has_label,
           (note IS NOT NULL) AS has_note,
           created_at, updated_at, deleted_at
    FROM public.dti_custom_lines
    """

#: The AI tag cache (LP-644). `hit_count` and `cache_kind` are the whole operational question —
#: is the cache earning its keep — and they carry no borrower content. `cache_key` is a
#: fingerprint of raw transaction fields and `value` is the model's judgment about one
#: borrower's transaction; neither belongs in an analytics view, and neither is needed to answer
#: what this table exists to answer.
_TAG_CACHE_VIEW = """
    CREATE VIEW readonly.tag_cache_entries AS
    SELECT id, loan_file_id, cache_kind, hit_count, created_at, updated_at
    FROM public.tag_cache_entries
    """

_GRANT = """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON readonly.dti_custom_lines TO mbai_readonly';
            EXECUTE 'GRANT SELECT ON readonly.tag_cache_entries TO mbai_readonly';
        END IF;
    END
    $$;
    """


def _swap_check(values: tuple[str, ...]) -> None:
    joined = ", ".join(f"'{value}'" for value in values)
    op.execute(f"ALTER TABLE activity_logs DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE activity_logs ADD CONSTRAINT {_CONSTRAINT} "
        f"CHECK (activity_type IN ({joined}))"
    )


def upgrade() -> None:
    _swap_check(_NEW_VALUES)
    op.execute("DROP VIEW IF EXISTS readonly.dti_custom_lines")
    op.execute("DROP VIEW IF EXISTS readonly.tag_cache_entries")
    op.execute(_DTI_CUSTOM_LINES_VIEW)
    op.execute(_TAG_CACHE_VIEW)
    op.execute(_GRANT)


def downgrade() -> None:
    # No single correct target: the constraint before this depended on which head
    # ran last, and picking one would reject rows the other lineage wrote. The
    # constraint is left as the union, which accepts everything either lineage
    # can produce and rejects everything neither can.
    op.execute("DROP VIEW IF EXISTS readonly.dti_custom_lines")
    op.execute("DROP VIEW IF EXISTS readonly.tag_cache_entries")
