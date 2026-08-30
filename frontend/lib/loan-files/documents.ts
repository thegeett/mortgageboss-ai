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
  QualificationReason,
  SourceLocation,
  Transaction,
} from "@/lib/types/document";

/**
 * What a field with no value renders as.
 *
 * Named because it is COMPARED as well as produced: the reviewer asks "is there
 * anything here to check?" and a comparison against a repeated em-dash literal
 * would silently stop matching the day one of them changed.
 */
export const EMPTY_VALUE = "—";

/**
 * Whether the pipeline can still move a document out of this status on its own.
 *
 * Declared here rather than read off `StatusMeta.spin`: polling is BEHAVIOUR and
 * `spin` is decoration, and the two are free to diverge — dropping the spinner
 * from `classified` (which already carries its own label, not "Processing")
 * would silently halt polling mid-pipeline. Exhaustive over `DocumentStatus`, so
 * a status the backend grows is a compile error here rather than a document that
 * quietly stops refreshing.
 */
const IN_FLIGHT: Record<DocumentStatus, boolean> = {
  pending: true,
  classifying: true,
  classified: true,
  extracting: true,
  completed: false,
  needs_review: false,
  failed: false,
};

/** A document is settled once the pipeline can no longer change its status. */
export function isTerminalStatus(status: DocumentStatus): boolean {
  // A value not in the table — a status the backend grew before this build knew
  // of it — counts as IN FLIGHT. Polling one state longer than necessary costs a
  // request; stopping early strands the document at a non-terminal status until
  // someone reloads the page by hand.
  return (IN_FLIGHT as Record<string, boolean | undefined>)[status] === false;
}

/** True if ANY document is still being processed (→ keep polling). */
export function hasInProgressDocuments(documents: DocumentResponse[]): boolean {
  return documents.some((d) => !isTerminalStatus(d.status));
}

// --- Versioning + staleness display (LP-71) --------------------------------- //

export interface DocumentBadge {
  label: string;
  className: string;
}

/**
 * A calm staleness badge for a document, or null if fresh/not-applicable. An active
 * flag is warning-toned ("Expired" / "May be stale"); a resolved one reads as a quiet,
 * muted note ("Staleness waived/accepted"). Helpful, not alarming.
 */
export function stalenessBadge(doc: DocumentResponse): DocumentBadge | null {
  const { is_stale, kind, resolution } = doc.staleness;
  if (is_stale) {
    return {
      label: kind === "expired" ? "Expired" : "May be stale",
      className: "bg-warning/10 text-warning border-warning/20",
    };
  }
  if (resolution) {
    return {
      label: resolution === "waived" ? "Staleness waived" : "Staleness accepted",
      className: "bg-muted text-muted-foreground border-border",
    };
  }
  return null;
}

/** "v2 of 3" when the document is part of a multi-version group, else null. */
export function versionLabel(doc: DocumentResponse): string | null {
  return doc.version_count > 1 ? `v${doc.version} of ${doc.version_count}` : null;
}

/**
 * A subtle "Package-ready" indicator (LP-72) for a qualified document, else null. The
 * not-qualified reasons (stale, superseded) are already surfaced by their own cues, so
 * this only adds the positive, informational signal. Phase 6 assembles the package.
 */
export function packageReadyBadge(doc: DocumentResponse): DocumentBadge | null {
  if (doc.package_qualification.qualified) {
    return { label: "Package-ready", className: "bg-success/10 text-success border-success/20" };
  }
  return null;
}

/** A short note for a historical (superseded) document, or null if current. */
export function supersededNote(doc: DocumentResponse): string | null {
  return doc.is_current ? null : "Superseded by a newer version";
}

/**
 * Other CURRENT documents of the same type on the file — the gentle duplicate
 * surfacing ("you have other pay stubs"). Informational, derived client-side from the
 * list the page already has; never a blocking prompt.
 */
