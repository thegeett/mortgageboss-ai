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
export type OwnerHintSource = "prefix" | "bucket" | "code_map" | "none" | "manual";

/** Whether the condition came off a sheet or was typed by a processor. */
export type ConditionOrigin = "sheet" | "manual";

/**
 * Where the lender said it (ADR-408). Part of a verdict, and a verdict is required for one.
 *
 * THE TWO DERIVED SOURCES ARE NOT INTERCHANGEABLE WITH THE THREE A PERSON PICKS.
 * `round_comparison` and `underwriter_note` are produced by the app — the first when a processor
 * confirms a "probably cleared" suggestion, the second when the lender's own dated note reopens a
 * condition — and both name the round that showed it. The three a processor picks carry no round,
 * because a portal screen is not a sheet.
 *
 * `underwriter_note` is also what `came_back` keys on: a manual "Came back" recorded from a phone call
 * is `not_cleared` and is NOT a came-back, which is the distinction the amber rail on S2-08 draws.
 */
export type VerdictSourceKind =
  | "portal"
  | "email"
  | "phone"
  | "round_comparison"
  | "underwriter_note";

/**
 * The three sources a PERSON may record (S2-04), and the only ones the verdict and bulk endpoints
 * accept (LP-912 review). The server refuses the two derived sources from a client with
 * `verdict_needs_source`, because `came_back` keys on `underwriter_note` and a client that could post
 * it could paint *Came back* on a note that never existed. Typed here so the client cannot send them.
 */
export type ManualVerdictSourceKind = Extract<VerdictSourceKind, "portal" | "email" | "phone">;

/** Which of the three writes a bulk call applies. */
export type BulkAction = "prep_status" | "verdict" | "owner";

/**
 * Why the server refused a write (LP-912). The CODE is for the client; the sentence is for a person.
 *
 * A CLOSED UNION RATHER THAN `string`, BECAUSE THE UI BRANCHES ON IT. A bulk write reports
 * `{condition_id, code, message}` per refused row so the toast can say "1 skipped: information only"
 * without parsing prose — and branching on a mistyped literal is a branch that silently never runs.
 *
 * THE MESSAGE IS STILL WHAT GETS SHOWN. Spec §6 rule 5: refusals carry one plain sentence and the UI
 * renders it as-is. This union is for deciding which rows to group and where to put the focus, never
 * for composing a replacement wording — four of the eight sentences are the spec's, character for
 * character, and re-writing them on the client would defeat the test that pins them.
 */
