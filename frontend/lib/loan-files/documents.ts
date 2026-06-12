/**
 * Document presentation + logic helpers (LP-43).
 *
 * One place for: the status → label/treatment map (extends the LP-31 status
 * idea to documents), the category groupings, the terminal-vs-in-progress rule
 * that drives live polling, client-side upload validation, and the extraction
 * field display. Colours use the LP-5 semantic tokens — never ad-hoc.
 */
import type {
  CatchAllSection,
  DocumentCategory,
  DocumentResponse,
  DocumentStatus,
  SourceLocation,
} from "@/lib/types/document";

// --- Status treatment ------------------------------------------------------- //

export interface DocumentStatusMeta {
  label: string;
  /** Badge classes from the design tokens. */
  className: string;
  /** True while the pipeline is still working (drives the spinner + polling). */
  inProgress: boolean;
}

export const DOCUMENT_STATUS_META: Record<DocumentStatus, DocumentStatusMeta> = {
  pending: {
    label: "Processing",
    className: "bg-info/10 text-info border-info/20",
    inProgress: true,
  },
  classifying: {
    label: "Processing",
    className: "bg-info/10 text-info border-info/20",
    inProgress: true,
  },
  classified: {
    label: "Classified",
    className: "bg-info/10 text-info border-info/20",
    inProgress: true,
  },
  extracting: {
    label: "Processing",
    className: "bg-info/10 text-info border-info/20",
    inProgress: true,
  },
  completed: {
    label: "Completed",
    className: "bg-success/10 text-success border-success/20",
    inProgress: false,
  },
  needs_review: {
    label: "Needs review",
    className: "bg-warning/10 text-warning border-warning/20",
    inProgress: false,
  },
  failed: {
    label: "Failed",
    className: "bg-destructive/10 text-destructive border-destructive/20",
    inProgress: false,
  },
};

/** A document is settled once the pipeline can no longer change its status. */
export function isTerminalStatus(status: DocumentStatus): boolean {
  return !DOCUMENT_STATUS_META[status].inProgress;
}

/** True if ANY document is still being processed (→ keep polling). */
export function hasInProgressDocuments(documents: DocumentResponse[]): boolean {
  return documents.some((d) => !isTerminalStatus(d.status));
}

// --- Categories + grouping -------------------------------------------------- //

/** Human labels + display order for the eight categories. */
export const CATEGORY_META: Record<DocumentCategory, string> = {
  income_employment: "Income & employment",
  assets: "Assets",
  credit: "Credit",
  property: "Property",
  borrower_info: "Borrower info",
  disclosures: "Disclosures",
  misc: "Miscellaneous",
  custom: "Custom",
};

const CATEGORY_ORDER: DocumentCategory[] = [
  "income_employment",
  "assets",
  "credit",
  "property",
  "borrower_info",
  "disclosures",
  "misc",
  "custom",
];

/** The bucket for documents the classifier hasn't categorized yet (e.g. pending). */
export const UNCATEGORIZED_LABEL = "Processing / uncategorized";

export interface DocumentGroup {
  key: string;
  label: string;
  documents: DocumentResponse[];
}

/**
 * Group documents by category for display: the eight categories in a sensible
 * order (only those that have documents), then an "Processing / uncategorized"
 * group for documents without a category yet (e.g. still pending). Within a
 * group, newest first.
 */
export function groupDocumentsByCategory(documents: DocumentResponse[]): DocumentGroup[] {
  const byCategory = new Map<DocumentCategory, DocumentResponse[]>();
  const uncategorized: DocumentResponse[] = [];

  for (const doc of documents) {
    if (doc.category && doc.category in CATEGORY_META) {
      const list = byCategory.get(doc.category) ?? [];
      list.push(doc);
      byCategory.set(doc.category, list);
    } else {
      uncategorized.push(doc);
    }
  }

  const newestFirst = (a: DocumentResponse, b: DocumentResponse) =>
    b.created_at.localeCompare(a.created_at);

  const groups: DocumentGroup[] = [];
  for (const category of CATEGORY_ORDER) {
    const docs = byCategory.get(category);
    if (docs && docs.length > 0) {
      groups.push({
        key: category,
        label: CATEGORY_META[category],
        documents: docs.sort(newestFirst),
      });
    }
  }
  if (uncategorized.length > 0) {
    groups.push({
      key: "uncategorized",
      label: UNCATEGORIZED_LABEL,
      documents: uncategorized.sort(newestFirst),
    });
  }
  return groups;
}

