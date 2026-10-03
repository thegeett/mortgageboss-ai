"""LP-956 — the readonly views catch up with the conditions work (trial item 12).

During the staging trial, "has this file been read? is its plan confirmed? which items are linked?" could
not be answered with `./scripts/deploy staging query`: the reading, plan and item columns had been
excluded "only to avoid rebuilding the view". This rebuilds two views and adds one:

- `readonly.conditions` gains `reading_status`, `reading_source`, `reading_confidence` (closed vocabularies
  and a number) and `next_step` (a category). `reading` itself (the model's summary of the lender's text)
  stays out, and so does `plan_reason`: LP-920's exclusion note called it "built by code and names no
  borrower", but the same commit added `plan_reason = f"Found: {found.document_name …}"`
  (`condition_plan.py:605`), so it can hold a DOCUMENT'S FILE NAME. `documents.document_name` is in
  `NEVER_EXPOSED` because the scrub matches identifier shapes and a person's name is not digit-shaped;
  carrying it here under another name would walk around that guard (LP-956 review).
- `readonly.condition_rounds` gains `plan_ready_at`, `plan_confirmed_at`, `plan_confirmed_by_user_id`, and
  the reading's STATE and counts from `reading_run` (state, conditions read, AI used, fell back, model).
  `reading_run` itself stays out: its `error` is the one free-text field.
- `readonly.condition_items` is new: ids, key, who acts, step, status, origin, documents and checks (codes),
  the linked document and page, what it waits on, its draft and its part. NOT `name`, `acceptable` or
  `specifics`, which restate the lender's wording, amounts and account endings.

RAW SQL (ADR-037). Each view is DROP then CREATE (a column list cannot change in place), and each is
RE-GRANTED IN `upgrade()` (LP-842: a dropped view drops its grants). The rollback copies are inline below
`def downgrade(`, never hoisted (the drift guard reads only the upgrade body).

Revision ID: 5d8b2f6a3c91
Revises: 9a3e5c7b1f20
Create Date: 2026-10-02 19:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "5d8b2f6a3c91"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "9a3e5c7b1f20"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
               reading_status, reading_source, reading_confidence,
               next_step,
               created_at, updated_at, deleted_at
        FROM public.conditions
        """
    )
    op.execute("DROP VIEW IF EXISTS readonly.condition_rounds")
    op.execute(
        """
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
               (comparison IS NOT NULL) AS has_comparison,
               plan_ready_at, plan_confirmed_at, plan_confirmed_by_user_id,
               (reading_run ->> 'state') AS reading_state,
               (reading_run ->> 'read') AS reading_read,
               (reading_run ->> 'used_ai') AS reading_used_ai,
               (reading_run ->> 'fell_back') AS reading_fell_back,
               (reading_run ->> 'model') AS reading_model,
               created_by_user_id, created_at, updated_at, deleted_at
        FROM public.condition_rounds
        """
    )
    op.execute(
        """
        CREATE VIEW readonly.condition_items AS
        SELECT id, company_id, loan_file_id, condition_id, round_id,
               key, performer, performers, option, status, origin,
               documents, checks,
               need_id, document_id, document_page, waits_on_condition_id,
               due_date, sequence, draft_id, part_of_item_id,
               created_at, updated_at, deleted_at
        FROM public.condition_items
        """
    )
    op.execute(
        """
        DO $$
        DECLARE v text;
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
                FOREACH v IN ARRAY ARRAY['conditions', 'condition_rounds', 'condition_items']
                LOOP
                    EXECUTE format('GRANT SELECT ON readonly.%I TO mbai_readonly', v);
                END LOOP;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS readonly.condition_items")
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
    op.execute("DROP VIEW IF EXISTS readonly.condition_rounds")
    op.execute(
        """
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
               (comparison IS NOT NULL) AS has_comparison,
               created_by_user_id, created_at, updated_at, deleted_at
        FROM public.condition_rounds
        """
    )
    op.execute(
        """
        DO $$
        DECLARE v text;
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
                FOREACH v IN ARRAY ARRAY['conditions', 'condition_rounds']
                LOOP
                    EXECUTE format('GRANT SELECT ON readonly.%I TO mbai_readonly', v);
                END LOOP;
            END IF;
        END
        $$;
        """
    )