export type ConditionRefusalCode =
  | "backward_move_needs_reason"
  | "info_only_has_no_status"
  | "verdict_needs_source"
  | "stale"
  | "waiting_needs_owner"
  | "nothing_to_reopen"
  | "verdict_needs_round"
  | "status_not_offered"
  | "condition_was_replaced";

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
 * Eight are Stage 2's (LP-912, ADR-408; `round_compared` and `round_completeness_changed` are
 * LP-915's), and the last five are Stage 3's reading (LP-919) and plan (LP-920). The detail sheet composes a plain-words history line from `kind`, so a member the
 * client cannot type renders as an unrecognised value — which is what the cross-stack mirror guard
 * exists to prevent.
 *
 * `condition_came_back` IS THE ONE EVENT FOR A CAME-BACK and carries both from→to pairs: the lender's
 * status to `not_cleared` and ours back to `to_do`. `condition_seen_again` still records the
 * appearance (the `R1 R2` chips derive from it), and `condition_note_added` folds into
 * `condition_came_back` when the note is what reopened the condition.
 *
 * Still absent, as deliberately as in Stage 1: no `condition_cleared` and no `condition_waived` —
 * clearing is `condition_verdict_recorded`, carrying a verdict that names who said so and where — and
 * no `condition_removed`, because nothing disappears (ADR-404).
 *
 * EVERY COMMENT ABOUT THIS UNION LIVES ABOVE IT, NOT INSIDE IT, and that is mechanical rather than
 * stylistic. `test_condition_type_mirror.py` parses the union with
 * `export type (\w+)\s*=\s*([^;]+);` — a body that stops at the first semicolon. Prose between the
 * members containing a semicolon truncates the body, so the guard silently reads a SHORTER union and
 * reports the backend as having members the frontend "does not". Measured: it did exactly that.
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
  | "condition_edited"
  | "condition_prep_moved"
  | "condition_verdict_recorded"
  | "condition_reopened"
  | "condition_came_back"
  | "condition_owner_changed"
  | "condition_superseded"
  | "round_compared"
  | "round_completeness_changed"
  | "condition_read"
  | "condition_reading_confirmed"
  | "condition_planned"
  | "condition_plan_changed"
  | "round_plan_confirmed";

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

  // --- condition-level scalars (LP-916, S2-03's History) --------------------- //
  //
  // THE FIELDS ABOVE ALL DESCRIBE A ROUND, which is why a condition's history
  // arrived as little more than a timestamp before this. Each of these is an enum
  // value, a date or a count — never the lender's words.

  /** Our track's move, on the events that state one. */
  prep_status_from: ConditionPrepStatus | null;
  prep_status_to: ConditionPrepStatus | null;
  /** Who we are waiting on, on a move TO `waiting` only (LP-916 review). */
  waiting_on: OwnerHint | null;
  /** The step that moved it, when the plan moved it (LP-921): "Moved to Ready to send (Already in the file)". */
  plan_option: PlanOption | null;
  /** The lender's track's move. */
  lender_status_from: ConditionLenderStatus | null;
  lender_status_to: ConditionLenderStatus | null;
  /**
   * Where the lender said it — a SEPARATE field from `source_kind` above.
   *
   * `source_kind` is `ConditionSourceKind` (how a ROUND arrived); this is
   * `VerdictSourceKind` (where the lender said it). Two closed vocabularies that
   * share the word "source", kept apart so a value from one cannot arrive typed
   * as the other.
   */
  verdict_source_kind: VerdictSourceKind | null;
  /** The date the LENDER said it, never ours. */
  verdict_source_date: string | null;
  /** How many notes an import added. A count — the notes themselves never travel. */
  notes_added: number | null;
  /**
   * Who did it. Null for a system event, which is a fact rather than missing
   * data: a parse task has no actor, and naming the processor who uploaded the
   * sheet would make the trail say something untrue.
   */
  actor_name: string | null;
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
 * What the lender said, and where — the verdict callout on S2-03.
 *
 * "Cleared · round 2 comparison · 09/10/2026 · Confirmed by Priya Raman on 09/10 at 4:31 PM" is this
 * object rendered. **Nothing may show "Cleared" without one** (ADR-404), which is why it travels with
 * the row rather than behind a second request: a screen saying "Cleared" has to be able to say who
 * said so.
 *
 * `source_date` IS THE LENDER'S DATE AND `recorded_at` IS OURS. Keeping both is the point — "cleared
 * on the 12th, recorded on the 14th" is a different fact from either date alone.
 *
 * `note` is the PROCESSOR'S note about the verdict ("Cleared in EASE, condition status screen"), not
 * the lender's words.
 */
