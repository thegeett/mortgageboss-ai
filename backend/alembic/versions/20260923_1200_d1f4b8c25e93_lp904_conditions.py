"""LP-904 — the condition tables, and the four lender columns Stage 1 needs.

FOUR TABLES AND FOUR COLUMNS, designed once from the Stage 0 decisions rather than discovered while
writing them (ADR-403…407).

`condition_rounds` — one condition sheet received. `round_number` is assigned ON IMPORT, not on
arrival: two drafts can exist at once (an upload and a paste), and numbering on arrival would either
renumber later or leave gaps where a draft was discarded. `sources` is a LIST because a pasted round
whose PDF arrives afterwards MERGES into that round (LP-907) rather than starting a second one.

`conditions` — one lender demand, living across rounds. `verbatim_text` keeps the underwriter's dated
notes because the lender wrote one string; `text_fingerprint` is taken with those note spans REMOVED,
so a condition that comes back with a new note is still matched as the same condition. That is also
why the text never needs to be compared in SQL — the fingerprint is what the two import lookups run
on, and it has its own index.

`condition_events` — append-only, enforced BY SHAPE: no `updated_at` and no `deleted_at`, copying
`finding_events`. An `updated_at` on a row nothing updates can only ever lie.

`lender_condition_codes` — keyed `(lender_id, code)` and never on the code alone. `7086` is short
funds to close at UWM and means nothing at Champions, so a global table would be wrong on its first
row and the error would be invisible.

⚠️ CODES ARE `String(16)`, NOT INTEGERS, and `conditions.lender_code` likewise. UWM prints `0006`.
The leading zeros are part of an identifier printed on a document; normalising it to 6 is a silent
loss that resurfaces months later as a failed match.

THE CHECK CONSTRAINTS ARE WRITTEN OUT BY HAND. `str_enum` sets `create_constraint=True`, but that
only materialises through `Base.metadata.create_all` — which is what the test suite builds from, and
is precisely why a mismatch between the enum and a migrated database is invisible to the suite
(`tests/test_activity_type_migrations.py` exists because of exactly that). A hand-written migration
must spell the value set out.

NPI AND THE READONLY VIEWS (ADR-405). Every view below drops the lender's words rather than scrubbing
them: `readonly.scrub()` matches identifier SHAPES, and a condition quoting an employer or a street
address is not digit-shaped, so it would cross a scrubbed view intact. What the views DO expose is
everything an analyst actually asks — which reader ran, how many rows it found, how many duplicates
it dropped, whether AI was used, how many lines were left unassigned — as counts and booleans derived
in the view.

`readonly.lenders` IS REBUILT because the table gains four columns. The definition below is copied
from **C7's `_VIEWS` upgrade-side entry**, which is the shape the database has — LP-806 lost three
columns by copying from a DOWNGRADE block, and the drift guard is what caught it.

⚠️ THE DOWNGRADE'S VIEW SQL IS INLINE, NEVER A MODULE CONSTANT. `_later_view_redefinitions()` reads
every `CREATE VIEW readonly.X` **above** the line `def downgrade(` as the live definition, so a
hoisted rollback definition wins and the guard then checks a shape the database does not have. That
cost LP-1000's first migration 24 failures in `tests/test_readonly_query.py`, and LP-813 hit the same
trap before it.

Hand-written, like every migration against this schema.

Revision ID: d1f4b8c25e93
Revises: c9e4a7b12d36
Create Date: 2026-09-23 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d1f4b8c25e93"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "c9e4a7b12d36"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The enum value sets, spelled out because a migration cannot rely on create_all (see the docstring).
_ROUND_STATUS = ("parsing", "draft", "parse_failed", "imported", "discarded")
_COMPLETENESS = ("full", "partial")
_SHEET_FORMAT = ("uwm_approval_letter", "champions_certificate", "generic", "pasted_text")
_BUCKET_KIND = (
    "master",
    "prior_to_approval",
    "prior_to_docs",
    "prior_to_closing",
    "prior_to_funding",
    "lender_to_clear",
    "trailing",
    "unknown",
)
_OWNER_HINT = ("borrower", "title", "insurance", "lender", "broker", "processor", "unknown")
_OWNER_HINT_SOURCE = ("prefix", "bucket", "code_map", "none")
_PREP_STATUS = ("to_do", "waiting", "review", "ready", "with_underwriter")
_LENDER_STATUS = ("open", "pending_review", "cleared", "not_cleared", "waived", "superseded")
_CONDITION_ORIGIN = ("sheet", "manual")
_EVENT_KIND = (
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
_CODE_STATUS = ("seeded", "observed_unmapped", "mapped")


def _in(column: str, values: Sequence[str]) -> str:
    return column + " IN (" + ", ".join(f"'{v}'" for v in values) + ")"


# DROPPED: raw_text, header, draft_rows, parse_report (the lender's words, and lines lifted from the
# sheet verbatim inside `unassigned_lines`). The report's ANSWERS are exposed as derived scalars, so
# "which reader ran, how much did it find, how much did it leave over" stays answerable from staging
# without reproducing a line of the letter. `expiry_dates` is exposed whole: dates a lender publishes
# about a loan, naming nobody.
#
# `sources` IS EXPOSED WHOLE, and the first cut of this view got that wrong. It carried
# `jsonb_array_length(sources) AS source_count` — which the drift guard correctly refused to count as
# exposing `sources`, because `_output_columns` reduces each select item to the name it comes OUT as
# and a column mentioned in a predicate about itself is not exposed. The guard was right: the column
# has no borrower or lender content — arrival kinds, timestamps and internal ids — so the honest
# answer was to expose it rather than to exclude it, and "how did rounds arrive, pasted or uploaded"
# then stays answerable without a second derived column saying less.
_ROUNDS_VIEW = """
    CREATE VIEW readonly.condition_rounds AS
    SELECT id, company_id, loan_file_id, lender_id,
           round_number, status, completeness, sheet_format,
           date_printed, round_date, expiry_dates,
           sources,
           (parse_report ->> 'reader') AS reader,
           (parse_report ->> 'reader_version') AS reader_version,
           COALESCE((parse_report ->> 'ai_used')::boolean, false) AS ai_used,
           COALESCE((parse_report ->> 'duplicates_dropped')::int, 0) AS duplicates_dropped,
           COALESCE(jsonb_array_length(parse_report -> 'warnings'), 0) AS warning_count,
           COALESCE(jsonb_array_length(parse_report -> 'unassigned_lines'), 0) AS unassigned_count,
           COALESCE(jsonb_array_length(draft_rows), 0) AS draft_row_count,
           (raw_text IS NOT NULL) AS has_raw_text,
           (header IS NOT NULL) AS has_header,
           created_by_user_id, created_at, updated_at, deleted_at
    FROM public.condition_rounds
    """

# DROPPED: verbatim_text and underwriter_notes — the lender's words. `text_fingerprint` IS exposed:
# it is a sha256, and it is the column that lets the readonly layer answer "did this condition recur
# across rounds?" without reproducing any of it. The note COUNT is exposed for the same reason —
# "how often do conditions come back" is the analytic question, and the count carries no text.
#
# ⚠️ `verbatim_text` IS NOT NAMED HERE AT ALL, not even inside a `length()`. It is in the test
# suite's NEVER_EXPOSED list, which searches the select-list TEXT of every view, so a derived scalar
# over it would trip that guard — and the guard is worth more than the metric. `style_profiles` made
# the identical trade for `cardinality(exemplars)` and its migration says so. `underwriter_notes`
# goes the other way, as `communication_evidence.attachment_manifest` does: EXCLUDED and counted,
# because the count is the whole answer and the column name has to appear to produce it.
_CONDITIONS_VIEW = """
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

