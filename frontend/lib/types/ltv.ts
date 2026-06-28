/**
 * LTV calculator types (LP-77) — the transparent, itemized calculation.
 *
 * Mirrors the backend `LtvCalculation` schema (the parallel to DTI, LP-76).
 * Money + ratio values arrive as decimal strings; ratios are null when the value
 * basis is unknown (e.g. no appraised value yet).
 */

export interface LtvLineItem {
  key: string;
  label: string;
  auto_amount: string | null;
  override_amount: string | null;
  amount: string;
  source: string;
  overridden: boolean;
}

export type LtvLimitStatus = "pass" | "over" | "unknown";

export interface LtvLimit {
  ltv_max: string | null;
  source: string; // "program_default" | "overlay" | "unknown"
  lender_slug: string | null;
  rule_id: string | null;
  purpose_basis: string; // "purchase" | "cash_out"
  status: LtvLimitStatus;
}

export interface LtvFindingsStatus {
  unresolved: boolean;
  open_in_scope_count: number;
}

export interface LtvCalculation {
  ltv: string | null;
  cltv: string | null;
  hcltv: string | null;
  value_basis: string | null;
  value_basis_label: string;
  loan_items: LtvLineItem[];
  value_items: LtvLineItem[];
  ltv_formula: string;
  cltv_formula: string;
  hcltv_formula: string;
  purpose: string; // purchase | rate_term_refinance | cash_out_refinance
  program: string | null;
  limit: LtvLimit;
  findings: LtvFindingsStatus;
}

export interface LtvOverrideInput {
  amount: string;
  note?: string | null;
}
