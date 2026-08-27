/** Needs-list item, mirroring the backend `NeedsItemPublic` (LP-68/69/70).
 *
 * The needs list is the self-maintaining checklist — what the file needs, WHY
 * (the AI reasoning, LP-69), and what's satisfied. A need carries two orthogonal
 * lifecycles: `status` (the arrival spine — did the document show up?) and
 * `disposition` (the human-confirmation spine — the AI proposes, the processor
 * disposes). `origin` records where the need came from. */

export type NeedsItemStatus =
  | "pending" // needs this doc; not yet arrived (the default — chase it)
  | "requested" // asked of the borrower; awaiting arrival
  | "received" // a matching doc arrived, not yet verified (in flight)
  | "verified" // the doc passed — satisfied (done)
  | "rejected" // a doc arrived but failed; still open, with a reason (needs attention)
  | "waived"; // the processor set it aside, with a reason

export type NeedsItemDisposition = "proposed" | "confirmed" | "waived" | "dismissed";

export type NeedsItemOrigin =
  | "manual" // a processor-added need
  | "finding" // from a verification finding (Phase 3)
  | "condition" // from a lender condition (Phase 4.5)
  | "template" // from a file-creation template
  | "floor" // the deterministic floor, from the stated MISMO data (LP-68)
  | "suggestion" // from an LP-67 finding-implication
  | "ai_reasoning"; // a holistic AI proposal (LP-69)

export type NeedsItemPriority = "blocking" | "standard" | "low";

export type DocumentCategory =
  | "assets"
  | "borrower_info"
  | "credit"
  | "disclosures"
  | "income_employment"
  | "property"
  | "misc"
  | "custom";

export interface NeedsItemPublic {
  id: string;
  title: string;
  description: string | null;
  category: DocumentCategory | null;
  needs_type: string | null;
  status: NeedsItemStatus;
  priority: NeedsItemPriority;
  origin: NeedsItemOrigin;
  disposition: NeedsItemDisposition;
  /** The "why" — the AI/suggestion reasoning (LP-67/69). Explainability made visible. */
  reasoning: string | null;
  /** Why a need was rejected (a doc failed) or waived. */
  reason: string | null;
  borrower_id: string | null;
  satisfied_by_document_id: string | null;
  satisfied_by_document_filename: string | null;
  satisfied_at: string | null;
  created_at: string;
  /** LP-108: true when the need is GRADED — a matched document is "attached, confirm coverage"
   * (status `received`), not auto-verified, because one document can't prove the full requirement
   * (all accounts/months/years). Drives the honest note + the "Confirm coverage" action. */
  requires_coverage_confirmation: boolean;
  /** LP-109 (derive-on-read): ALL completed documents matching this need's criteria, so the
   * processor confirms coverage against the full evidence set (not just the single trigger doc).
   * Intentionally coarse for umbrella needs; empty for simple-presence needs. */
  matching_documents: MatchedDocument[];
  /** LP-110: the SOURCE — the specific data that TRIGGERED the need, honestly attributed by origin,
   * so the reasoning is FALSIFIABLE (the processor can verify the AI didn't misread). Null when the
   * origin carries no structured source (e.g. a processor-added manual need). */
  source: NeedSource | null;
  /** LP-111: set when the AI FLAGGED this proposed need as a possible duplicate of another (by id) —
   * the processor confirms the merge or keeps both. Never a silent merge (the deterministic-certain
   * duplicates were already merged before this). */
  possible_duplicate_of: string | null;
  /** LP-631: set when a coverage predicate concluded the FILE ALREADY ANSWERS this need — the
   * document that appears to answer it, plus the reasoning to check it against. A flag, never a
   * close (ADR-388): the processor dismisses the need or keeps it. */
  possibly_covered_by: MatchedDocument | null;
  coverage_note: string | null;
}

/** One document matching a need (LP-109) — id (for a link) + display filename. */
export interface MatchedDocument {
  id: string;
  filename: string;
}

/** How much to trust a need's source (LP-110) — deterministic rule (certain) vs AI-identified
 * (the AI's reading — verify) vs finding (triggered by a finding on a document). */
export type NeedSourceAttribution = "deterministic" | "ai_identified" | "finding" | "manual";

/** One fact that triggered a need (LP-110) — grounds the reasoning to verifiable data. */
export interface NeedSourceFact {
  kind: string;
  label: string;
  /** A reference to the underlying record (e.g. a finding id) where one exists. */
  ref: string | null;
  /** A linkable source document (e.g. the finding's document). */
  document_id: string | null;
  document_filename: string | null;
}

/** The SOURCE of a need (LP-110) — the triggering data, honestly attributed by origin. */
export interface NeedSource {
  attribution: NeedSourceAttribution;
  facts: NeedSourceFact[];
}