export interface Verdict {
  status: ConditionLenderStatus;
  source_kind: VerdictSourceKind;
  source_date: string;
  /** The sheet that showed it, for the two sources the app derives. Null for portal/email/phone. */
  round_id: string | null;
  note: string | null;
  recorded_by: string | null;
  recorded_at: string | null;
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
  /** Who we are waiting on while our status is Waiting (LP-921: "Waiting on Borrower", "Waiting on LO"). */
  waiting_on: OwnerHint | null;
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
  /**
   * The lender said "not satisfied" AND said it in an underwriter's note (LP-912 narrowed this).
   *
   * Both halves matter: a manual "Came back" recorded from a phone call is `not_cleared` and is not
   * `came_back`, so the amber rail and the "set by the lender's 9/18 note" line on S2-08 only appear
   * for the note-sourced case.
   */
  came_back: boolean;
  /** What the lender said and where, or null while they have not answered. */
  verdict: Verdict | null;
  /** Set by LP-915 when a "reworded" pair is confirmed. Nothing disappears; it points forward. */
  superseded_by_id: string | null;
  /** LP-919 — the app's reading of the lender's words, or null before it is read. */
  reading: ConditionReading | null;
  reading_status: ConditionReadingStatus;
  reading_confidence: number | null;
  /** The library type behind the reading, for S3-01's "Library: AS-04 Earnest money" chip. */
  library_type: LibraryType | null;
  /** LP-920 — the whole condition's step when it takes one; null when its items carry their own. */
  next_step: PlanOption | null;
  /** Why the plan proposed it, in S3-02's words ("Shortfall computed by code", "Waits on 1228"). */
  plan_reason: string | null;
  items: ConditionItem[];
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

/**
 * One value the lender changed between two sheets — S2-06's "note rate 6.374% → 6.490%".
 *
 * BOTH SIDES ARE NULLABLE AND NEITHER IS EVER GUESSED. Round 1's rate lock is genuinely blank, so
 * the table draws "— → 09/30/2026": a value appearing, not changing.
 */
export interface LetterChange {
  label: string;
  old: string | null;
  new: string | null;
}

/**
 * A condition this sheet may have reworded, and the one it created (S2-08's *Was* / *Now*).
 *
 * TWO IDS, NOT TWO WORDINGS. The panel resolves both from rows it already holds, which is what keeps
 * the lender's text out of the saved comparison entirely.
 */
export interface RewordedPair {
  old_id: string;
  new_id: string;
}

/**
 * What one import changed (LP-915) — everything S2-06, S2-07, S2-08 and S2-10 draw.
 *
 * COMPUTED ONCE AND SAVED, so opening the panel later shows the same result. `compared_with` in
 * particular is a fact about the past — "compared with the 11 conditions that were open before it" —
 * and does not shrink as those conditions are answered.
 *
 * EVERY LIST IS CONDITION IDS. The panel looks each one up in the rows it already has; a suggestion
 * whose condition is not on the current page simply is not drawn rather than being half-rendered.
 */
export interface RoundComparison {
  round_id: string;
  round_number: number | null;
  /** The panel's "Compared with the N conditions that were open before it." */
  compared_with: number;
  new: string[];
  still_open: string[];
  /** Each came-back that moved OUR track — S2-08's "our status moved from … back to …". */
  came_back_moves: {
    condition_id: string;
    prep_status_from: ConditionPrepStatus;
    prep_status_to: ConditionPrepStatus;
  }[];
  came_back: string[];
  reworded: RewordedPair[];
  /**
   * Pending suggestions — a QUESTION WITH A BUTTON, never a status (design rule 4).
   *
   * Empty once she has answered, whichever way she answered: confirming records verdicts for the
   * ticked ones and the unticked ones lose the suggestion, so the panel never asks twice.
   */
  probably_cleared: string[];
  letter_changes: LetterChange[];
  /** Why nothing is suggested, shown as S2-10's callout exactly as the server words it. */
  no_suggestions_reason: string | null;
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
  /**
   * What this import changed (LP-915). Null until a round has been compared — every round 1, and
   * every round not yet imported.
   *
   * NULL IS NOT AN EMPTY COMPARISON, for the same reason `created` is null rather than 0 below: a
   * first sheet is compared against nothing, and "0 probably cleared · compared with 0" would be a
   * claim nobody made.
   */
  comparison: RoundComparison | null;
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
  /** How the round first arrived (LP-916 review) — what "Imported from round 1 (PDF upload, …)" reads. */
  arrived_as: ConditionSourceKind | null;
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
  /** LP-921 (S3-12): open and Waiting; open with an unfinished "I'll do it" step; open and Ready. */
  waiting_on_others: number;
  your_tasks: number;
  ready_to_send: number;
  /** Whether any round of the file has a plan — the bar shows S3-12's numbers only then. */
  has_plan: boolean;
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

/**
 * The field every LP-912 write may echo so a stale one is refused rather than silently winning.
 *
 * `expected_updated_at` IS THE SERVER'S NAME FOR IT, and the spec writes `updated_at` in all five
 * request bodies. The existing name won: `DraftUpdateInput` has shipped it since LP-909 for exactly
 * this purpose, and two names for one concept inside one feature is the drift this repo keeps
 * correcting. It also says the truer thing — the value the caller READ, not the value it is setting.
 *
 * OPTIONAL, AND NOT A LOOPHOLE. Omitting it means "no opinion", the same as on the draft. What makes
 * the guard real is that the client always has the value, because `Condition.updated_at` is on the
 * wire for this reason.
 */
export interface ConcurrentWrite {
  expected_updated_at?: string | null;
}

/** Move OUR track (S2-05). Forward needs nothing; backward needs a reason. */
export interface PrepStatusInput extends ConcurrentWrite {
  to: ConditionPrepStatus;
  /**
   * REQUIRED BY THE SERVER WHEN `to` IS `waiting`, and refused without it. "Waiting" with nobody
   * named is a status nobody can act on, and the list groups by owner.
   */
  waiting_on?: OwnerHint | null;
  /** Required for a BACKWARD move, and kept in the history as the only record of what went wrong. */
  reason?: string | null;
  note?: string | null;
  /** Defaults to now on a move to `with_underwriter`; sent explicitly for a submission made earlier. */
  sent_at?: string | null;
}

/**
 * Record what the lender said — the ONLY route to `cleared` or `waived` (ADR-404).
 *
 * `source_date` IS REQUIRED AND IS THE LENDER'S DATE, never today's. A verdict dated by our clock is
 * a verdict about us, which is why the server has no default for it and this type does not make it
 * optional.
 */
export interface VerdictInput extends ConcurrentWrite {
  status: ConditionLenderStatus;
  source_kind: ManualVerdictSourceKind;
  source_date: string;
  /** Optional provenance: when given, the server requires it to be a round on this file. */
  round_id?: string | null;
  /** The PROCESSOR'S note about the verdict, not the lender's words. */
  note?: string | null;
}

/** Put a cleared or waived condition back to open. The old verdict stays in the history. */
export interface ReopenInput extends ConcurrentWrite {
  reason: string;
}

/** Set or clear the manual owner override (A2). */
export interface OwnerInput extends ConcurrentWrite {
  /** `null` means "back to the hint", not "nobody". */
  owner: OwnerHint | null;
}

/**
 * One write applied to many conditions, refusing the rows that may not have it.
 *
 * THE FIELDS OF ALL THREE ACTIONS LIVE HERE and the server validates the ones the chosen action
 * needs, mirroring `BulkRequest`. Three separate types would be tidier and would push onto the client
 * a split the UI does not want: one dialog sends one dialog's worth of fields for a row set it has no
 * reason to divide.
 */
export interface BulkInput extends ConcurrentWrite {
  condition_ids: string[];
  action: BulkAction;
  to?: ConditionPrepStatus | null;
  waiting_on?: OwnerHint | null;
  reason?: string | null;
  note?: string | null;
  sent_at?: string | null;
  status?: ConditionLenderStatus | null;
  source_kind?: ManualVerdictSourceKind | null;
  source_date?: string | null;
  round_id?: string | null;
  owner?: OwnerHint | null;
}

/** One row a bulk write would not touch, and the sentence to show for it. */
export interface BulkRefusal {
  condition_id: string;
  code: ConditionRefusalCode;
  message: string;
}

/**
 * What a bulk write did — "4 marked cleared · 1 skipped: information only".
 *
 * IT ARRIVES AS 200 WITH REFUSALS AS DATA, not as a 409. Partial success is the expected outcome, so
 * a 409 would throw away the rows that worked, and a body listing only successes would leave a
 * processor to work out for themselves which row did not move.
 */
export interface BulkResult {
  applied: string[];
  refused: BulkRefusal[];
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

// --- Stage 3: the reading (LP-919) ------------------------------------------------------------- //

/** Who acts on one item (backend `Performer`, `app/models/condition_vocabulary.py`). */
export type Performer =
  | "borrower"
  | "lo"
  | "processor"
  | "lender"
  | "title"
  | "attorney"
  | "insurance"
  | "hoa"
  | "employer"
  | "appraiser"
  | "other_party";

/**
 * The next step for an item or a condition (backend `PlanOption`). "Lender is doing it" and
 * "Information only" are options here, never statuses (plan §4a change 12).
 */
export type PlanOption =
  | "ask_borrower"
  | "ask_third_party"
  | "i_will_do_it"
  | "already_in_file"
  | "ask_underwriter"
  | "push_back"
  | "lender_doing_it"
  | "information_only";

/** What code checks on evidence (backend `EvidenceCheck`; LP-923 runs them). */
export type EvidenceCheck =
  | "all_pages"
  | "right_account"
  | "right_borrower"
  | "right_period"
  | "inside_lender_dates"
  | "amount_matches"
  | "covers_required_funds"
  | "signed_and_dated"
  | "mortgagee_clause_matches"
  | "effective_by_closing"
  | "inside_voe_window"
  | "not_expired";

/** Below the confidence bar, or read without the AI, the reading needs her before anything is drafted. */
export type ConditionReadingStatus = "unread" | "ready" | "needs_confirmation" | "confirmed";

export type ConditionReadingSource = "ai" | "library" | "confirmed";

export interface ReadingSpecifics {
  amounts: string[];
  account_bank: string | null;
  account_last4: string | null;
  /** `2026-08`: the statement month the item needs. */
  month: string | null;
  names: string[];
}

export interface ReadingItem {
  key: string;
  name: string;
  acceptable: string;
  performers: Performer[];
  option: PlanOption;
  documents: string[];
  checks: EvidenceCheck[];
  specifics: ReadingSpecifics;
}

export interface ConditionReading {
  source: ConditionReadingSource;
  type_id: string | null;
  /** The short label the plan row shows (S3-02). */
  summary: string;
  /** The "How we read it" sentence (S3-01), or null when the model gave none the checks accepted. */
  explanation: string | null;
  information_only: boolean;
  lender_doing_it: boolean;
  /** What the underwriter's dated note means, in plain words ("Not in Upload" → asked again). */
  note_meaning: string | null;
  items: ReadingItem[];
  /** Figures CODE computed from the lender's words. Decimal strings; never the model's. */
  figures: { shortfall: { required: string; verified: string; amount: string } | null };
  /** Two dates code read from the letter: the condition cannot apply (6178). ISO dates. */
  push_back: { must_not_close_before: string; policy_starts: string } | null;
  confidence: number | null;
}

export interface LibraryType {
  id: string;
  name: string;
  /** `AS-04 Earnest money`. */
  label: string;
  /** `Fannie Mae B3-4.3-09`, or "Lender requirement". */
  rule_label: string;
  rule_note: string | null;
}

// --- Stage 3: the plan (LP-920) ---------------------------------------------------------------- //

export type ConditionItemStatus = "open" | "requested" | "received" | "done" | "not_needed";

export type ConditionItemOrigin = "reading" | "manual" | "carried";

export interface ConditionItem {
  id: string;
  key: string;
  name: string;
  acceptable: string;
  performer: Performer;
  performers: Performer[];
  option: PlanOption;
  status: ConditionItemStatus;
  origin: ConditionItemOrigin;
  need_id: string | null;
  need_title: string | null;
  /** Other conditions asking through the same need ("Same statement as 7086 and 6132"). */
  shared_with_codes: string[];
  document_id: string | null;
  document_name: string | null;
  document_page: number | null;
  waits_on_condition_id: string | null;
  waits_on_code: string | null;
  due_date: string | null;
  specifics: ReadingSpecifics;
  /** LP-921 — what she does, from the library ("upload the invoice"); null on an ask or her own item. */
  task: string | null;
}

export interface RoundPlanDraft {
  recipient: string;
  label: string;
  codes: string[];
}

/** S3-02's heading and pills for one round's plan. */
export interface RoundPlan {
  round_id: string;
  round_number: number | null;
  round_date: string;
  planned: number;
  ready_at: string | null;
  confirmed_at: string | null;
  nothing_sent: boolean;
  drafts: RoundPlanDraft[];
  your_tasks: number;
  already_in_file: number;
  push_back: number;
  lender_doing_it: number;
  needs_confirmation: number;
  blocking_codes: string[];
}
