/**
 * Dashboard filter-pill groupings for loan-file status (LP-31).
 *
 * Status PRESENTATION moved to `lib/status.ts` in LP-UI-005 — one tone
 * vocabulary for every domain, rendered through `<StatusToken>`. What stays here
 * is the grouping logic, which is a dashboard concern rather than a visual one.
 *
 * Pill groupings (ADR): All = no filter; Active = the in-progress statuses
 * (everything not action-needed and not completed — incl. CLEAR_TO_CLOSE, so no
 * status is orphaned); Action needed = IN_CONDITIONS (a V1 proxy — later
 * includes outstanding blocking needs); Completed = CLOSED + WITHDRAWN. The four
 * non-"All" groups are disjoint and together cover all eight statuses.
 */
import { LOAN_FILE_STATUS, resolveStatus } from "@/lib/status";
import type { LoanFileStatus } from "@/lib/types/loan-file";

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
  return resolveStatus(LOAN_FILE_STATUS, status).label;
}
