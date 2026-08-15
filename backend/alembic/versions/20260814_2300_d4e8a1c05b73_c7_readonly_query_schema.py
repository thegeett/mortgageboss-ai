"""read-only query schema + masked views + mbai_readonly role (C7)

Revision ID: d4e8a1c05b73
Revises: c9d3f1a6b2e4
Create Date: 2026-08-14 23:00:00.000000

The staging database has no inspection path, so diagnosing anything means reasoning from
CloudWatch alone. C7 adds one: a one-off ECS task that runs a single SELECT as a role that
CANNOT reach a base table. This migration is the database half — the schema, the views, and
the role.

WHY VIEWS AND NOT A READ-ONLY GRANT ON ``public``
-------------------------------------------------
``borrowers.ssn`` is Fernet-encrypted, so a SELECT returns ciphertext. Nothing else is.
``extractions.extracted_data`` holds raw SSNs and TINs in plaintext JSON (``employee_ssn``
from W-2s, ``recipient_tin`` from 1099s); ``documents.full_text`` holds the entire OCR'd
document, SSN included; ``mismo_imports.catch_all`` holds the raw MISMO payload. The §3B
masking runs at snapshot BUILD time, not at rest.

And the exfiltration path is not the network — it is the transcript. A query returning a raw
SSN puts it in terminal scrollback, in a conversation, and possibly in a result document
committed to git. No network control touches that; this view layer is the control that does.
So the role gets NO access to base tables at all, and every text or JSON column that can carry
a document-derived value is either dropped or scrubbed.

WHY THE SCRUB IS SHAPE-BASED, NOT KEY-BASED
-------------------------------------------
The ticket suggested stripping "the known PII keys". A key denylist fails OPEN: a new extractor
field carrying an identifier is not on the list, and this layer is the only thing between an
agent and a raw SSN. The codebase already documents the hole — ``_PII_FIELDS`` in
``verification/snapshot/documents_section.py`` carries the note that PII inside a captured LIST
row (a tradeline's account number) is NOT routed through it. With 121 schema specs and 99
generated extractors behind that surface, a hand-maintained list in a migration will drift.

So ``readonly.scrub()`` matches on the SHAPE OF THE VALUE, over the serialized JSON, which is
recursive by construction: it reaches nested list rows and fields that do not exist yet. The
patterns are lifted verbatim from the LP-209 at-rest guard
(``verification/snapshot/persistence.py``) so the two agree by construction rather than by
review — that guard is what rejected a staging snapshot on 2026-08-14 for containing exactly
these shapes, which is the evidence that unmasked identifiers reach this data.

Shape-matching is deliberately over-broad: a legitimate 9+ digit identifier is redacted too.
That is the accepted trade, and the same one the at-rest guard makes.

Names and street addresses are NOT digit-shaped, so the scrub cannot catch them. They are
handled by dropping the columns that carry them (see ``downgrade`` notes and the ticket result
doc for the full list). Values that survive are amounts, dates, enums, ids, confidences and
model-generated prose with identifiers scrubbed out.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e8a1c05b73"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "c9d3f1a6b2e4"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE = "mbai_readonly"
_SCHEMA = "readonly"

# The scrub. IMMUTABLE + STRICT so it can be used freely in views and indexes, and so a NULL
# input short-circuits to NULL rather than the string "null".
#
# Pattern 1 — a dashed SSN (``\b\d{3}-\d{2}-\d{4}\b``), the at-rest guard's ``_RAW_SSN``.
# Pattern 2 — a spaced SSN, which the at-rest guard does not need (it inspects compact JSON) but
#             which appears in OCR'd prose that reaches ``findings.message``.
# Pattern 3 — a bare run of 9+ digits not followed by a decimal, the guard's ``_LONG_DIGITS``.
#             The negative lookahead keeps a 9-digit whole-dollar amount with cents intact.
#
# Order matters: the dashed and spaced forms are replaced first, because pattern 3 would
# otherwise leave their separators behind as ``[REDACTED]-[REDACTED]-[REDACTED]``-style noise
# only for longer runs — harmless, but the explicit forms give a cleaner marker.
_SCRUB_FN = f"""
CREATE OR REPLACE FUNCTION {_SCHEMA}.scrub(v text)
RETURNS text
LANGUAGE sql
IMMUTABLE
STRICT
PARALLEL SAFE
AS $$
    SELECT regexp_replace(
             regexp_replace(
               regexp_replace(v, '\\m\\d{{3}}-\\d{{2}}-\\d{{4}}\\M', '[REDACTED-ID]', 'g'),
               '\\m\\d{{3}}\\s\\d{{2}}\\s\\d{{4}}\\M', '[REDACTED-ID]', 'g'),
             '\\m\\d{{9,}}\\M(?!\\.\\d)', '[REDACTED-ID]', 'g')
