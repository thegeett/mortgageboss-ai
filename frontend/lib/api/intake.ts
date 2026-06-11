/**
 * Intake submit orchestration (LP-32) — Option A: sequential, file-first.
 *
 * 1. POST /loan-files (the gate — throws on failure so the caller stays on the
 *    form and can retry).
 * 2. POST /loan-files/{id}/borrowers (primary borrower) — best-effort.
 * 3. POST /loan-files/{id}/property — best-effort.
 *
 * The file is the gate: once it exists (a usable DRAFT), a failed borrower/
 * property step is reported as a non-fatal `warning`, not an error — there is no
 * client-side rollback (ADR). The SSN passes through here once to the borrower
 * endpoint (encrypted at rest) and is never logged.
 */
import { apiClient } from "@/lib/api/client";
import { LOAN_FILES_PATH } from "@/lib/api/loan-files";

export interface CreatedLoanFile {
  id: string;
  display_id: string;
}

export interface LoanFilePayload {
  lender_id?: string;
  loan_program?: string;
  loan_purpose?: string;
  loan_officer_name?: string;
  loan_officer_email?: string;
}

export interface BorrowerPayload {
  first_name: string;
  last_name: string;
  middle_name?: string;
  ssn?: string;
  date_of_birth?: string;
  email?: string;
  phone?: string;
  marital_status?: string;
}

export interface PropertyPayload {
  address_line?: string;
  address_line_2?: string;
  city?: string;
  state?: string;
  postal_code?: string;
  property_type?: string;
  occupancy_type?: string;
  estimated_value?: string;
  purchase_price?: string;
}

export async function createLoanFile(payload: LoanFilePayload): Promise<CreatedLoanFile> {
  const response = await apiClient.post<CreatedLoanFile>(LOAN_FILES_PATH, payload);
  return response.data;
}

export async function addPrimaryBorrower(fileId: string, payload: BorrowerPayload): Promise<void> {
  await apiClient.post(`${LOAN_FILES_PATH}/${fileId}/borrowers`, {
    ...payload,
    is_primary: true,
    borrower_position: 1,
  });
}

export async function setProperty(fileId: string, payload: PropertyPayload): Promise<void> {
  await apiClient.post(`${LOAN_FILES_PATH}/${fileId}/property`, payload);
}

/** Which best-effort enrichment step failed (the file itself was still created). */
export type IntakeWarning = "borrower" | "property";

export interface IntakeResult {
  file: CreatedLoanFile;
  warnings: IntakeWarning[];
}

/**
 * Run the Option-A sequence. Throws if file creation fails (the caller keeps the
 * form open); otherwise resolves with the created file and any best-effort steps
 * that failed (so the caller can show a non-blocking warning).
 */
export async function submitIntake(input: {
  loanFile: LoanFilePayload;
  borrower: BorrowerPayload | null;
  property: PropertyPayload | null;
}): Promise<IntakeResult> {
  const file = await createLoanFile(input.loanFile); // the gate — may throw
  const warnings: IntakeWarning[] = [];

  if (input.borrower) {
    try {
      await addPrimaryBorrower(file.id, input.borrower);
    } catch {
      warnings.push("borrower");
    }
  }
  if (input.property) {
    try {
      await setProperty(file.id, input.property);
    } catch {
      warnings.push("property");
    }
  }

  return { file, warnings };
}
