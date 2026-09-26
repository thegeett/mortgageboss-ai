/**
 * Condition rounds and conditions (LP-904 schema; LP-905/907/909 use them).
 *
 * Mirrors `backend/app/schemas/condition.py`. Two rules from Stage 0 shape what is here and, more
 * importantly, what is NOT:
 *
 * * **The lender's wording is carried verbatim and never paraphrased** (ADR-405). `verbatim_text` is
 *   rendered in `font-serif` because it is quoted from a document.
 * * **Stage 1 has no status controls** (ADR-404). `prep_status` and `lender_status` exist on the
 *   backend row and are deliberately absent from `ConditionPublic` — they are created with defaults
 *   and nothing moves them, so exposing them would invite a UI that implies otherwise.
 *
 * A DRAFT ROW IS NOT A CONDITION. `DraftRow` is a parse result awaiting review: it has a confidence
 * and the source lines it came from, and no identity of its own until import.
 */

// --- enums, mirroring the backend StrEnums ---------------------------------- //

/** WHEN a condition must be satisfied, read from the lender's own heading. */
export type BucketKind =
  | "master"
  | "prior_to_approval"
  | "prior_to_docs"
  | "prior_to_closing"
  | "prior_to_funding"
  | "lender_to_clear"
  | "trailing"
  | "unknown";

/**
 * A bucket kind in a processor's words — S1-12's Heading select and the review screen's groups.
 *
 * ⚠️ IT LIVES HERE RATHER THAN IN `lib/status.ts`, WHICH IS WHERE IT LOOKS LIKE IT BELONGS. Every
 * vocabulary in that module is a `Record<K, StatusMeta>` carrying a TONE for `StatusToken`. A
 * heading has no tone — it is not blocking, verified, or in progress, it is where on the sheet the
 * lender put the condition — so giving it one would invent a judgement the data does not make, and
 * put a non-status in a file whose whole contract is status tone.
 *
 * ⚠️ AND IT IS NOT DERIVED BY DE-SNAKING THE VALUE. `prior_to_docs` → "Prior to docs" happens to
 * work; `lender_to_clear` → "Lender to clear" reads as an instruction to the processor when it
 * means the LENDER clears it, and `master` → "Master" says nothing at all. The labels are written,
 * so each one can be right.
 */
export const BUCKET_KIND_LABEL: Record<BucketKind, string> = {
  master: "Master (applies to the whole file)",
  prior_to_approval: "Prior to approval",
  prior_to_docs: "Prior to docs",
  prior_to_closing: "Prior to closing",
  prior_to_funding: "Prior to funding",
  lender_to_clear: "The lender clears this",
  trailing: "Trailing (after closing)",
  unknown: "No heading given",
};

/** Who probably has to act. A HINT, never a decision — Stage 3 decides. */
export type OwnerHint =
  | "borrower"
  | "title"
  | "insurance"
  | "lender"
  | "broker"
  | "processor"
  | "unknown";

/**
 * Where the hint came from, so a processor can weigh it.
 *
 * Carried because the hints are not equally good: a `TC:` the lender typed is far stronger evidence
 * than a default looked up from the code map, and a UI showing them identically would invite
 * trusting the weak one. S1-04 renders this under the chip ("from code map" / "from “TC:” prefix").
 */
export type OwnerHintSource = "prefix" | "bucket" | "code_map" | "none";

/** Whether the condition came off a sheet or was typed by a processor. */
export type ConditionOrigin = "sheet" | "manual";

/** Where a round is between arriving and being imported. */
export type ConditionRoundStatus = "parsing" | "draft" | "parse_failed" | "imported" | "discarded";

/**
 * Whether this round is the lender's WHOLE list or only part of it (ADR-404).
 *
 * Load-bearing rather than descriptive: absence is evidence only when the thing absent was in a
 * list claiming to be complete. A `partial` source may add and update; it may never remove or clear.
 */
export type ConditionRoundCompleteness = "full" | "partial";

/** Which layout the reader recognised (LP-906). */
export type ConditionSheetFormat =
  | "uwm_approval_letter"
  | "champions_certificate"
  | "generic"
  | "pasted_text";

/** How one arrival of a round reached us. A round has a LIST — a paste can be enriched by its PDF. */
export type ConditionSourceKind = "pdf_upload" | "email" | "paste" | "manual";

/**
 * What happened to a round — the history on the round-details sheet (S1-09).
 *
 * Stage 1 writes all of these and nothing else. Note what is ABSENT and stays absent until Stage 2:
 * there is no `condition_cleared` and no `round_compared`, because Stage 1 cannot produce them and
 * an enum member nothing writes is an invitation (ADR-404).
 */