export function otherCurrentSameType(
  doc: DocumentResponse,
  all: DocumentResponse[],
): DocumentResponse[] {
  if (!doc.document_type || !doc.is_current) return [];
  return all.filter(
    (d) => d.id !== doc.id && d.is_current && d.document_type === doc.document_type,
  );
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

/** Preferred label + order for the known typed-core fields (pay stub + W-2). */
export const EXTRACTION_FIELD_LABELS: Record<string, string> = {
  // Pay stub (LP-39a)
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
  // W-2 (LP-39b)
  tax_year: "Tax year",
  employee_ssn: "Employee SSN",
  employer_ein: "Employer EIN",
  wages_tips_other_comp: "Wages (Box 1)",
  federal_income_tax_withheld: "Federal tax withheld (Box 2)",
  social_security_wages: "Social Security wages (Box 3)",
  social_security_tax_withheld: "Social Security tax (Box 4)",
  medicare_wages: "Medicare wages (Box 5)",
  medicare_tax_withheld: "Medicare tax (Box 6)",
  // Bank statement (LP-39c)
  account_holder_name: "Account holder",
  bank_name: "Bank",
  account_number_masked: "Account number",
  account_type: "Account type",
  statement_period_start: "Statement period start",
  statement_period_end: "Statement period end",
  beginning_balance: "Beginning balance",
  ending_balance: "Ending balance",
  total_deposits: "Total deposits",
  total_withdrawals: "Total withdrawals",
};

const EXTRACTION_FIELD_ORDER = Object.keys(EXTRACTION_FIELD_LABELS);

export interface ExtractionField {
  key: string;
  label: string;
  value: string;
  source: SourceLocation | null;
  /** The model's self-rating, or null when it gave none — which is the common case. */
  confidence: number | null;
}

/** Money-ish keys we render as currency (pay stub + W-2 boxes + bank balances). */
const MONEY_KEYS = new Set([
  // Pay stub
  "gross_pay",
  "net_pay",
  "ytd_gross",
  "rate",
  // W-2 boxes
  "wages_tips_other_comp",
  "federal_income_tax_withheld",
  "social_security_wages",
  "social_security_tax_withheld",
  "medicare_wages",
  "medicare_tax_withheld",
  // Bank statement balances/totals
  "beginning_balance",
  "ending_balance",
  "total_deposits",
  "total_withdrawals",
]);

/** A label for a typed-core key — the known label, or a humanized fallback. */
function labelFor(key: string): string {
  return (
    EXTRACTION_FIELD_LABELS[key] ?? key.charAt(0).toUpperCase() + key.slice(1).replace(/_/g, " ")
  );
}

function displayValue(key: string, raw: unknown): string {
  if (raw === null || raw === undefined || raw === "") return EMPTY_VALUE;
  if (MONEY_KEYS.has(key)) {
    const amount = Number(raw);
    if (!Number.isNaN(amount)) {
      return amount.toLocaleString("en-US", { style: "currency", currency: "USD" });
    }
  }
  return String(raw);
}

/**
 * Pull `{value, source, confidence}` out of a typed-core entry, tolerating odd shapes.
 *
 * `confidence` (LP-201) is nullable and OFTEN ABSENT — three-quarters of stored
 * fields carry no key at all. A missing one stays `null` rather than defaulting to
 * anything: a fabricated 1.0 would read as the model being certain about a value it
 * never rated.
 */
function readTypedField(entry: unknown): {
  value: unknown;
  source: SourceLocation | null;
  confidence: number | null;
} {
  if (entry && typeof entry === "object" && "value" in entry) {
    const obj = entry as { value?: unknown; source?: unknown; confidence?: unknown };
    const source =
      obj.source && typeof obj.source === "object" ? (obj.source as SourceLocation) : null;
    const confidence = typeof obj.confidence === "number" ? obj.confidence : null;
    return { value: obj.value ?? null, source, confidence };
  }
  return { value: entry ?? null, source: null, confidence: null }; // tolerant: a bare value
}

/**
 * The typed core as ordered, labelled rows (value + source). Works for any
 * document type — known fields (pay stub / W-2) appear first in a sensible order,
 * then any others. Sensitive fields (e.g. the W-2 SSN) are **masked** in display;
 * absent/null values render as `EMPTY_VALUE`.
 */
function maskedDisplay(key: string, value: unknown): string {
  const raw = value == null ? null : String(value);
  // An SSN or ITIN gets the ***-**-#### format; other ids (account number) get last-4.
  return /ssn|itin/.test(key) ? maskSsn(raw) : maskLast4(raw);
}

export function extractionFields(
  data: Record<string, unknown>,
  /**
   * Field keys the backend says are identifiers (LP-UI-032). Masked ON TOP of
   * `MASKED_FIELD_KEYS`, never instead of it: a backend that stops answering must
   * not be able to un-mask something that is masked today.
   */
  sensitiveKeys?: ReadonlySet<string>,
): ExtractionField[] {
  const fields: ExtractionField[] = [];
  for (const key of Object.keys(data)) {
    // The catch-all and the transactions list are rendered separately.
    if (key === "additional_sections" || key === "transactions") continue;
    const { value, source, confidence } = readTypedField(data[key]);
    const display =
      MASKED_FIELD_KEYS.has(key) || sensitiveKeys?.has(key)
        ? maskedDisplay(key, value)
        : displayValue(key, value);
    fields.push({ key, label: labelFor(key), value: display, source, confidence });
  }
  // Known typed-core fields first (in order), then any others.
  const orderIndex = (k: string) => {
    const i = EXTRACTION_FIELD_ORDER.indexOf(k);
    return i === -1 ? Number.MAX_SAFE_INTEGER : i;
  };
  return fields.sort((a, b) => orderIndex(a.key) - orderIndex(b.key));
}

/** The bank statement transactions (`transactions`), or [] if absent/odd. */
export function extractionTransactions(data: Record<string, unknown>): Transaction[] {
  const raw = data.transactions;
  if (!Array.isArray(raw)) return [];
  return raw.filter((t): t is Transaction => Boolean(t) && typeof t === "object");
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

/** Sensitive typed-core keys masked in display (W-2 SSN LP-39b; bank acct LP-39c). */
export const MASKED_FIELD_KEYS = new Set(["employee_ssn", "account_number_masked"]);

/**
 * A catch-all field naming an identifier (LP-UI-032 review).
 *
 * THE TYPED-CORE MASK CANNOT REACH THIS PATH. `extractionFields` masks by field KEY,
 * against the backend's identity list plus `MASKED_FIELD_KEYS`. The catch-all is keyed
 * by a free-text LABEL the model wrote, so there is no key to look up — and the
 * catch-all is by definition the fields nobody classified, which is exactly where an
 * unclassified identifier ends up. Measured on the current corpus: a nine-digit tax id
 * under "b Employer's social security number" renders in the clear today, alongside
 * eleven other identifier-labelled catch-all values.
 *
 * BOTH the label and the value have to be consulted, and neither alone works:
 *
 * - Label alone masks money. "Social Security - YTD" and "OASDI (Social Security) -
 *   Current" are withholding AMOUNTS on a real pay stub in this corpus. Masking a
 *   processor's YTD figure because its label says "social security" is a worse bug
 *   than the one being fixed.
 * - Value alone misses short identifiers. An eight-digit brokerage account number is
 *   not distinguishable from any other number without its label.
 *
 * So: money and rates are excluded first, then a bare 9+ digit run or an SSN shape is
 * an identifier whatever the label claims, and below that the label has to say so.
 */
const IDENTIFIER_LABEL =
  /\b(ssns?|social security (number|no)|tax(payer)? id|tins?|eins?|account (number|no)|routing|passport|licen[sc]e number)\b/i;

export function catchAllIsSensitive(label: string, value: string): boolean {
  // A status word ("Match", "No alert") carries no identifier to hide, and masking it
  // to bullets destroys the only thing the row said.
  if (!/\d/.test(value)) return false;
  // Money and rates. A decimal fraction or a currency/percent mark says this is an
  // amount — no identifier is written with cents.
  if (/[$%]|\d\.\d/.test(value)) return false;
  if (/\d{3}[- ]\d{2}[- ]\d{4}|\b\d{9,}\b/.test(value)) return true;
  return IDENTIFIER_LABEL.test(label);
}

/** The display form for a catch-all field — masked when it names an identifier. */
export function catchAllDisplay(label: string, value: string): string {
  if (!catchAllIsSensitive(label, value)) return value;
  // Which mask, and the VALUE decides first. A 9-digit or dashed SSN shape gets the
  // SSN form whatever the label says: keying only off the label gave "••••6789" for a
  // literal `123-45-6789` sitting under a label that did not name it.
  const ssnShaped = /^\D*\d{3}[- ]\d{2}[- ]\d{4}\D*$/.test(value) || /^\D*\d{9}\D*$/.test(value);
  return ssnShaped || /\bssns?\b|social security (number|no)|tax(payer)? id|\btins?\b/i.test(label)
    ? maskSsn(value)
    : maskLast4(value);
}

// --- Document type override (LP-44) ----------------------------------------- //

/** Types that re-extract on override (the rest relabel classified-only). */
export const EXTRACTABLE_TYPES = new Set(["pay_stub", "w2", "bank_statement"]);

/** Selectable types for the override control (value + human label). */
export const OVERRIDE_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: "pay_stub", label: "Pay stub" },
  { value: "w2", label: "W-2" },
  { value: "bank_statement", label: "Bank statement" },
  { value: "tax_return_1040", label: "Tax return (1040)" },
  { value: "drivers_license", label: "Driver’s license" },
  { value: "credit_report", label: "Credit report" },
  { value: "gift_letter", label: "Gift letter" },
  { value: "other", label: "Other" },
];

