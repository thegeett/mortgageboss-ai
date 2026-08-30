/**
 * The four LP-87 calculators (MI, self-employed, reserves, max loan) — one shared
 * transparent view type, mirroring the backend `CalculatorView`. One shape → one
 * component renders all four (the LP-76/77 transparent/overrideable pattern).
 */

export type CalculatorName = "mortgage_insurance" | "self_employed" | "reserves" | "max_loan";

export interface CalcLine {
  key: string;
  label: string;
  auto_amount: string | null; // Decimal serialized as string
  override_amount: string | null;
  amount: string; // effective
  source: string;
  overridden: boolean;
  /** Who set the override and why (LP-UI-021). Null when the line is not overridden,
   *  and `override_by` alone is null for an override with no recorded actor. */
  override_by: string | null;
  override_note: string | null;
}

export interface CalcStep {
  label: string;
  value: string; // pre-formatted (money / months / percent / text)
  emphasis: boolean;
}

export interface MethodologyNote {
  starter: boolean;
  text: string;
}

/**
 * The in-scope findings split by the system that produced them (LP-UI-021).
 *
 * A single total merges three generators. LP-375 keeps the governed rule engine
 * and the legacy AI sweep structurally separate, and "91 unresolved findings"
 * was that separation collapsed into a number a processor could not reconcile
 * with anything on screen: the tabs showed 75 governed and 13 legacy, and the
 * remaining 3 appeared nowhere at all.
 *
 * `other` is counted, not inferred — a generator this split does not know about
 * gets its own number rather than inflating one of the three.
 */
export interface FindingBreakdown {
  governed: number;
  cross_source: number;
  legacy: number;
  other: number;
}

export interface CalcFindings {
  unresolved: boolean;
  open_in_scope_count: number;
  breakdown: FindingBreakdown;
}

export interface CalculatorView {
  calculator: CalculatorName;
  title: string;
  headline: string | null;
  headline_label: string;
  status: string | null;
  program: string | null;
  inputs: CalcLine[];
  steps: CalcStep[];
  formulas: string[];
  methodology: MethodologyNote;
  findings: CalcFindings;
}

export interface CalcOverrideInput {
  amount: string;
  note?: string | null;
}
