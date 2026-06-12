/**
 * Needs-list presentation helpers (LP-34): a single priority→badge mapping (like
 * `STATUS_META` for loan status), category/status labels, and the outstanding
 * count. The needs list is provisional template data (LP-30, pending refinement).
 */
import type {
  DocumentCategory,
  NeedsItemPriority,
  NeedsItemPublic,
  NeedsItemStatus,
} from "@/lib/types/needs-item";

export const PRIORITY_META: Record<NeedsItemPriority, { label: string; className: string }> = {
  blocking: {
    label: "Blocking",
    className: "bg-destructive/10 text-destructive border-destructive/20",
  },
  standard: { label: "Standard", className: "bg-gray-100 text-gray-600 border-gray-200" },
  low: { label: "Low", className: "bg-gray-50 text-gray-400 border-gray-200" },
};

export const NEEDS_STATUS_LABELS: Record<NeedsItemStatus, string> = {
  outstanding: "Outstanding",
  requested: "Requested",
  received: "Received",
  waived: "Waived",
};

const CATEGORY_LABELS: Record<DocumentCategory, string> = {
  assets: "Assets",
  borrower_info: "Borrower info",
  credit: "Credit",
  disclosures: "Disclosures",
  income_employment: "Income & employment",
  property: "Property",
  misc: "Misc",
  custom: "Custom",
};

export function categoryLabel(category: DocumentCategory | null): string {
  return category ? CATEGORY_LABELS[category] : "Uncategorized";
}

/** Items still needed — not yet received or waived. */
export function outstandingNeedsCount(needs: NeedsItemPublic[]): number {
  return needs.filter((item) => item.status !== "received" && item.status !== "waived").length;
}