/** True if overriding to this type will re-run extraction (vs relabel-only). */
export function typeReExtracts(documentType: string | null | undefined): boolean {
  return documentType != null && EXTRACTABLE_TYPES.has(documentType);
}

/**
 * Mask an SSN to last-4 for display (LP-39b) — consistent with the borrower
 * `masked_ssn` discipline. The raw value is never shown in full and never logged.
 */
export function maskSsn(ssn: string | null | undefined): string {
  if (!ssn) return EMPTY_VALUE;
  const digits = ssn.replace(/\D/g, "");
  if (digits.length < 4) return "•••";
  return `•••-••-${digits.slice(-4)}`;
}

/**
 * Mask any identifier to its last 4 chars for display (LP-39c, generalizes the SSN
 * mask) — e.g. a bank account number. Already-masked input (e.g. "****1234") shows
 * its last 4. Never shown in full.
 */
export function maskLast4(value: string | null | undefined): string {
  if (!value) return EMPTY_VALUE;
  const trimmed = value.trim();
  const tail = trimmed.replace(/[^A-Za-z0-9]/g, "").slice(-4);
  return tail ? `••••${tail}` : "••••";
}

// --- Coverage, freshness, duplicates (LP-UI-019) ---------------------------- //

/**
 * Why a document is not package-qualified, in the processor's words.
 *
 * The reasons are the BACKEND's (`app/documents/staleness.py`), which checks
 * them in priority order and reports the first failure. They are not restated
 * here as a second opinion — this map only gives each one a label.
 */
