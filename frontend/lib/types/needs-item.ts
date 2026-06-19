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
}
