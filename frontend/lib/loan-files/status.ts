/**
 * Single source of truth for loan-file status presentation and the dashboard
 * filter-pill groupings (LP-31).
 *
 * Status → badge colours use the LP-5 semantic tokens (info/warning/success +
 * neutral grays), kept calm: attention statuses (in-conditions) read amber,
 * good outcomes (clear-to-close) read green, terminal/idle read neutral.
 *
 * Pill groupings (ADR): All = no filter; Active = the in-progress statuses
 * (everything not action-needed and not completed — incl. CLEAR_TO_CLOSE, so no
 * status is orphaned); Action needed = IN_CONDITIONS (a V1 proxy — later
 * includes outstanding blocking needs); Completed = CLOSED + WITHDRAWN. The four
 * non-"All" groups are disjoint and together cover all eight statuses.
 */
import type { LoanFileStatus } from "@/lib/types/loan-file";

export interface StatusMeta {
  label: string;
  /** Badge classes (background/text/border) built from the design tokens. */
  className: string;
}

export const STATUS_META: Record<LoanFileStatus, StatusMeta> = {
  draft: { label: "Draft", className: "bg-gray-100 text-gray-600 border-gray-200" },
  in_processing: { label: "In processing", className: "bg-info/10 text-info border-info/20" },
  ready_to_submit: {
    label: "Ready to submit",
    className: "bg-primary/10 text-primary border-primary/20",
  },
  submitted: { label: "Submitted", className: "bg-primary/10 text-primary border-primary/20" },
  in_conditions: {
    label: "In conditions",
    className: "bg-warning/10 text-warning border-warning/20",
  },
  clear_to_close: {
    label: "Clear to close",
    className: "bg-success/10 text-success border-success/20",
  },
  closed: { label: "Closed", className: "bg-gray-100 text-gray-500 border-gray-200" },
  withdrawn: { label: "Withdrawn", className: "bg-gray-50 text-gray-400 border-gray-200" },
};

export type FilterKey = "all" | "active" | "action_needed" | "completed";

export interface FilterPill {
  key: FilterKey;
  label: string;
  /** The statuses this pill filters to; empty = no status filter (All). */
  statuses: LoanFileStatus[];
}

export const FILTER_PILLS: FilterPill[] = [
  { key: "all", label: "All", statuses: [] },
  {
    key: "active",
    label: "Active",
    statuses: ["draft", "in_processing", "ready_to_submit", "submitted", "clear_to_close"],
  },
  { key: "action_needed", label: "Action needed", statuses: ["in_conditions"] },
  { key: "completed", label: "Completed", statuses: ["closed", "withdrawn"] },
];

export function statusesForFilter(key: FilterKey): LoanFileStatus[] {
  return FILTER_PILLS.find((pill) => pill.key === key)?.statuses ?? [];
}

export function statusLabel(status: LoanFileStatus): string {
  return STATUS_META[status].label;
}
