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
 * IT LIVES HERE RATHER THAN IN `lib/status.ts`, WHICH IS WHERE IT LOOKS LIKE IT BELONGS. Every
 * vocabulary in that module is a `Record<K, StatusMeta>` carrying a TONE for `StatusToken`. A
 * heading has no tone — it is not blocking, verified, or in progress, it is where on the sheet the
 * lender put the condition — so giving it one would invent a judgement the data does not make, and
 * put a non-status in a file whose whole contract is status tone.
 *
 * AND IT IS NOT DERIVED BY DE-SNAKING THE VALUE. `prior_to_docs` → "Prior to docs" happens to
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

/**
 * The same kinds as they appear on a CHIP beside a group heading.
 *
 * SHORTER THAN `BUCKET_KIND_LABEL`, AND THAT IS WHY THERE ARE TWO (LP-909 §5 visual check). A
 * select needs a label that stands alone — "The lender clears this", "Master (applies to the whole
 * file)" — while a chip sits directly beside the lender's own heading and the design writes it as
 * "Lender clears", "Master", "Prior to docs".
 *
 * AND THE LONG FORM BROKE A MUST-MATCH RULE. S1-04 says there is NO chip when the kind equals the
 * heading, which is how "Master" is drawn — but comparing the heading against "Master (applies to the
 * whole file)" never matched, so S1-11 rendered a chip the design omits. The chip vocabulary is what
 * that comparison has to use.
 */
export const BUCKET_KIND_CHIP: Record<BucketKind, string> = {
  master: "Master",
  prior_to_approval: "Prior to approval",
  prior_to_docs: "Prior to docs",
  prior_to_closing: "Prior to closing",
  prior_to_funding: "Prior to funding",
  lender_to_clear: "Lender clears",
  trailing: "Trailing",
  unknown: "No heading",
};

/**
 * Whether a round is the lender's whole list or only part of it, as a CHIP.
 *
 * ONE VOCABULARY, BECAUSE THERE WERE ALREADY FOUR (LP-909 §5). `round-strip.tsx` and
 * `round-details-sheet.tsx` each wrote `completeness === "full" ? "Full list" : "Just some"` inline,
 * `round-review.tsx` wrote a prose form of the same fact, and `paste-conditions-dialog.tsx` a third
 * wording for its radio — and S1-07 and S1-10 needed a fifth. This is precisely what
 * `BUCKET_KIND_CHIP` was split out for: a label copied until two copies disagree.
 *
 * AND A TERNARY IS NOT EXHAUSTIVE OVER THE UNION, WHICH IS THE PART THAT WILL BITE. With two
 * members today, `completeness === "full" ? … : …` is right by accident — a third member would read
 * as "Just some" in four places at once, silently, because the else-branch swallows it. A `Record`
 * keyed on the union makes the compiler demand an answer for the new member.
 *
 * The paste dialog's radio keeps its own fuller wording ("Just some conditions") deliberately: a
 * radio has to stand alone where a chip sits beside the round it describes.
 */
export const COMPLETENESS_CHIP: Record<ConditionRoundCompleteness, string> = {
  full: "Full list",
  partial: "Just some",
};

/**
 * Which layout the reader recognised, in the words S1-04 and S1-10 print.
 *
 * ONE COPY: this was defined identically in `round-review.tsx` and `round-details-sheet.tsx`, and
 * the two had already drifted in TYPE — one keyed on the union, the other `Record<string, string>`
 * with a `?? round.sheet_format` fallback for a value the union cannot hold. Keyed on the union, the
 * fallback is unnecessary rather than merely unused.
 */
export const FORMAT_LABEL: Record<ConditionSheetFormat, string> = {
  uwm_approval_letter: "UWM · Loan Approval Conditions",
  champions_certificate: "Champions · Conditional Approval",
  generic: "Unrecognised layout",
  pasted_text: "Plain text · no lender layout found",
};

/**
 * The layout's short name, for a round whose text was PASTED rather than uploaded (S1-07).
 *
 * `sheet_format` ALONE CANNOT TELL THOSE APART. `read_pasted_text` returns
 * `UWM_APPROVAL_LETTER` for a paste it recognised — the same value an uploaded letter carries — so
 * S1-07's header read "UWM · Loan Approval Conditions", naming a letter nobody sent us. The design's
 * line is "UWM layout · recognised in the pasted text", which says what was actually recognised and
 * where.
 *
 * `null` for the two formats that name no lender layout: "Unrecognised layout · recognised in the
 * pasted text" would contradict itself.
 */
