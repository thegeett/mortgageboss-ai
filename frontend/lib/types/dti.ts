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
  /** LP-568: shown in the breakdown but NOT summed into the totals — an obligation that does not
   * survive closing (the mortgage a refinance pays off, a departing residence, a debt cleared to
   * qualify). Distinct from `unknown`: the amount is real and known, it simply stops existing.
   * Render struck-through WITH the reason — never hide the row, or the processor cannot tell a
   * debt was considered at all. */
  excluded?: boolean;
  excluded_reason?: string | null;
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
  unverified_inputs?: UnverifiedInput[];
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

/** bug-001: a figure the FILE STATES for a gated input, which is not acceptable verification.
 *
 * A real file gated on "Property taxes is unknown" while two of its documents stated the annual tax
 * outright ($5,579). Both were automated valuations, so gating is right — an estimator's figure must
 * not silently set a DTI. But telling a processor it is missing sends them to find it twice.
 *
 * `field_key` + `monthly_amount` are exactly a `DtiOverrideInput`, so the card can offer it as ONE
 * CLICK — which records who accepted it and why, rather than the calculator assuming it quietly. */
export interface UnverifiedInput {
  field_key: string;
  label: string;
  monthly_amount: string;
  annual_amount: string;
  source_label: string;
  sentence: string;
}

export interface DtiOverrideInput {
  amount: string;
  note?: string | null;
}