export type ConditionEventKind =
  | "round_received"
  | "round_parsed"
  | "round_parse_failed"
  | "round_reparse_requested"
  | "round_imported"
  | "round_discarded"
  | "round_enriched"
  | "condition_created"
  | "condition_seen_again"
  | "condition_note_added"
  | "condition_edited";

/**
 * One line of a round's history (S1-09).
 *
 * ⚠️ THE SERVER PROJECTS NAMED SCALARS AND NEVER `detail`, so this carries a wide set of optional
 * fields rather than a payload. `ConditionEvent.detail` is classified NPI — "what changed, which is
 * the lender's text" — and the readonly layer drops it whole, so the history is composed from counts
 * and identifiers instead.
 *
 * ⚠️ `actor_user_id` IS NULL FOR A SYSTEM EVENT, and that is a fact rather than missing data: a parse
 * task has no actor, and naming the processor who uploaded the sheet would make the trail say
 * something untrue.
 */
export interface ConditionEvent {
  kind: ConditionEventKind;
  occurred_at: string;
  actor_user_id: string | null;
  source_kind: string | null;
  reader: string | null;
  reader_version: string | null;
  rows: number | null;
  duplicates_dropped: number | null;
  round_number: number | null;
  created: number | null;
  seen_again: number | null;
  from_status: string | null;
  filled_from: string | null;
}

/** The paste endpoint's ceiling, enforced by the request schema (spec §LP-907). */
export const MAX_PASTE_CHARS = 100_000;

// --- reads ------------------------------------------------------------------ //

/**
 * A dated note the underwriter appended inside the condition's text.
 *
 * Carried as structure AND left inside `verbatim_text`, deliberately: the lender wrote one string,
 * and a UI showing the note as though it were ours would misattribute it. The structure is what lets
 * the review screen render it as a dated chip beside the wording rather than inside it.
 */
export interface UnderwriterNote {
  date: string | null;
  text: string;
  first_seen_round_id: string | null;
}

export interface ConditionSource {
  kind: ConditionSourceKind;
  at: string | null;
  document_id: string | null;
  inbound_attachment_id: string | null;
  user_id: string | null;
  /**
   * Whether this arrival stored bytes — what "can this round still take a PDF" reduces to.
   *
   * ⚠️ IT EXISTS BECAUSE THE CLIENT COULD NOT ASK THE SERVER'S QUESTION. `_has_pdf_source` keys on
   * `storage_path`, which was not serialised, so the round strip kept a list of `kind` values —
   * exactly the list that function's comment warns against. It held only because every
   * bytes-carrying source happens to be written as `pdf_upload` or `email` today.
   *
   * A boolean rather than the path: the path is server-controlled so a sender's filename never
   * shapes the storage layout, and shipping it would export that layout to answer yes or no.
   */
  has_bytes: boolean;
}

/**
 * What the reader did — the honest record of a parse, including what it could not place.
 *
 * `unassigned_lines` is the invariant spec §9.2 exists for: every non-blank line becomes a row, a
 * heading, a known artifact, or an entry here. Nothing is silently dropped, and S1-10/S1-11 show
 * these so a processor can add or ignore each one.
 */
export interface ParseReport {
  reader: string | null;
  reader_version: string | null;
  warnings: string[];
  unassigned_lines: string[];
  duplicates_dropped: number;
  ai_used: boolean;
  /**
   * ⚠️ NOT THE SAME FACT AS `ai_used`, AND THE PAIR IS READ TOGETHER. `needs_ai` is the READER's
   * verdict that the rules could not split this text; `ai_used` is whether an AI split actually ran.
   * Both false means the rules read it. `needs_ai` true with `ai_used` false means the round is
   * waiting for the split task — a state that has to be findable.
   */
  needs_ai: boolean;
  /** Set only on `parse_failed` — the typed reason S1-03 shows in mono, never a bare exception. */
  failure_kind: string | null;
  failure_detail: string | null;
}

/** One parsed row awaiting review. No identity until import. */
export interface DraftRow {
  sequence: number;
  lender_code: string | null;
  lender_category: string | null;
  bucket_heading: string;
  bucket_kind: BucketKind;
  verbatim_text: string;
  underwriter_notes: UnderwriterNote[];
  owner_hint: OwnerHint;
  owner_hint_source: OwnerHintSource;
  processor_assist: boolean;
  /**
   * 1.0 for a row the rules read; 0.6 for an AI split (LP-908). S1-10 sorts anything below 0.8
   * first and requires the flagged-rows checkbox before import.
   */
  confidence: number;
  source_line_numbers: number[];
}

