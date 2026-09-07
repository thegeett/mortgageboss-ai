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
export type RefinanceType = "rate_term" | "cash_out";

/** Why this file wants a processor's attention (LP-UI-013, derived server-side). */
export type AttentionTone = "blocking" | "attention" | "verified" | "neutral";

export interface FileAttention {
  tone: AttentionTone;
  label: string;
  needs_total: number;
  needs_satisfied: number;
}

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
  /** Optional: a version-skewed backend may not send it. */
  attention?: FileAttention | null;
}

export interface PaginatedLoanFiles {
  items: LoanFileSummary[];
  total: number;
  page: number;
  page_size: number;
}

// --- Single-file detail (LP-33), mirroring the backend `LoanFileDetail` ------ //

/** Safe borrower view — `masked_ssn` only, never the raw SSN. */
export interface BorrowerPublic {
  id: string;
  first_name: string;
  last_name: string;
  masked_ssn: string | null;
  is_primary: boolean;
  borrower_position: number;
}

export type PropertyType =
  | "single_family"
  | "condo"
  | "townhouse"
  | "multi_family"
  | "manufactured"
  | "other";
export type OccupancyType = "primary_residence" | "second_home" | "investment";

export interface PropertyPublic {
  id: string;
  address_line: string | null;
  address_line_2: string | null;
  city: string | null;
  state: string | null;
  postal_code: string | null;
  property_type: PropertyType | null;
  occupancy_type: OccupancyType | null;
  estimated_value: string | null;
  purchase_price: string | null;
  /** The MISMO valuation amount (LP-90). The LTV's appraised basis reads this first
   * (`valuation_amount || estimated_value`), so it's exposed + editable on the Overview. */
  valuation_amount: string | null;
}

/** The state of LP-69's async AI needs reasoning (LP-71.5). `null` = not triggered. */
export type AiNeedsStatus = "pending" | "completed" | "failed";

export interface LoanFileDetail extends LoanFileSummary {
  loan_officer_name: string | null;
  loan_officer_email: string | null;
  /** The refinance cash-out kind (LP-99). Null for a purchase, or for a refi whose kind the
   * MISMO import couldn't determine — the Overview surfaces that so it's corrected (the LTV
   * limit depends on it; cash-out is stricter). Editable only when the purpose is refinance. */
  refinance_type: RefinanceType | null;
  ai_needs_status: AiNeedsStatus | null;
  borrowers: BorrowerPublic[];
  property: PropertyPublic | null;
}