export const QUALIFICATION_REASON_LABEL: Record<QualificationReason, string> = {
  superseded: "Superseded",
  stale: "Out of date",
  untyped: "Not recognised",
  not_extracted: "Not extracted yet",
};

export interface DocumentCoverage {
  /** Current, fresh, typed and extracted — the backend's four criteria. */
  qualified: number;
  total: number;
  /** The rest, grouped by the FIRST criterion each one failed. */
  shortfalls: { reason: QualificationReason; label: string; count: number }[];
  /** Unresolved staleness — a processor can act on each of these. */
  stale: DocumentResponse[];
  /** Documents sharing a type with another current document on the file. */
  duplicated: { type: string; documents: DocumentResponse[] }[];
}

/**
 * What the Documents context rail reports, derived from the list the page has
 * already fetched. Nothing here is a second request — the rail exists to keep
 * these answerable in one action, not to add a round trip per question.
 *
 * CURRENT documents only. A superseded version is reachable through the version
 * history and counting it would make "8 of 12 qualified" describe a list of
 * twelve the processor cannot see.
 */
/**
 * Documents still moving through the pipeline THAT WILL LAND IN THE TABLE.
 *
 * One definition, because there were two. `DocumentList` shows
 * `is_current && isTerminalStatus`, and `documentCoverage` counts `is_current` —
 * but the processing strip and the rail's "Processing" metric each filtered on
 * `!isTerminalStatus` alone. A SUPERSEDED document mid-flight was therefore
 * counted as arriving and shown in the strip, and could never appear in the
 * table below it when it settled, because it is not current.
 *
 * The strip is a promise that these rows are on their way to the list. A row
 * that is not is a count a processor cannot reconcile with what they can see.
 */
export function inFlightDocuments(documents: DocumentResponse[]): DocumentResponse[] {
  return documents.filter((doc) => doc.is_current && !isTerminalStatus(doc.status));
}

/** The documents the table can show — current, whatever their status. */
export function currentDocuments(documents: DocumentResponse[]): DocumentResponse[] {
  return documents.filter((doc) => doc.is_current);
}

export function documentCoverage(documents: DocumentResponse[]): DocumentCoverage {
  const current = documents.filter((doc) => doc.is_current);

  const counts = new Map<QualificationReason, number>();
  let qualified = 0;
  for (const doc of current) {
    if (doc.package_qualification.qualified) {
      qualified += 1;
      continue;
    }
    const reason = doc.package_qualification.reason;
    if (reason) counts.set(reason, (counts.get(reason) ?? 0) + 1);
  }

  const shortfalls = (Object.keys(QUALIFICATION_REASON_LABEL) as QualificationReason[])
    .filter((reason) => (counts.get(reason) ?? 0) > 0)
    .map((reason) => ({
      reason,
      label: QUALIFICATION_REASON_LABEL[reason],
      count: counts.get(reason) ?? 0,
    }));

  // A staleness a processor has already answered (replaced, waived, accepted) is
  // not a thing to chase — LP-71 records the resolution for exactly this reason.
  const stale = current.filter((doc) => doc.staleness?.is_stale && !doc.staleness.resolution);

  const byType = new Map<string, DocumentResponse[]>();
  for (const doc of current) {
    if (!doc.document_type) continue;
    byType.set(doc.document_type, [...(byType.get(doc.document_type) ?? []), doc]);
  }
  const duplicated = [...byType.entries()]
    .filter(([, docs]) => docs.length > 1)
    .map(([type, docs]) => ({ type, documents: docs }));

  return { qualified, total: current.length, shortfalls, stale, duplicated };
}