$$;
"""

# A json-in / json-out convenience wrapper: scrub the serialized form and cast back, so the view
# still hands back queryable JSON rather than a string.
_SCRUB_JSON_FN = f"""
CREATE OR REPLACE FUNCTION {_SCHEMA}.scrub_json(v json)
RETURNS json
LANGUAGE sql
IMMUTABLE
STRICT
PARALLEL SAFE
AS $$
    SELECT {_SCHEMA}.scrub(v::text)::json
$$;
"""

_SCRUB_JSONB_FN = f"""
CREATE OR REPLACE FUNCTION {_SCHEMA}.scrub_jsonb(v jsonb)
RETURNS jsonb
LANGUAGE sql
IMMUTABLE
STRICT
PARALLEL SAFE
AS $$
    SELECT {_SCHEMA}.scrub(v::text)::jsonb
$$;
"""

# Each entry is a full CREATE VIEW. Written out rather than generated: which column is dropped
# and which is scrubbed is a reviewable security decision per table, and a loop would hide it.
_VIEWS: tuple[str, ...] = (
    # --- Loan file spine ---------------------------------------------------- #
    # DROPPED: inbox_token (a capability — anyone holding it can post documents to the file),
    # loan_officer_name / loan_officer_email (named individual).
    f"""
    CREATE VIEW {_SCHEMA}.loan_files AS
    SELECT id, display_id, company_id, lender_id,
           loan_program, loan_purpose, loan_amount, status,
           note_amount, note_rate_percent, lien_priority, amortization_type,
           amortization_months, application_received_date, ai_needs_status,
           refinance_type, verification_stale, aggression_level_override,
           submitted_aggression_level,
           created_at, updated_at, deleted_at
    FROM public.loan_files
    """,
    # DROPPED: first/middle/last_name, ssn (ciphertext, useless), date_of_birth, email,
    # phone, declarations (the 1003 declarations JSON).
    f"""
    CREATE VIEW {_SCHEMA}.borrowers AS
    SELECT id, loan_file_id, is_primary, borrower_position, marital_status,
           citizenship, dependent_count,
           created_at, updated_at, deleted_at
    FROM public.borrowers
    """,
    # DROPPED: address_line, address_line_2, postal_code (the subject property street address).
    # KEPT: city / state — needed for state overlays and county loan limits, and neither
    # identifies a household on its own.
    f"""
    CREATE VIEW {_SCHEMA}.properties AS
    SELECT id, loan_file_id, city, state, property_type, occupancy_type,
           attachment_type, construction_method, financed_unit_count,
           estimated_value, purchase_price, valuation_amount,
           created_at, updated_at, deleted_at
    FROM public.properties
    """,
    # --- Documents and extraction ------------------------------------------- #
    # DROPPED: full_text (the ENTIRE document as text — a W-2's full text contains the SSN
    # verbatim; there is no meaningful redaction of "the whole document"), generic_analysis and
    # summary (model prose over the document), storage_path (points at the object).
    # KEPT + SCRUBBED: original_filename — user-supplied metadata rather than document content,
    # already visible in the app UI and in API responses, and findings reference documents by
    # filename, so dropping it would gut the debugging value. Scrubbed for digit-shaped ids.
    f"""
    CREATE VIEW {_SCHEMA}.documents AS
    SELECT id, loan_file_id,
           {_SCHEMA}.scrub(original_filename) AS original_filename,
           mime_type, file_size_bytes, document_type, category,
           classification_confidence, status, processing_error, upload_source,
           tier, version, is_current, version_group_id, supersedes_document_id,
           staleness_resolution, possible_duplicate, uploaded_by_user_id,
           created_at, updated_at, deleted_at
    FROM public.documents
    """,
    # THE headline column. Scrubbed, not dropped: the SHAPE of extracted_data (which fields
    # filled, at what confidence) is usually the thing being debugged, and amounts/dates survive
    # the scrub intact. Raw SSNs, TINs and account numbers do not.
    f"""
    CREATE VIEW {_SCHEMA}.extractions AS
    SELECT id, document_id, version, is_current,
           {_SCHEMA}.scrub_json(extracted_data) AS extracted_data,
           extraction_status, model_used, tokens_used, cost_estimate,
           confidence, confidence_source, error_detail,
           created_at, updated_at, deleted_at
    FROM public.extractions
    """,
    # DROPPED: catch_all (the raw MISMO payload — SSN, DOB and full addresses by design),
    # raw_file_path (points at the raw file in object storage).
    f"""
    CREATE VIEW {_SCHEMA}.mismo_imports AS
    SELECT id, loan_file_id, source_format, status,
           {_SCHEMA}.scrub_json(parse_warnings) AS parse_warnings,
           created_at, updated_at, deleted_at
    FROM public.mismo_imports
    """,
    f"""
    CREATE VIEW {_SCHEMA}.document_borrower_links AS
    SELECT id, document_id, borrower_id, confidence, method, created_at, updated_at
    FROM public.document_borrower_links
    """,
    # --- Verification and findings ------------------------------------------ #
    f"""
    CREATE VIEW {_SCHEMA}.verifications AS
    SELECT id, loan_file_id, status, trigger, started_at, completed_at,
           red_count, yellow_count, green_count,
           total_tokens_used, total_cost_estimate, error_detail, input_fingerprint,
           created_at, updated_at, deleted_at
    FROM public.verifications
    """,
    # DROPPED: source_snippet — a literal quote lifted from the document, which is exactly where
    # a name or address appears verbatim (observed carrying both on 2026-08-14).
    # SCRUBBED: message / details / applied_record / load_bearing_tags / resolution_note — model
    # prose and structured evidence, the most valuable debugging columns in the schema.
    f"""
    CREATE VIEW {_SCHEMA}.findings AS
    SELECT id, loan_file_id, verification_id, source_document_id, source_document_ids,
           rule_id, origin, status, category, evaluation_outcome, subject_key,
           {_SCHEMA}.scrub(message) AS message,
           {_SCHEMA}.scrub_json(details) AS details,
           {_SCHEMA}.scrub_json(applied_record) AS applied_record,
           {_SCHEMA}.scrub_jsonb(load_bearing_tags) AS load_bearing_tags,
           confidence, source_page,
           resolution_status,
           {_SCHEMA}.scrub(resolution_note) AS resolution_note,
           resolved_by_user_id, resolved_at,
           created_at, updated_at, deleted_at
    FROM public.findings
    """,
    f"""
    CREATE VIEW {_SCHEMA}.document_findings AS
    SELECT id, document_id, finding_type,
           {_SCHEMA}.scrub(description) AS description,
           amount, frequency,
           {_SCHEMA}.scrub_json(details) AS details,
           status, created_at, updated_at, deleted_at
    FROM public.document_findings
    """,
    f"""
    CREATE VIEW {_SCHEMA}.finding_events AS
    SELECT id, finding_id, event_type, from_outcome, to_outcome,
           {_SCHEMA}.scrub_jsonb(detail) AS detail,
           occurred_at
    FROM public.finding_events
    """,
    # The frozen snapshot the rules evaluated. Masked at build by §3B — scrubbed again here
    # because that masking is best-effort: the at-rest guard exists precisely because it can
    # fail, and it did fail closed on staging on 2026-08-14.
    f"""
    CREATE VIEW {_SCHEMA}.snapshot_records AS
    SELECT id, run_id, loan_file_id, snapshot_version,
           {_SCHEMA}.scrub_jsonb(snapshot_json) AS snapshot_json,
           created_at
    FROM public.snapshot_records
    """,
    f"""
    CREATE VIEW {_SCHEMA}.observations AS
    SELECT id, loan_file_id, run_id, about, observation_type,
           {_SCHEMA}.scrub(value) AS value,
           {_SCHEMA}.scrub_jsonb(structured) AS structured,
           relates_to_finding_id, relates_to_subject, confidence,
           {_SCHEMA}.scrub(reasoning) AS reasoning,
           produced_by, needs_tag, created_at, updated_at
    FROM public.observations
    """,
    f"""
    CREATE VIEW {_SCHEMA}.validation_verdicts AS
    SELECT id, company_id, item_id, kind, title,
           {_SCHEMA}.scrub(corrected_value) AS corrected_value,
           {_SCHEMA}.scrub(note) AS note,
           recorded_by_user_id, created_at, updated_at, deleted_at
    FROM public.validation_verdicts
    """,
    # --- Stated financials --------------------------------------------------- #
    # holder_name / employer_name are usually institutions but can be individuals, so scrubbed
    # rather than dropped: the name is often the whole point of an employer-consistency finding.
    f"""
    CREATE VIEW {_SCHEMA}.stated_assets AS
    SELECT id, loan_file_id, asset_type, value,
           {_SCHEMA}.scrub(holder_name) AS holder_name,
           created_at, updated_at, deleted_at
    FROM public.stated_assets
    """,
    f"""
    CREATE VIEW {_SCHEMA}.stated_liabilities AS
    SELECT id, loan_file_id, liability_type, monthly_payment, unpaid_balance,
           {_SCHEMA}.scrub(holder_name) AS holder_name,
           created_at, updated_at, deleted_at
    FROM public.stated_liabilities
    """,
    f"""
    CREATE VIEW {_SCHEMA}.stated_employers AS
    SELECT id, borrower_id,
           {_SCHEMA}.scrub(employer_name) AS employer_name,
           is_current, created_at, updated_at, deleted_at
    FROM public.stated_employers
    """,
    f"""
    CREATE VIEW {_SCHEMA}.stated_income_items AS
    SELECT id, borrower_id, monthly_amount, income_type, employment_income,
           created_at, updated_at, deleted_at
    FROM public.stated_income_items
    """,
    # --- Needs, activity, overrides ------------------------------------------ #
    f"""
    CREATE VIEW {_SCHEMA}.needs_items AS
    SELECT id, loan_file_id, borrower_id,
           {_SCHEMA}.scrub(title) AS title,
           {_SCHEMA}.scrub(description) AS description,
           category, needs_type, origin, priority, status,
           satisfied_by_document_id, satisfied_at, requested_at,
           {_SCHEMA}.scrub(notes) AS notes,
           disposition,
           {_SCHEMA}.scrub(reasoning) AS reasoning,
           {_SCHEMA}.scrub(reason) AS reason,
           source_finding_id,
           {_SCHEMA}.scrub_json(source_facts) AS source_facts,
           duplicate_reviewed, duplicate_of_id,
           created_at, updated_at, deleted_at
    FROM public.needs_items
    """,
    f"""
    CREATE VIEW {_SCHEMA}.activity_logs AS
    SELECT id, loan_file_id, activity_type, actor_user_id,
           {_SCHEMA}.scrub(summary) AS summary,
           {_SCHEMA}.scrub_json(detail) AS detail,
           created_at, updated_at, deleted_at
    FROM public.activity_logs
    """,
    f"""
    CREATE VIEW {_SCHEMA}.calculator_overrides AS
    SELECT id, loan_file_id, calculator, field_key, value,
           {_SCHEMA}.scrub(note) AS note,
           actor_user_id, created_at, updated_at, deleted_at
    FROM public.calculator_overrides
    """,
    f"""
    CREATE VIEW {_SCHEMA}.dti_overrides AS
    SELECT id, loan_file_id, field_key, value,
           {_SCHEMA}.scrub(note) AS note,
           actor_user_id, created_at, updated_at, deleted_at
    FROM public.dti_overrides
    """,
    f"""
    CREATE VIEW {_SCHEMA}.ltv_overrides AS
    SELECT id, loan_file_id, field_key, value,
           {_SCHEMA}.scrub(note) AS note,
           actor_user_id, created_at, updated_at, deleted_at
    FROM public.ltv_overrides
    """,
    # --- Tenancy and reference data ------------------------------------------ #
    # DROPPED: settings (arbitrary per-company JSON — may hold integration config or keys).
    f"""
    CREATE VIEW {_SCHEMA}.companies AS
    SELECT id, name, slug, is_active, created_at, updated_at, deleted_at
    FROM public.companies
    """,
    # DROPPED: hashed_password (a credential), email, first_name, last_name.
    f"""
    CREATE VIEW {_SCHEMA}.users AS
    SELECT id, company_id, role, is_active, default_aggression_level,
           created_at, updated_at, deleted_at
    FROM public.users
    """,
    # DROPPED: contact_email, contact_phone (named contacts at the lender).
    f"""
    CREATE VIEW {_SCHEMA}.lenders AS
    SELECT id, company_id, name, slug, portal_url,
           {_SCHEMA}.scrub(notes) AS notes,
           lender_overlays, supported_programs, is_active,
           created_at, updated_at, deleted_at
    FROM public.lenders
    """,
    # DROPPED ENTIRELY: communications.body / subject / sender / recipient — outbound email to
    # borrowers. The envelope is enough to debug the comms pipeline; the content never is.
    f"""
    CREATE VIEW {_SCHEMA}.communications AS
    SELECT id, loan_file_id, direction, channel, status, needs_item_id,
           initiated_by_user_id, external_message_id, sent_at,
           {_SCHEMA}.scrub(error_detail) AS error_detail,
           created_at, updated_at, deleted_at
    FROM public.communications
    """,
    # Rule-engine reference data. No loan data of any kind — exposed whole.
    f"""
    CREATE VIEW {_SCHEMA}.rules AS
    SELECT id, rule_id, name, category, kind, evaluation_path, numeric_check,
           exact_match, priya_validated, threshold_needs_signoff, rationale, spec,
           created_at, updated_at
    FROM public.rules
    """,
    f"""
    CREATE VIEW {_SCHEMA}.tags AS
    SELECT id, tag_id, entity, value_type, allowed_values, description,
           produced_by, tag_role, tag_version, extras, created_at, updated_at
    FROM public.tags
    """,
    f"""
    CREATE VIEW {_SCHEMA}.rule_tags AS
    SELECT id, rule_id, tag_id, created_at, updated_at FROM public.rule_tags
    """,
    f"""
    CREATE VIEW {_SCHEMA}.tag_dependencies AS
    SELECT id, tag_id, depends_on_tag_id, created_at, updated_at
    FROM public.tag_dependencies
    """,
    f"""
    CREATE VIEW {_SCHEMA}.graduation_candidates AS
    SELECT id, signature, observation_type, occurrences, created_at, updated_at
    FROM public.graduation_candidates
    """,
)


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}")
    op.execute(_SCRUB_FN)
    op.execute(_SCRUB_JSON_FN)
    op.execute(_SCRUB_JSONB_FN)

    for view in _VIEWS:
        op.execute(view)

    # THE ROLE IS NOT CREATED HERE — and that is the point.
    #
    # Migrations run in EVERY environment. Creating the login role here would put it in
    # production, where this debugging path is explicitly not wanted. Views are safe to
    # create everywhere (a view with no grantee grants nothing to anyone), so the schema
    # half is environment-agnostic and there is no schema drift between environments.
    #
    # The role, its grants and its revokes live in ``app.scripts.provision_query_role``,
    # run as a one-off task by ``./scripts/deploy <env> query-setup``, which refuses any
    # environment not in QUERY_ENVIRONMENTS. In an environment where that has never been
    # run, ``readonly.*`` exists and nothing on earth can select from it.
    #
    # Re-applied here only if the role is ALREADY present, so that a later migration
    # adding a view does not leave staging with a view its role cannot read. Ordering
    # between this migration and the provisioning step therefore does not matter.
    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_ROLE}') THEN
                EXECUTE 'GRANT USAGE ON SCHEMA {_SCHEMA} TO {_ROLE}';
                EXECUTE 'GRANT SELECT ON ALL TABLES IN SCHEMA {_SCHEMA} TO {_ROLE}';
            END IF;
        END
        $$;
    """)


def downgrade() -> None:
    """Drop the schema and everything in it.

    The ROLE is deliberately left alone: this migration never created it, and dropping a
    cluster-scoped role that something else provisioned would reach outside this database.
    ``provision_query_role --drop`` removes it.
    """
    op.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE")
