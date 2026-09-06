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

/**
 * What shape an extracted field's value has (LP-702).
 *
 * The typed core is NOT flat. 67 of the document types in
 * `app/ai/prompts/extraction/` declare at least one list-valued key — a pay
 * stub's `earnings_lines`, an HOA statement's `payment_ledger`, a credit
 * report's `tradelines` — and the display layer used to stringify them, which
 * is how `[object Object],[object Object]` reached a processor's screen.
 *
 * The kind is DERIVED FROM THE VALUE, never from a list of key names. Two
 * hardcoded key names is how that bug existed; a third would be the same bug
 * with one more name in it.
 */
export type ExtractionFieldKind = "scalar" | "list" | "record";

/** What a processor supplied for one field (LP-703), as the screen needs it. */
export interface FieldCorrection {
  /** The value they typed. Null for a removal, which supplies nothing. */
  value: string | null;
  /** They said the field is not on the document. */
  removed: boolean;
}

export interface ExtractionField {
  key: string;
  label: string;
  /**
   * One line for the field. A scalar's value; for a list or a record, how much
   * is in it ("14 rows") — the detail is in `rows`.
   */
  value: string;
  kind: ExtractionFieldKind;
  /** Column labels for a `list`/`record`. Empty for a scalar, and for a list of plain values. */
  /**
   * The table's columns. Carries the ROW KEY beside the label because the label is
   * a lossy projection — `columnLabel` humanizes, and `{amount, Amount}` both
   * render "Amount", which repeated as a React key inside one row. The key is an
   * object key and is unique by construction.
   */
  columns: ColumnSpec[];
  /** One array of cells per row, aligned to `columns`. Empty for a scalar. */
  rows: string[][];
  source: SourceLocation | null;
  /** The model's self-rating, or null when it gave none — which is the common case. */
  confidence: number | null;
  /** A person supplied this value — corrected or added (LP-703). */
  corrected: boolean;
  /**
   * What the model said, when a person overruled it. Null when nothing was
   * replaced.
   *
   * SHOWN BESIDE THE CORRECTION, not instead of it. Until LP-703 the row rendered
   * the EXTRACTED value with a "Verified" mark next to it, so a processor who had
   * just typed 4,200 went on reading 15,000 — and once corrections started
   * reaching the rule engine that became the screen and the checks disagreeing
   * about the same field.
   */
  replacedValue: string | null;
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

// --- Shape-aware display (LP-702) ------------------------------------------- //

/** The grouped catch-all, which has its own labelled renderer. */
const CATCH_ALL_KEY = "additional_sections";

/**
 * Row keys that say WHERE a value was read rather than what it is.
 *
 * Every list contract in `app/ai/prompts/extraction/` carries `page` and
 * `snippet` on each row. They are kept — dropping them would throw away the
 * only provenance a nested row has — but they sort to the end, so the columns a
 * processor came to read are the ones on the left.
 */
const PROVENANCE_KEYS = new Set(["page", "snippet", "source"]);

const PROVENANCE_LABELS: Record<string, string> = {
  page: "Page",
  snippet: "Read from",
  source: "Source",
};

/** "1 row" / "14 rows" — a count that reads as a sentence rather than a number. */
function countLabel(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}

function isPlainObject(raw: unknown): raw is Record<string, unknown> {
  return typeof raw === "object" && raw !== null && !Array.isArray(raw);
}

/**
 * A display string for any single value.
 *
 * THE ONE GUARANTEE: this never returns `[object Object]`. A shape with no
 * honest one-line form says what it is instead of being handed to `String()`.
 */
function leafDisplay(raw: unknown): string {
  if (raw === null || raw === undefined || raw === "") return EMPTY_VALUE;
  if (Array.isArray(raw)) {
    return raw.length === 0 ? EMPTY_VALUE : countLabel(raw.length, "item");
  }
  if (isPlainObject(raw)) return compactRecord(raw);
  return String(raw);
}

/** How many of a nested object's own entries are worth putting on one line. */
const INLINE_ENTRY_LIMIT = 3;

/**
 * A nested object flattened onto one line — `Charge: 450 · Paid: 0`.
 *
 * A count ("4 fields") would be honest and useless. Naming the first few
 * entries is what lets a processor tell two rows apart without opening either.
 */
function compactRecord(raw: Record<string, unknown>): string {
  const entries = Object.entries(raw).filter(
    ([, value]) => value !== null && value !== undefined && value !== "",
  );
  if (entries.length === 0) return EMPTY_VALUE;
  const shown = entries
    .slice(0, INLINE_ENTRY_LIMIT)
    // MASKED PER ENTRY. Joining first and masking the result asks the identifier
    // test about a line like `Number: 123456789 · Balance: 450.00` — where the
    // money exclusion fires on the SIBLING's cents and clears the whole cell,
    // identifier included. Each entry is judged against its own label and value.
    .map(([key, value]) => {
      const label = labelFor(key);
      return `${label}: ${catchAllDisplay(label, scalarOrCount(value))}`;
    })
    .join(" · ");
  const rest = entries.length - INLINE_ENTRY_LIMIT;
  return rest > 0 ? `${shown} · +${rest} more` : shown;
}

/** A leaf inside an already-flattened line: scalars as themselves, deeper shapes as a count. */
function scalarOrCount(raw: unknown): string {
  if (Array.isArray(raw)) return countLabel(raw.length, "item");
  if (isPlainObject(raw)) return countLabel(Object.keys(raw).length, "field");
  return String(raw);
}

/**
 * One cell of a nested row.
 *
 * Masked through `catchAllDisplay`, not through the backend's identity list.
 * Nested rows are keyed by names the MODEL chose — `tradelines[].account_number`
 * is not a key `field_scrutiny` reports on — so the label+value test is the only
 * one that reaches this path. It excludes money first, so a running balance is
 * not hidden for having digits in it.
 */
function cellDisplay(key: string, raw: unknown): string {
  if (MASKED_FIELD_KEYS.has(key)) return maskedDisplay(key, raw);
  const text = leafDisplay(raw);
  if (text === EMPTY_VALUE) return text;
  // A PROVENANCE CELL IS A SENTENCE, not a value. `snippet` is the quoted line a
  // row was read from, and it is kept precisely because it is the only provenance
  // a nested row has — but the whole-cell mask replaced it outright, so a snippet
  // reading "CHASE CARD 4147202512345678 Balance 1,203" became "••••1203": the
  // provenance gone, and the last-4 taken from the balance rather than the card.
  // The identifier inside it is redacted in place instead.
  if (PROVENANCE_KEYS.has(key)) return redactIdentifiers(text);
  return catchAllDisplay(labelFor(key), text);
}

/**
 * Mask identifier-shaped runs WITHIN a string, leaving the words around them.
 *
 * For provenance text only. Everywhere else a value either is an identifier or is
 * not, and the whole cell is the right unit; a snippet is prose that may happen to
 * contain one.
 */
function redactIdentifiers(text: string): string {
  return text
    .replace(/\b\d{3}[- ]\d{2}[- ]\d{4}\b/g, (m) => `•••-••-${m.slice(-4)}`)
    .replace(/\b\d{9,}\b/g, (m) => `••••${m.slice(-4)}`);
}

function columnLabel(key: string): string {
  return PROVENANCE_LABELS[key] ?? labelFor(key);
}

/**
 * A list of objects as aligned columns and rows.
 *
 * Columns are the UNION of the items' keys, not the first item's: a ledger whose
 * first row has no `paid` would otherwise drop that column for every row after
 * it. Order is first-seen, with the provenance keys pushed to the end.
 *
 * A list whose items are not all objects (plain strings, or a mix) gets no
 * columns and one cell per row — there is nothing to align.
 */
function tableFrom(
  parentKey: string,
  items: readonly unknown[],
): { columns: ColumnSpec[]; rows: string[][] } {
  if (!items.every(isPlainObject)) {
    // THROUGH THE MASK, like every other cell. This branch called `leafDisplay`
    // directly, so a list of bare strings was the one path that skipped the
    // identifier test entirely: `borrower_identifiers: ["123-45-6789"]` rendered
    // in the clear, while the same value inside an object row was masked. There
    // is no row key here, so the LIST's own key names the column.
    return { columns: [], rows: items.map((item) => [cellDisplay(parentKey, item)]) };
  }
  const keys: string[] = [];
  for (const item of items) {
    for (const key of Object.keys(item)) if (!keys.includes(key)) keys.push(key);
  }
  const ordered = [
    ...keys.filter((k) => !PROVENANCE_KEYS.has(k)),
    ...keys.filter((k) => PROVENANCE_KEYS.has(k)),
  ];
  return {
    columns: ordered.map((key) => ({ key, label: columnLabel(key) })),
    rows: items.map((item) => ordered.map((key) => cellDisplay(key, item[key]))),
  };
}

/** One column of a nested table: the row key it reads, and the words shown for it. */
export interface ColumnSpec {
  key: string;
  label: string;
}

/** The value half of an `ExtractionField` — everything except its key, label and provenance. */
type FieldShape = Pick<ExtractionField, "value" | "kind" | "columns" | "rows">;

const SCALAR: Pick<FieldShape, "kind" | "columns" | "rows"> = {
  kind: "scalar",
  columns: [],
  rows: [],
};

/**
 * What a field's value is, and how it should be shown.
 *
 * A field the backend calls an identifier is NEVER expanded, whatever shape it
 * arrives in — a masked list would leak through its rows. It renders as bullets,
 * which says something is there without saying what.
 */
function shapeOf(key: string, value: unknown, masked: boolean): FieldShape {
  if (masked) {
    if (Array.isArray(value) || isPlainObject(value)) return { ...SCALAR, value: "•••" };
    return { ...SCALAR, value: maskedDisplay(key, value) };
  }
  if (Array.isArray(value)) {
    // An empty list is not a table with no rows; it is a field with nothing in it.
    if (value.length === 0) return { ...SCALAR, value: EMPTY_VALUE };
    return {
      ...tableFrom(key, value),
      kind: "list",
      value: countLabel(value.length, "row"),
    };
  }
  if (isPlainObject(value)) {
    const entries = Object.keys(value);
    if (entries.length === 0) return { ...SCALAR, value: EMPTY_VALUE };
    return {
      ...tableFrom(key, [value]),
      kind: "record",
      value: countLabel(entries.length, "field"),
    };
  }
  return { ...SCALAR, value: displayValue(key, value) };
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

function maskedDisplay(key: string, value: unknown): string {
  const raw = value == null ? null : String(value);
  // An SSN or ITIN gets the ***-**-#### format; other ids (account number) get last-4.
  return /ssn|itin/.test(key) ? maskSsn(raw) : maskLast4(raw);
}

/**
 * The typed core as ordered, labelled rows. Works for any document type — known
 * fields (pay stub / W-2) appear first in a sensible order, then any others.
 * Sensitive fields (e.g. the W-2 SSN) are **masked** in display; absent/null
 * values render as `EMPTY_VALUE`.
 *
 * Only the catch-all is held back, because it has its own labelled renderer.
 * `transactions` used to be held back too and is not any more: it is a list like
 * the other 77, and giving it a private renderer is what left the rest with none.
 */
export function extractionFields(
  data: Record<string, unknown>,
  /**
   * Field keys the backend says are identifiers (LP-UI-032). Masked ON TOP of
   * `MASKED_FIELD_KEYS`, never instead of it: a backend that stops answering must
   * not be able to un-mask something that is masked today.
   */
  sensitiveKeys?: ReadonlySet<string>,
  /**
   * What a processor supplied, by field key (LP-703).
   *
   * SUBSTITUTED BEFORE THE MASK AND THE FORMATTING, exactly as the backend does it
   * in `build_document_fields`. A corrected SSN then travels the identical masking
   * path an extracted one does, and a corrected money field is formatted the same
   * way. Rendering the correction afterwards would mean a second copy of both, and
   * the second copy is where a raw identifier eventually reaches the screen.
   */
  corrections?: ReadonlyMap<string, FieldCorrection>,
): ExtractionField[] {
  const fields: ExtractionField[] = [];
  // An ADDED field is by definition a key the extraction has no entry for, so it
  // cannot be reached by walking `data`. Extraction order first, so an addition
  // can never shadow a key the model produced — the API refuses that case, and
  // this makes it harmless if it ever slips.
  const addedKeys = [...(corrections?.keys() ?? [])].filter((key) => !(key in data));
  for (const key of [...Object.keys(data), ...addedKeys]) {
    if (key === CATCH_ALL_KEY) continue;
    const { value, source, confidence } = readTypedField(data[key]);
    const masked = MASKED_FIELD_KEYS.has(key) || Boolean(sensitiveKeys?.has(key));
    const correction = corrections?.get(key);
    const supplied = correction !== undefined && !correction.removed && correction.value !== null;
    const shown = supplied ? correction.value : value;
    const replaced = supplied && value !== null ? shapeOf(key, value, masked).value : null;
    fields.push({
      key,
      label: labelFor(key),
      ...shapeOf(key, shown, masked),
      source,
      // A person's value has no model rating, and carrying the old one forward
      // would report the model as sure about a figure it never saw.
      confidence: supplied ? null : confidence,
      corrected: supplied,
      replacedValue: replaced,
    });
  }
  // Known typed-core fields first (in order), then any others.
  const orderIndex = (k: string) => {
    const i = EXTRACTION_FIELD_ORDER.indexOf(k);
    return i === -1 ? Number.MAX_SAFE_INTEGER : i;
  };
  return fields.sort((a, b) => orderIndex(a.key) - orderIndex(b.key));
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

/**
 * The keys the backend reports as identifiers, as a set.
 *
 * ONE DEFINITION, because two callers need it and they disagreed. The reviewer's
 * field pane computed it and passed it in; the review PAGE called
 * `extractionFields` without it, to feed the queue. So a backend-sensitive field
 * arriving as a list was a masked SCALAR in the pane — mark, editor and all — and
 * a LIST to the queue, which drops lists: it could never be stopped on, and
 * `isFullyReviewed` ignored it.
 */
/**
 * A processor's overrides, keyed by field, as `extractionFields` wants them.
 *
 * ONE DEFINITION, for the third time. The pane computed this and the review PAGE
 * did not, so an added field was drawn on screen and absent from `rowKeys`, the
 * queue, the labels map and `editableFieldKey` — the arrows and Tab stepped past
 * it, `selected` could never name it, and E/R could not open its editor. The one
 * value on the document a human is personally answerable for was the one row the
 * keyboard could not reach.
 *
 * `sensitiveKeysOf` exists because those same two call sites drifted over
 * `sensitiveKeys`. That it has happened again with a second argument is the
 * argument for the page passing its fields DOWN rather than the pane recomputing
 * them — recorded on LP-701, still open.
 */
export function correctionsOf(
  scrutiny:
    | Record<string, { verdict?: string | null; corrected_value?: string | null }>
    | undefined,
): Map<string, { value: string | null; removed: boolean }> {
  return new Map(
    Object.entries(scrutiny ?? {})
      .filter(
        ([, s]) => s?.verdict === "corrected" || s?.verdict === "added" || s?.verdict === "removed",
      )
      .map(([key, s]) => [
        key,
        { value: s.corrected_value ?? null, removed: s.verdict === "removed" },
      ]),
  );
}

export function sensitiveKeysOf(
  scrutiny: Record<string, { sensitive?: boolean }> | undefined,
): Set<string> {
  return new Set(
    Object.entries(scrutiny ?? {})
      .filter(([, s]) => s?.sensitive)
      .map(([key]) => key),
  );
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
 * So: money and rates are excluded first, then an SSN SHAPE is an identifier whatever
 * the label claims, then a label naming a WORKING identifier wins over a bare digit
 * run, and below that the label has to say so.
 */
const IDENTIFIER_LABEL =
  /\b(ssns?|social security (number|no)|tax(payer)? id|tins?|eins?|account (number|no)|routing|passport|licen[sc]e number)\b/i;

/**
 * A WORKING identifier — one a processor reads in order to do the job.
 *
 * MIRRORS THE BACKEND'S `pii_readable` (`critical_fields.yaml`), which already lists
 * loan_number, policy_number, case_number, permit_number and twenty more as
 * classified-PII-but-shown: they are kept out of LLM snapshots and analytics views
 * and put on the processor's own screen, because reading them IS the job.
 *
 * Without this, the two masking paths answered differently about the same field. A
 * typed-core `loan_number` is shown — the backend says so. The same loan number
 * inside a nested row was masked to `••••6789` by the bare 9+ digit rule, since
 * `field_scrutiny` does not report on row keys and nothing else spoke for it. Worse,
 * the answer depended on the LENDER: an 8-digit loan number rendered, a 10-digit one
 * did not, which is not a distinction about sensitivity at all.
 *
 * It is deliberately checked AFTER the SSN shape. A dashed `123-45-6789` is an SSN
 * whoever labelled the column; this only decides bare digit runs, where the label is
 * the sole evidence either way.
 *
 * EVERY ALTERNATIVE HERE IS A STEM FROM THAT BACKEND LIST, and nothing else. A first
 * draft added `check`, `claim`, `item`, `reference` and `confirmation` on the reasoning
 * that they "look like" working identifiers — inventing policy the backend had not
 * agreed. One of them was a live leak: `claim_number_masked` IS masked there, so
 * "Claim number" would have been un-masked by a rule meant only to stop over-masking.
 * An allow-list that makes things LESS hidden is green by construction; it grows only
 * when `pii_readable` does.
 */
const READABLE_IDENTIFIER_LABEL =
  /\b(loan|invoice|receipt|policy|control|document|project|job|employee|certificate|registration|parcel|apn|case|permit|quote|commitment|form|amendment|submission)\s*(number|no|id)\b|\bphone\b/i;

export function catchAllIsSensitive(label: string, value: string): boolean {
  // A status word ("Match", "No alert") carries no identifier to hide, and masking it
  // to bullets destroys the only thing the row said.
  if (!/\d/.test(value)) return false;
  // Money and rates. A decimal fraction or a currency/percent mark says this is an
  // amount — no identifier is written with cents.
  if (/[$%]|\d\.\d/.test(value)) return false;
  // An SSN SHAPE is an SSN whatever the column is called.
  if (/\d{3}[- ]\d{2}[- ]\d{4}/.test(value)) return true;
  // A named working identifier is READ, not hidden — however many digits it runs to.
  if (READABLE_IDENTIFIER_LABEL.test(label)) return false;
  if (/\b\d{9,}\b/.test(value)) return true;
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
