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

export interface CalcFindings {
  unresolved: boolean;
  open_in_scope_count: number;
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