# DROPPED: detail. Unlike `finding_events.detail`, which is documented as PII-safe, this one holds
# WHAT CHANGED — an edited wording, an appended note, a bucket that moved — which is the lender's
# text. The event kind, the actor and the time answer the audit question without it.
_EVENTS_VIEW = """
    CREATE VIEW readonly.condition_events AS
    SELECT id, company_id, loan_file_id, round_id, condition_id,
           kind, actor_user_id, occurred_at
    FROM public.condition_events
    """

# NOTHING DROPPED. A template id, a label the lender publishes, and counts — nothing borrower-derived
# anywhere in the table, and the unmapped backlog is a question worth asking from staging.
_CODES_VIEW = """
    CREATE VIEW readonly.lender_condition_codes AS
    SELECT id, lender_id, code, label, canonical_type_id,
           default_bucket_kind, default_owner_hint, info_only,
           status, times_seen, first_seen_at, last_seen_at,
           created_at, updated_at
    FROM public.lender_condition_codes
    """

_GRANTS = """
    DO $$
    DECLARE v text;
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            FOREACH v IN ARRAY ARRAY['condition_rounds', 'conditions', 'condition_events',
                                     'lender_condition_codes', 'lenders']
            LOOP
                EXECUTE format('GRANT SELECT ON readonly.%I TO mbai_readonly', v);
            END LOOP;
        END IF;
    END
    $$;
    """