export const LAYOUT_NAME: Record<ConditionSheetFormat, string | null> = {
  uwm_approval_letter: "UWM layout",
  champions_certificate: "Champions layout",
  generic: null,
  pasted_text: null,
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

/**
 * OUR preparation track: what we are doing (ADR-404, ADR-408). Four steps on screen.
 *
 * `review` IS IN THIS UNION AND IS NEVER OFFERED, and it must stay. Default A4 keeps it in the
 * database — removing an enum member costs a migration for no gain, and Stage 3 may use it for
 * "document arrived, checking it" — while no Stage 2 control lists it. The cross-stack guard
 * (`backend/tests/test_condition_type_mirror.py`) asserts SET EQUALITY with the backend enum in both
 * directions, so deleting it here to match what the UI shows breaks the build rather than tidying
 * anything. Leave it, and leave it out of the selects.
 */
export type ConditionPrepStatus = "to_do" | "waiting" | "review" | "ready" | "with_underwriter";

/**
 * THE LENDER'S track: what the lender said (ADR-404, ADR-408).
 *
 * Nothing moves this off `open` except a recorded verdict — who said so and where — or the lender's
 * own dated note, which sets `not_cleared`. "Cleared" never appears next to anything else.
 *
 * `pending_review` is the counterpart of `review` above: kept in the database by A4, never offered.
 */
export type ConditionLenderStatus =
  | "open"
  | "pending_review"
  | "cleared"
  | "not_cleared"
  | "waived"
  | "superseded";

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
 * How the conditions list is ordered (LP-911). Sent as the `sort` query parameter.
 *
 * `sheet` is the default and is the order the lender printed them in on the newest sheet, which is
 * the order the processor sees in the lender's own portal.
 *
 * `code` SORTS AS A STRING. A lender code keeps its leading zeros because it is an identifier printed
 * on a document, not a quantity (ADR-407), so `"0006"` comes before `"1228"` — the server orders it
 * and the client must not "helpfully" re-sort numerically.
 */
export type ConditionSort = "sheet" | "code" | "status" | "owner" | "updated";

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
 * THE SERVER PROJECTS NAMED SCALARS AND NEVER `detail`, so this carries a wide set of optional
 * fields rather than a payload. `ConditionEvent.detail` is classified NPI — "what changed, which is
 * the lender's text" — and the readonly layer drops it whole, so the history is composed from counts
 * and identifiers instead.
 *
 * `actor_user_id` IS NULL FOR A SYSTEM EVENT, and that is a fact rather than missing data: a parse
 * task has no actor, and naming the processor who uploaded the sheet would make the trail say
 * something untrue.
 */
export interface ConditionEvent {
  kind: ConditionEventKind;
  occurred_at: string;
  actor_user_id: string | null;
  /** A closed enum on the wire, not an open string — an unrecognised value arrives as null. */
  source_kind: ConditionSourceKind | null;
  reader: string | null;
  rows: number | null;
  round_number: number | null;
  created: number | null;
  seen_again: number | null;
  from_status: ConditionRoundStatus | null;
  /** What an enrich actually did, so a line need not claim it filled what it did not. */
  filled_header: boolean | null;
  filled_expiry: boolean | null;
  matched: number | null;
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
   * IT EXISTS BECAUSE THE CLIENT COULD NOT ASK THE SERVER'S QUESTION. `_has_pdf_source` keys on
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
   * NOT THE SAME FACT AS `ai_used`, AND THE PAIR IS READ TOGETHER. `needs_ai` is the READER's
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

/**
 * One imported condition, as the list and the detail sheet render it.
 *
 * THE STATUS FIELDS ARRIVED IN STAGE 2 (LP-911). Through Stage 1 they were deliberately absent —
 * created with defaults and moved by nothing, so exposing them would have invited a UI implying
 * otherwise (ADR-404). LP-912 adds the endpoints that move them. **"Cleared" still means a recorded
 * verdict and nothing else**; the rule moved from "the field does not exist" to "only a verdict sets
 * it".
 *
 * `superseded_by_id` has no producer until LP-915 and is `null` until then; it is here because its
 * type is already final. `verdict` and `pending_suggestion` arrive typed with their producers
 * (LP-912, LP-915) — they shipped here first as guessed types and were taken out in review.
 */
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
  /** Our preparation track. */
  prep_status: ConditionPrepStatus;
  /** The lender's answer. Nothing but a recorded verdict moves this off `open`/`not_cleared`. */
  lender_status: ConditionLenderStatus;
  /**
   * When the row last changed — the value an LP-912 write must echo back.
   *
   * WITHOUT IT THE STALE-WRITE GUARD IS UNREACHABLE. LP-912's moves are optimistic on `updated_at`,
   * and a client cannot send a value it was never given. That is not hypothetical: LP-909 §4 found
   * the draft's 409 could never fire because `ConditionRound` carried only `created_at`.
   */
  updated_at: string;
  /**
   * The owner the list groups and filters on. `owner_hint` is the sheet's guess; this is the answer,
   * and LP-912 makes them differ by adding a manual override that wins.
   *
   * "Not known" FOLLOWS THE OWNER BEING `unknown`, NEVER THE SOURCE BEING `none`. Measured in the
   * Stage 2 survey: `1228` comes back `unknown` with source `code_map`, because the UWM map gives it
   * `default_owner_hint: unknown` — so keying the label off the source renders "Not known · from code
   * map", which S2-01 does not draw.
   */
  effective_owner: OwnerHint;
  effective_owner_source: OwnerHintSource;
  /** The newest DATED underwriter note, for the row's chip. Null when every note is undated. */
  latest_note: UnderwriterNote | null;
  /** Whether the lender still owes an answer. Info-only and replaced conditions are never open. */
  is_open: boolean;
  /** Days since this file first recorded it — not since the lender printed it. */
  days_open: number;
  /** The lender said "not satisfied". LP-912 narrows this to "because of an underwriter note". */
  came_back: boolean;
  /** Set by LP-915 when a "reworded" pair is confirmed. Nothing disappears; it points forward. */
  superseded_by_id: string | null;
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
   * PRESENT DOES NOT MEAN REVIEWABLE. A `parsing` round awaiting the AI split carries the
   * rules-read rows too, and S1-02 renders skeletons and polls rather than showing them. Read
   * `status` to decide whether a processor may act on these, never their presence.
   */
  draft_rows: DraftRow[] | null;
  parse_report: ParseReport;
  /** The letter's own details for the side panel. Absent for a paste, which has no letter. */
  header: Record<string, unknown> | null;
  condition_count: number;
  /**
   * What the import recorded, or null when the question does not apply.
   *
   * NULL IS NOT ZERO. A draft has never been imported, so the server sends null rather than 0 —
   * and "0 new" would describe an import that never happened. On an IMPORTED round 0 is a real
   * measurement: "0 new · 6 seen again" is S1-08's own line, and it is the whole point of that
   * screen that a second round added nothing and removed nothing.
   */
  created: number | null;
  seen_again: number | null;
  created_at: string;
  /**
   * When the row last changed — the value `expected_updated_at` must echo on a draft save.
   *
   * IT WAS NOT EXPOSED, WHICH MADE THE STALE-WRITE GUARD UNREACHABLE. `ConditionDraftUpdate`
   * says "the caller sends the `updated_at` it read", and no caller could read it: the round
   * schema carried only `created_at`. So two tabs on one draft — the case the 409 exists for —
   * would both have sent `null` and the second would have overwritten the first in silence.
   * Added to `ConditionRoundPublic` alongside this (LP-909 §4).
   */
  updated_at: string;
}

/**
 * One round, and whether a condition was on it — the detail sheet's Rounds pills (S2-03).
 *
 * THE THREE STATES ARE NOT TWO. A condition absent from a `full` round is genuinely absent; absent
 * from a `partial` one it says nothing at all, because the processor pasted some lines and never
 * claimed the rest were gone (ADR-404). `on_sheet` together with `completeness` is what lets the
 * screen say "not comparable" instead of implying a condition was dropped.
 */
export interface ConditionRoundAppearance {
  round_id: string;
  round_number: number | null;
  round_date: string;
  date_printed: string | null;
  completeness: ConditionRoundCompleteness;
  on_sheet: boolean;
  /** The notes that arrived IN this round, matched on each note's `first_seen_round_id`. */
  notes: UnderwriterNote[];
}

/** One condition with its whole story — the detail sheet. Extends the row so the two cannot drift. */
export interface ConditionDetail extends Condition {
  /** Every IMPORTED round on the file, oldest first, each saying whether this condition was on it. */
  rounds: ConditionRoundAppearance[];
}

/**
 * The summary bar and the file rail's counts (S2-01, S2-02).
 *
 * The three breakdowns count OPEN conditions only, which is what makes "Prior to docs open 1" a
 * different number from how many prior-to-docs conditions the file has ever had.
 */
export interface ConditionSummary {
  total: number;
  open: number;
  cleared: number;
  waived: number;
  not_cleared: number;
  superseded: number;
  info_only: number;
  by_prep_status: Record<string, number>;
  by_owner: Record<string, number>;
  by_bucket_kind: Record<string, number>;
  open_prior_to_docs: number;
  open_prior_to_funding: number;
  /** 0 until LP-915 proposes one. The round card's "N probably cleared — review" reads it. */
  pending_suggestions: number;
  /** The newest imported round, for the rail's "from round 2, printed 09/10". */
  latest_round: ConditionRound | null;
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
