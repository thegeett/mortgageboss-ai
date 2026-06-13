/** Shared human labels for loan program/purpose (LP-34), so "FHA" reads the same
 * everywhere (file header, overview cards, …). One source, no per-surface maps. */
import type { LoanProgram, LoanPurpose } from "@/lib/types/loan-file";

export const LOAN_PROGRAM_LABELS: Record<LoanProgram, string> = {
  conventional: "Conventional",
  fha: "FHA",
};

export const LOAN_PURPOSE_LABELS: Record<LoanPurpose, string> = {
  purchase: "Purchase",
  refinance: "Refinance",
};

export function programLabel(program: LoanProgram | null): string {
  return program ? LOAN_PROGRAM_LABELS[program] : "—";
}

export function purposeLabel(purpose: LoanPurpose | null): string {
  return purpose ? LOAN_PURPOSE_LABELS[purpose] : "—";
}