def upgrade() -> None:
    op.create_table(
        "condition_rounds",
        sa.Column("id", sa.UUID(), primary_key=True),
        # On the row rather than inherited through the loan file: a round is reached directly by id
        # from /api/condition-rounds/{id}, so the scoping filter needs a column here.
        sa.Column(
            "company_id",
            sa.UUID(),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "loan_file_id",
            sa.UUID(),
            sa.ForeignKey("loan_files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # RESTRICT: a lender with rounds against it must not be deletable out from under them.
        sa.Column(
            "lender_id", sa.UUID(), sa.ForeignKey("lenders.id", ondelete="RESTRICT"), nullable=True
        ),
        sa.Column("round_number", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="parsing"),
        sa.Column("sources", sa.dialects.postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("completeness", sa.String(32), nullable=False, server_default="full"),
        sa.Column("sheet_format", sa.String(32), nullable=False, server_default="generic"),
        sa.Column("date_printed", sa.Date(), nullable=True),
        sa.Column("round_date", sa.Date(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("header", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("expiry_dates", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("draft_rows", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "parse_report", sa.dialects.postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "created_by_user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            _in("status", _ROUND_STATUS), name="ck_condition_rounds_conditionroundstatus"
        ),
        sa.CheckConstraint(
            _in("completeness", _COMPLETENESS),
            name="ck_condition_rounds_conditionroundcompleteness",
        ),
        sa.CheckConstraint(
            _in("sheet_format", _SHEET_FORMAT), name="ck_condition_rounds_conditionsheetformat"
        ),
    )
    op.create_index("ix_condition_rounds_loan_file_id", "condition_rounds", ["loan_file_id"])
    op.create_index("ix_condition_rounds_company_id", "condition_rounds", ["company_id"])
    op.create_index(
        "ix_condition_rounds_file_status", "condition_rounds", ["loan_file_id", "status"]
    )
    # ONE ROUND NUMBER PER FILE, among IMPORTED and undeleted rows only. Partial because drafts have
    # no number (NULL, and NULLs do not conflict anyway) and a discarded or deleted round must not
    # hold its number hostage — the next import would then skip a number for no visible reason.
    op.execute(
        "CREATE UNIQUE INDEX uq_condition_rounds_file_number "
        "ON condition_rounds (loan_file_id, round_number) "
        "WHERE round_number IS NOT NULL AND deleted_at IS NULL AND status = 'imported'"
    )

    op.create_table(
        "conditions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "company_id",
            sa.UUID(),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "loan_file_id",
            sa.UUID(),
            sa.ForeignKey("loan_files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lender_id", sa.UUID(), sa.ForeignKey("lenders.id", ondelete="RESTRICT"), nullable=True
        ),
        # RESTRICT on both: a condition's provenance is which sheet it arrived on, and a round that
        # minted conditions must not vanish from under them.
        sa.Column(
            "first_round_id",
            sa.UUID(),
            sa.ForeignKey("condition_rounds.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_round_id",
            sa.UUID(),
            sa.ForeignKey("condition_rounds.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
        # String, not Integer — "0006" keeps its leading zeros (ADR-407).
        sa.Column("lender_code", sa.String(16), nullable=True),
        sa.Column("lender_category", sa.String(256), nullable=True),
        sa.Column("bucket_heading", sa.String(256), nullable=False),
        sa.Column("bucket_kind", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("verbatim_text", sa.Text(), nullable=False),
        sa.Column("text_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "underwriter_notes", sa.dialects.postgresql.JSONB(), nullable=False, server_default="[]"
        ),
        sa.Column("owner_hint", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("owner_hint_source", sa.String(32), nullable=False, server_default="none"),
        sa.Column("info_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("canonical_type_id", sa.String(64), nullable=True),
        sa.Column("prep_status", sa.String(32), nullable=False, server_default="to_do"),
        sa.Column("lender_status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("origin", sa.String(32), nullable=False, server_default="sheet"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_in("bucket_kind", _BUCKET_KIND), name="ck_conditions_bucketkind"),
        sa.CheckConstraint(_in("owner_hint", _OWNER_HINT), name="ck_conditions_ownerhint"),
        sa.CheckConstraint(
            _in("owner_hint_source", _OWNER_HINT_SOURCE), name="ck_conditions_ownerhintsource"
        ),
        sa.CheckConstraint(
            _in("prep_status", _PREP_STATUS), name="ck_conditions_conditionprepstatus"
        ),
        sa.CheckConstraint(
            _in("lender_status", _LENDER_STATUS), name="ck_conditions_conditionlenderstatus"
        ),
        sa.CheckConstraint(_in("origin", _CONDITION_ORIGIN), name="ck_conditions_conditionorigin"),
    )
    op.create_index("ix_conditions_loan_file_id", "conditions", ["loan_file_id"])
    op.create_index("ix_conditions_company_id", "conditions", ["company_id"])
    # The two lookups import performs, in order: (code, fingerprint), then fingerprint alone.
    op.create_index(
        "ix_conditions_file_lender_code", "conditions", ["loan_file_id", "lender_id", "lender_code"]
    )
    op.create_index(
        "ix_conditions_file_fingerprint", "conditions", ["loan_file_id", "text_fingerprint"]
    )

    op.create_table(
        "condition_events",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "company_id",
            sa.UUID(),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "loan_file_id",
            sa.UUID(),
            sa.ForeignKey("loan_files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "round_id",
            sa.UUID(),
            sa.ForeignKey("condition_rounds.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "condition_id",
            sa.UUID(),
            sa.ForeignKey("conditions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("detail", sa.dialects.postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_in("kind", _EVENT_KIND), name="ck_condition_events_conditioneventkind"),
        # NO created_at/updated_at/deleted_at — append-only by shape. `occurred_at` is the row's
        # own time, and an `updated_at` on a row nothing updates could only ever lie.
    )
    op.create_index(
        "ix_condition_events_round_occurred", "condition_events", ["round_id", "occurred_at"]
    )
    op.create_index(
        "ix_condition_events_condition_occurred",
        "condition_events",
        ["condition_id", "occurred_at"],
    )
    op.create_index("ix_condition_events_loan_file_id", "condition_events", ["loan_file_id"])

    op.create_table(
        "lender_condition_codes",
        sa.Column("id", sa.UUID(), primary_key=True),
        # CASCADE, unlike the tables above: a code map is metadata ABOUT a lender with no
        # borrower-derived content, so it should go with the lender rather than block its removal.
        sa.Column(
            "lender_id", sa.UUID(), sa.ForeignKey("lenders.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("label", sa.String(256), nullable=False),
        sa.Column("canonical_type_id", sa.String(64), nullable=True),
        sa.Column("default_bucket_kind", sa.String(32), nullable=True),
        sa.Column("default_owner_hint", sa.String(32), nullable=True),
        sa.Column("info_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(32), nullable=False, server_default="observed_unmapped"),
        sa.Column("times_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # The nullable defaults permit NULL: an observed code has no meaning until a person gives it
        # one, and a default that guessed would be indistinguishable from one that was chosen.
        sa.CheckConstraint(
            "default_bucket_kind IS NULL OR " + _in("default_bucket_kind", _BUCKET_KIND),
            name="ck_lender_condition_codes_bucket_kind",
        ),
        sa.CheckConstraint(
            "default_owner_hint IS NULL OR " + _in("default_owner_hint", _OWNER_HINT),
            name="ck_lender_condition_codes_owner_hint",
        ),
        sa.CheckConstraint(
            _in("status", _CODE_STATUS), name="ck_lender_condition_codes_lendercodestatus"
        ),
    )
    # THE KEY (ADR-407): unique per lender, never globally.
    op.create_index(
        "uq_lender_condition_codes_lender_code",
        "lender_condition_codes",
        ["lender_id", "code"],
        unique=True,
    )
    op.create_index(
        "ix_lender_condition_codes_lender_status", "lender_condition_codes", ["lender_id", "status"]
    )

    # --- the four lender columns ------------------------------------------
    op.add_column("lenders", sa.Column("canonical_lender_key", sa.String(64), nullable=True))
    op.add_column("lenders", sa.Column("mortgagee_clause", sa.Text(), nullable=True))
    op.add_column("lenders", sa.Column("condition_upload_cutoff", sa.String(64), nullable=True))
    op.add_column(
        "lenders",
        sa.Column(
            "condition_handling_notes",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
    )

    op.execute(_ROUNDS_VIEW)
    op.execute(_CONDITIONS_VIEW)
    op.execute(_EVENTS_VIEW)
    op.execute(_CODES_VIEW)

    # `readonly.lenders` REBUILT for the three exposed new columns. Copied from C7's `_VIEWS`
    # UPGRADE-side entry, which is the shape the database has.
    #
    # `condition_handling_notes` is NOT exposed: free prose an admin typed about a lender, which is
    # where a person's name arrives in a shape no scrubber predicts — the same reason
    # `lender_contacts.notes` is dropped. `mortgagee_clause` IS exposed: it is the lender's own
    # published mailing identity, printed on every sheet, and nothing borrower-derived.
    op.execute("DROP VIEW IF EXISTS readonly.lenders")
    op.execute(
        """
        CREATE VIEW readonly.lenders AS
        SELECT id, company_id, name, slug, portal_url,
               readonly.scrub(notes) AS notes,
               lender_overlays, supported_programs, is_active,
               canonical_lender_key, mortgagee_clause, condition_upload_cutoff,
               created_at, updated_at, deleted_at
        FROM public.lenders
        """
    )
    op.execute(_GRANTS)


def downgrade() -> None:
    # INLINE, not a module constant: `_later_view_redefinitions()` reads every `CREATE VIEW
    # readonly.X` ABOVE `def downgrade(` as the LIVE definition, so hoisting this one would make the
    # drift guard check a shape the database does not have. LP-1000 and LP-813 both hit it.
    op.execute("DROP VIEW IF EXISTS readonly.lenders")
    op.execute(
        """
        CREATE VIEW readonly.lenders AS
        SELECT id, company_id, name, slug, portal_url,
               readonly.scrub(notes) AS notes,
               lender_overlays, supported_programs, is_active,
               created_at, updated_at, deleted_at
        FROM public.lenders
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
                EXECUTE 'GRANT SELECT ON readonly.lenders TO mbai_readonly';
            END IF;
        END
        $$;
        """
    )

    op.execute("DROP VIEW IF EXISTS readonly.lender_condition_codes")
    op.execute("DROP VIEW IF EXISTS readonly.condition_events")
    op.execute("DROP VIEW IF EXISTS readonly.conditions")
    op.execute("DROP VIEW IF EXISTS readonly.condition_rounds")

    op.drop_column("lenders", "condition_handling_notes")
    op.drop_column("lenders", "condition_upload_cutoff")
    op.drop_column("lenders", "mortgagee_clause")
    op.drop_column("lenders", "canonical_lender_key")

    op.drop_index("ix_lender_condition_codes_lender_status", table_name="lender_condition_codes")
    op.drop_index("uq_lender_condition_codes_lender_code", table_name="lender_condition_codes")
    op.drop_table("lender_condition_codes")

    op.drop_index("ix_condition_events_loan_file_id", table_name="condition_events")
    op.drop_index("ix_condition_events_condition_occurred", table_name="condition_events")
    op.drop_index("ix_condition_events_round_occurred", table_name="condition_events")
    op.drop_table("condition_events")

    op.drop_index("ix_conditions_file_fingerprint", table_name="conditions")
    op.drop_index("ix_conditions_file_lender_code", table_name="conditions")
    op.drop_index("ix_conditions_company_id", table_name="conditions")
    op.drop_index("ix_conditions_loan_file_id", table_name="conditions")
    op.drop_table("conditions")

    op.execute("DROP INDEX IF EXISTS uq_condition_rounds_file_number")
    op.drop_index("ix_condition_rounds_file_status", table_name="condition_rounds")
    op.drop_index("ix_condition_rounds_company_id", table_name="condition_rounds")
    op.drop_index("ix_condition_rounds_loan_file_id", table_name="condition_rounds")
    op.drop_table("condition_rounds")
