/**
 * DTI calculator types (LP-76) — the transparent, itemized calculation.
 *
 * Mirrors the backend `DtiCalculation` schema. All money + ratio values arrive as
 * decimal strings (Pydantic serialises Decimal as a string); ratios are null when
 * income is zero (undefined).
 */

export interface DtiLineItem {
  key: string;
  label: string;
  auto_amount: string | null;
  override_amount: string | null;
  amount: string;
  source: string;
  overridden: boolean;
  /** LP-375: a REQUIRED input (taxes/insurance) that could not be derived and was not overridden — its
   * `amount` of 0 is a fail-closed placeholder, NOT an extracted $0.00 (absent≠0). Render as "Unknown". */
  unknown?: boolean;
}

export type DtiLimitStatus = "pass" | "over" | "unknown";

export interface DtiLimit {
  back_end_max: string | null;
  source: string; // "program_default" | "overlay" | "unknown"
  lender_slug: string | null;
  rule_id: string | null;
  status: DtiLimitStatus;
}

export interface DtiFindingsStatus {
  unresolved: boolean;
  open_in_scope_count: number;
}

export interface DtiCalculation {
  front_end_dti: string | null;
  back_end_dti: string | null;
  /** LP-375: fail-closed — a REQUIRED housing input (taxes/insurance) is unknown, so the ratios are
   * nulled (never a confident number on a fabricated 0) and `gate_reason` names the unknown input(s). */
  gated?: boolean;
  gate_reason?: string | null;
  gross_monthly_income: string;
  housing_payment: string;
  monthly_debts: string;
  total_monthly_obligations: string;
  income_items: DtiLineItem[];
  housing_items: DtiLineItem[];
  debt_items: DtiLineItem[];
  front_end_formula: string;
  back_end_formula: string;
  program: string | null;
  limit: DtiLimit;
  findings: DtiFindingsStatus;
}

export interface DtiOverrideInput {
  amount: string;
  note?: string | null;
}
