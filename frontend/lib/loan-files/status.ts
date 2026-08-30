/**
 * Loan-file status label lookup.
 *
 * Status PRESENTATION moved to `lib/status.ts` in LP-UI-005. The dashboard's
 * four filter-pill groupings lived here until LP-UI-014 replaced them with saved
 * views; their status sets are recorded in docs/tickets/LP-UI-014.md as the
 * defaults worth seeding.
 *
 * Pill groupings (ADR): All = no filter; Active = the in-progress statuses
 * (everything not action-needed and not completed — incl. CLEAR_TO_CLOSE, so no
 * status is orphaned); Action needed = IN_CONDITIONS (a V1 proxy — later
 * includes outstanding blocking needs); Completed = CLOSED + WITHDRAWN. The four
 * non-"All" groups are disjoint and together cover all eight statuses.
 */
import { LOAN_FILE_STATUS, resolveStatus } from "@/lib/status";
import type { LoanFileStatus } from "@/lib/types/loan-file";

export function statusLabel(status: LoanFileStatus): string {
  return resolveStatus(LOAN_FILE_STATUS, status).label;
}
