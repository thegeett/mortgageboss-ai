/** Needs-list item (LP-34), mirroring the backend `NeedsItemPublic`. The needs
 * list is provisional template data (LP-30, pending domain refinement). */

export type NeedsItemStatus = "outstanding" | "requested" | "received" | "waived";
export type NeedsItemPriority = "blocking" | "standard" | "low";
export type NeedsItemOrigin = "manual" | "finding" | "condition" | "template";
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
  category: DocumentCategory | null;
  needs_type: string | null;
  status: NeedsItemStatus;
  priority: NeedsItemPriority;
  origin: NeedsItemOrigin;
  borrower_id: string | null;
  satisfied_by_document_id: string | null;
  created_at: string;
}