// --- Client-side upload validation (UX; the server is authoritative, LP-36) - //

export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024; // 50 MB
export const ACCEPTED_MIME_TYPES = ["application/pdf", "image/jpeg", "image/png"] as const;

export interface FileValidationError {
  file: string;
  reason: string;
}

/** Validate a file's type + size for fast feedback; returns an error or null. */
export function validateUploadFile(file: File): FileValidationError | null {
  const type = file.type.toLowerCase();
  const isAccepted =
    (ACCEPTED_MIME_TYPES as readonly string[]).includes(type) || type === "image/jpg";
  if (!isAccepted) {
    return { file: file.name, reason: "Unsupported type — use PDF, JPG, or PNG" };
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return { file: file.name, reason: "Too large — the limit is 50 MB" };
  }
  return null;
}

// --- Misc display ----------------------------------------------------------- //

/** Bytes → a short human size, e.g. 1536 → "1.5 KB". */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}`;
}

/** A confidence in [0,1] → "92%" (or null when absent). */
export function formatConfidence(value: number | null): string | null {
  if (value === null || Number.isNaN(value)) return null;
  return `${Math.round(value * 100)}%`;
}

// --- Extraction field display (LP-39a shape) -------------------------------- //
// The stored `extracted_data` is the typed core (each field a {value, source})
// + a grouped catch-all (`additional_sections`). We read it leniently.

/** Preferred label + order for the known pay-stub typed-core fields. */
export const EXTRACTION_FIELD_LABELS: Record<string, string> = {
  employer_name: "Employer",
  employee_name: "Employee",
  pay_period_start: "Pay period start",
  pay_period_end: "Pay period end",
  pay_date: "Pay date",
  gross_pay: "Gross pay",
  net_pay: "Net pay",
  ytd_gross: "YTD gross",
  pay_frequency: "Pay frequency",
  hours: "Hours",
  rate: "Rate",
};

const EXTRACTION_FIELD_ORDER = Object.keys(EXTRACTION_FIELD_LABELS);

export interface ExtractionField {
  key: string;
  label: string;
  value: string;
  source: SourceLocation | null;
}

/** Money-ish keys we render as currency. */
const MONEY_KEYS = new Set(["gross_pay", "net_pay", "ytd_gross", "rate"]);

function displayValue(key: string, raw: unknown): string {
  if (raw === null || raw === undefined || raw === "") return "—";
  if (MONEY_KEYS.has(key)) {
    const amount = Number(raw);
    if (!Number.isNaN(amount)) {
      return amount.toLocaleString("en-US", { style: "currency", currency: "USD" });
    }
  }
  return String(raw);
}

/** Pull `{value, source}` out of a typed-core entry, tolerating odd shapes. */
function readTypedField(entry: unknown): { value: unknown; source: SourceLocation | null } {
  if (entry && typeof entry === "object" && "value" in entry) {
    const obj = entry as { value?: unknown; source?: unknown };
    const source =
      obj.source && typeof obj.source === "object" ? (obj.source as SourceLocation) : null;
    return { value: obj.value ?? null, source };
  }
  return { value: entry ?? null, source: null }; // tolerant: a bare value
}

/**
 * The typed core as ordered, labelled rows (value + source) — the known pay-stub
 * fields in a sensible order. Absent/null values render as "—".
 */
export function extractionFields(data: Record<string, unknown>): ExtractionField[] {
  const fields: ExtractionField[] = [];
  for (const key of EXTRACTION_FIELD_ORDER) {
    if (key in data) {
      const { value, source } = readTypedField(data[key]);
      fields.push({
        key,
        label: EXTRACTION_FIELD_LABELS[key] ?? key,
        value: displayValue(key, value),
        source,
      });
    }
  }
  return fields;
}

/** The grouped catch-all (`additional_sections`), or [] if absent/odd. */
export function catchAllSections(data: Record<string, unknown>): CatchAllSection[] {
  const raw = data.additional_sections;
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (s): s is CatchAllSection =>
      Boolean(s) && typeof s === "object" && Array.isArray((s as CatchAllSection).fields),
  );
}

/** A compact "p.{page}: '{snippet}'" label for a source affordance, or null. */
export function formatSource(source: SourceLocation | null): string | null {
  if (!source) return null;
  const parts: string[] = [];
  if (source.page != null) parts.push(`p.${source.page}`);
  if (source.snippet) parts.push(`“${source.snippet}”`);
  return parts.length > 0 ? parts.join(": ") : null;
}
