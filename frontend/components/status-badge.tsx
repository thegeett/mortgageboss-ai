import { LOAN_FILE_STATUS, resolveStatus } from "@/lib/status";
import type { LoanFileStatus } from "@/lib/types/loan-file";
import { StatusToken } from "./status-token";

/**
 * A loan-file status pill. One vocabulary, one rendering: colour + glyph + word
 * (LP-UI-005). `resolveStatus` means a status the backend grew shows up visibly
 * instead of crashing the row.
 */
export function StatusBadge({ status }: { status: LoanFileStatus }) {
  return <StatusToken meta={resolveStatus(LOAN_FILE_STATUS, status)} variant="chip" />;
}
