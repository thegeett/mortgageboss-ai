/**
 * Document types (LP-43) — mirror the backend LP-36 schemas.
 *
 * `storage_path` is intentionally absent (the API never exposes it); the bytes
 * are fetched only via the auth'd `/download` endpoint.
 */

/** Processing lifecycle (LP-15/LP-42). The pipeline drives a document through these. */
export type DocumentStatus =
  | "pending"
  | "classifying"
  | "classified"
  | "extracting"
  | "completed"
  | "failed"
  | "needs_review";

/** The eight organizational categories (set by the classifier; null while pending). */
export type DocumentCategory =
  | "assets"
  | "borrower_info"
  | "credit"
  | "disclosures"
  | "income_employment"
  | "property"
  | "misc"
  | "custom";

export type UploadSource = "user_upload" | "borrower_inbox" | "mismo_import";

export type ExtractionStatus = "succeeded" | "failed" | "partial";

/** The level-of-investment tier a document was handled as (LP-58). */
export type DocumentTier = "tier_1" | "tier_2" | "tier_3";

/** The processor's resolution of a flagged-stale document (LP-71). */
export type StalenessResolution = "waived" | "accepted";

/** Why a document is (or would be) stale: aged past its window, or expired. */
export type StalenessKind = "aged" | "expired";

/** A document's freshness assessment (LP-71) — deterministic, date-driven. */
export interface StalenessInfo {
  is_stale: boolean;
  kind: StalenessKind | null;
  reason: string | null;
  resolution: StalenessResolution | null;
  as_of_date: string | null;
}

/** Whether a document is fit for the lender package (current + fresh) — groundwork (LP-71). */
export interface PackageFitness {
  fit: boolean;
  /** Why not fit: "superseded" | "stale" | null. */
  reason: string | null;
}

/** Why a document isn't package-qualified (LP-72). */
export type QualificationReason = "superseded" | "stale" | "untyped" | "not_extracted";

/** Package qualification (LP-72): current + fresh + typed + extracted → qualified. */
export interface PackageQualification {
  qualified: boolean;
  reason: QualificationReason | null;
}

/** A document's metadata (the list item). */
export interface DocumentResponse {
  id: string;
  loan_file_id: string;
  original_filename: string;
  mime_type: string;
  file_size_bytes: number;
  document_type: string | null;
  category: DocumentCategory | null;
  /** The tier the document was handled as (LP-58). */
  tier: DocumentTier | null;
  /** A short human-readable gist for Tier 2 (recognized) documents (LP-65). */
  summary: string | null;
  classification_confidence: number | null;
  status: DocumentStatus;
  upload_source: UploadSource;
  uploaded_by_user_id: string | null;
  created_at: string;
  updated_at: string;
  // --- Versioning (Model C, LP-71) ---
  version: number;
  is_current: boolean;
  version_group_id: string | null;
  supersedes_document_id: string | null;
  /** How many versions are in this document's group (1 = standalone). */
  version_count: number;
  /** The email-ingest "possible duplicate" flag (surfaced gently). */
  possible_duplicate: boolean;
  // --- Staleness + package fitness (LP-71) ---
  staleness: StalenessInfo;
  package_fit: PackageFitness;
  // --- LP-72: a derived display name + the package-qualification flag ---
  /** A consistent {Type}_{Identifier}_{Date} display name (the stored file is untouched). */
  standard_name: string;
  package_qualification: PackageQualification;
}

/**
 * Extraction shape (LP-39a). `extracted_data` is the typed core (each field a
 * `{value, source}`) plus a grouped catch-all (`additional_sections`) — read
 * leniently as a flexible record by the display helpers.
 */

/** Where a value was read from on the document (page + verbatim snippet). */
export interface SourceLocation {
  page: number | null;
  snippet: string | null;
}

/** One captured catch-all field (value kept as a string). */
export interface CatchAllField {
  label: string;
  value: string | null;
  source: SourceLocation | null;
}

/** A named group of catch-all fields (e.g. "Deductions"). */
export interface CatchAllSection {
  section: string;
  fields: CatchAllField[];
}

/** One bank-statement transaction row (LP-39c; values are JSON strings). */
export interface Transaction {
  date: string | null;
  description: string | null;
  amount: string | null;
  transaction_type: string | null;
  running_balance: string | null;
  source: SourceLocation | null;
}

/** The current extraction (pay stubs in V1); `extracted_data` is a flexible record. */
export interface ExtractionPublic {
  id: string;
  version: number;
  extracted_data: Record<string, unknown>;
  extraction_status: ExtractionStatus;
  model_used: string | null;
  created_at: string;
}

/** Tier 3 generic-analyzer output (LP-66) — the flexible findings for a long-tail doc. */
export interface AnalyzedParty {
  name: string | null;
  role: string | null;
}
export interface AnalyzedDate {
  date: string | null;
  description: string | null;
}
export interface AnalyzedAmount {
  value: string | number | null;
  context: string | null;
}
export interface AnalyzedFinding {
  finding_type: string | null;
  description: string | null;
  amount: string | number | null;
  frequency: string | null;
}
export interface GenericAnalysis {
  document_type_guess?: string | null;
  key_parties?: AnalyzedParty[];
  key_dates?: AnalyzedDate[];
  key_amounts?: AnalyzedAmount[];
  key_findings?: AnalyzedFinding[];
  summary?: string | null;
}

/** A document + its current extraction + (Tier 3) generic analysis (the drawer detail). */
export interface DocumentDetailResponse extends DocumentResponse {
  current_extraction: ExtractionPublic | null;
  /** Tier 3 only — the generic analyzer's parties/dates/amounts/findings (LP-66). */
  generic_analysis: GenericAnalysis | null;
}

/** The dev-only text-layer extraction (LP-40; non-production endpoint). */
export interface TextLayerExtraction {
  text: string;
  page_count: number;
  has_text: boolean;
  extraction_ok: boolean;
  error_reason: string | null;
}