/** One imported condition, as the list renders it. NO STATUS FIELDS — see the module docstring. */
export interface Condition {
  id: string;
  lender_code: string | null;
  lender_category: string | null;
  bucket_heading: string;
  bucket_kind: BucketKind;
  /** The lender's words. Rendered in serif; never paraphrased anywhere in the stack. */
  verbatim_text: string;
  underwriter_notes: UnderwriterNote[];
  owner_hint: OwnerHint;
  owner_hint_source: OwnerHintSource;
  info_only: boolean;
  canonical_type_id: string | null;
  origin: ConditionOrigin;
  sequence: number;
  first_round_id: string;
  last_seen_round_id: string;
  /**
   * Every round this condition appeared on — the `R1 R2` chips.
   *
   * Derived server-side from its `CONDITION_CREATED` / `CONDITION_SEEN_AGAIN` events rather than
   * from `first_round_id` / `last_seen_round_id`, because two columns cannot express "appeared on
   * R1 and R3 but not R2", which is the whole point of the chips.
   */
  round_numbers: number[];
  created_at: string;
}

export interface ConditionRound {
  id: string;
  /** Assigned on IMPORT. Null on a draft — S1-05's strip must render a numberless card. */
  round_number: number | null;
  status: ConditionRoundStatus;
  completeness: ConditionRoundCompleteness;
  sheet_format: ConditionSheetFormat;
  sources: ConditionSource[];
  date_printed: string | null;
  round_date: string;
  expiry_dates: Record<string, string | null> | null;
  /**
   * ⚠️ PRESENT DOES NOT MEAN REVIEWABLE. A `parsing` round awaiting the AI split carries the
   * rules-read rows too, and S1-02 renders skeletons and polls rather than showing them. Read
   * `status` to decide whether a processor may act on these, never their presence.
   */
  draft_rows: DraftRow[] | null;
  parse_report: ParseReport;
  /** The letter's own details for the side panel. Absent for a paste, which has no letter. */
  header: Record<string, unknown> | null;
  condition_count: number;
  created_at: string;
  /**
   * When the row last changed — the value `expected_updated_at` must echo on a draft save.
   *
   * ⚠️ IT WAS NOT EXPOSED, WHICH MADE THE STALE-WRITE GUARD UNREACHABLE. `ConditionDraftUpdate`
   * says "the caller sends the `updated_at` it read", and no caller could read it: the round
   * schema carried only `created_at`. So two tabs on one draft — the case the 409 exists for —
   * would both have sent `null` and the second would have overwritten the first in silence.
   * Added to `ConditionRoundPublic` alongside this (LP-909 §4).
   */
  updated_at: string;
}

// --- writes ----------------------------------------------------------------- //

export interface PasteConditionsInput {
  text: string;
  /**
   * REQUIRED, with no default here on purpose. The UI defaults the control to "just some" — the
   * answer that can never remove anything — but the API refusing to guess is what makes it a
   * decision rather than a fallback (ADR-404).
   */
  completeness: ConditionRoundCompleteness;
  round_date?: string | null;
}

export interface DraftUpdateInput {
  draft_rows: DraftRow[];
  completeness?: ConditionRoundCompleteness | null;
  round_date?: string | null;
  /**
   * The `updated_at` the caller read. A mismatch is refused with 409 rather than silently
   * overwriting another tab's edit — and it also refuses a tab whose rows were changed by an
   * enrich or a re-parse, which is the same hazard.
   */
  expected_updated_at?: string | null;
}

export interface AddConditionInput {
  /** Stored exactly as typed — S1-12's hint is "Type it exactly as the lender wrote it." */
  verbatim_text: string;
  lender_code?: string | null;
  lender_category?: string | null;
  bucket_heading?: string | null;
  bucket_kind?: BucketKind;
}

/** What an import did — the toast and the timeline entry. */
export interface ConditionImportResult {
  round_id: string;
  round_number: number;
  created: number;
  /** Never implies anything was closed: a condition missing from a new sheet is simply not touched. */
  seen_again: number;
  unmapped_codes: string[];
}

/** What attaching the lender's PDF to an existing round did (LP-907, screen S1-09). */
export interface ConditionEnrichResult {
  round_id: string;
  round_number: number | null;
  status: ConditionRoundStatus;
  sheet_format: ConditionSheetFormat;
  filled_header: boolean;
  filled_expiry: boolean;
  filled_date_printed: boolean;
  matched: number;
  added: number;
  /** A COUNT, not the texts — those are the lender's words and come back on the round. */
  unmatched_existing: number;
  warnings: string[];
}
