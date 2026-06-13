/**
 * Stated-financials types (LP-55), mirroring the backend `StatedFinancialsResponse`
 * (the read-only view of the data MISMO import populated). Decimals serialize as
 * strings; dates/timestamps as ISO strings. SSN is masked.
 */
import type { LoanFileDetail } from "@/lib/types/loan-file";

export interface StatedIncomeItem {
  monthly_amount: string | null;
  income_type: string | null;
  employment_income: boolean | null;
}

export interface StatedLiability {
  liability_type: string | null;
  monthly_payment: string | null;
  unpaid_balance: string | null;
  holder_name: string | null;
}

export interface StatedAsset {
  asset_type: string | null;
  value: string | null;
  holder_name: string | null;
}

export interface StatedBorrower {
  id: string;
  full_name: string;
  masked_ssn: string | null;
  date_of_birth: string | null;
  marital_status: string | null;
  dependent_count: number | null;
  citizenship: string | null;
  is_primary: boolean;
  declarations: Record<string, string> | null;
  income_items: StatedIncomeItem[];
  employers: string[];
}

export interface MismoImportSummary {
  source_format: string;
  status: string;
  warnings: string[];
  imported_at: string;
}

export interface StatedLoanTerms {
  note_amount: string | null;
  note_rate_percent: string | null;
  lien_priority: string | null;
  amortization_type: string | null;
  amortization_months: number | null;
  application_received_date: string | null;
}

export interface StatedPropertyExtras {
  valuation_amount: string | null;
  attachment_type: string | null;
  construction_method: string | null;
  financed_unit_count: number | null;
}

export interface StatedFinancials {
  borrowers: StatedBorrower[];
  liabilities: StatedLiability[];
  assets: StatedAsset[];
  loan_terms: StatedLoanTerms;
  property_extras: StatedPropertyExtras | null;
  mismo_import: MismoImportSummary | null;
}

/** The LP-54 import response: the created file + parse warnings. */
export interface MismoImportResult {
  loan_file: LoanFileDetail;
  warnings: string[];
}
