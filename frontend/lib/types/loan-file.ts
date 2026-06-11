/**
 * Loan-file list types (LP-31), mirroring the backend `LoanFileSummary` /
 * `PaginatedLoanFiles`. `loan_amount` is a string (Pydantic serialises Decimal
 * as a string); timestamps are ISO strings.
 */

export type LoanFileStatus =
  | "draft"
  | "in_processing"
  | "ready_to_submit"
  | "submitted"
  | "in_conditions"
  | "clear_to_close"
  | "closed"
  | "withdrawn";

export type LoanProgram = "conventional" | "fha";
export type LoanPurpose = "purchase" | "refinance";

export interface LoanFileSummary {
  id: string;
  display_id: string;
  status: LoanFileStatus;
  loan_program: LoanProgram | null;
  loan_purpose: LoanPurpose | null;
  loan_amount: string | null;
  lender_id: string | null;
  lender_name: string | null;
  property_address: string | null;
  primary_borrower_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface PaginatedLoanFiles {
  items: LoanFileSummary[];
  total: number;
  page: number;
  page_size: number;
}
