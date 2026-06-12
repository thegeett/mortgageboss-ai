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

/** A document's metadata (the list item). */
export interface DocumentResponse {
  id: string;
  loan_file_id: string;
  original_filename: string;
  mime_type: string;
  file_size_bytes: number;
  document_type: string | null;
  category: DocumentCategory | null;
  classification_confidence: number | null;
  status: DocumentStatus;
  upload_source: UploadSource;
  uploaded_by_user_id: string | null;
  created_at: string;
  updated_at: string;
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

/** The current extraction (pay stubs in V1); `extracted_data` is a flexible record. */
export interface ExtractionPublic {
  id: string;
  version: number;
  extracted_data: Record<string, unknown>;
  extraction_status: ExtractionStatus;
  model_used: string | null;
  created_at: string;
}

/** A document + its current extraction (the drawer detail). */
export interface DocumentDetailResponse extends DocumentResponse {
  current_extraction: ExtractionPublic | null;
}

/** The dev-only text-layer extraction (LP-40; non-production endpoint). */
export interface TextLayerExtraction {
  text: string;
  page_count: number;
  has_text: boolean;
  extraction_ok: boolean;
  error_reason: string | null;
}
