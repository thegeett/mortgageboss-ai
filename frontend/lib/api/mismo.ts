/**
 * MISMO import data layer (LP-55): the upload mutation (calls the LP-54 endpoint)
 * and the stated-financials read.
 *
 * Import is **inline** server-side (fast, no Celery), so this is a normal
 * mutation whose result *is* the created file — the caller navigates straight to
 * it (import-directly). The stated-financials read backs the "Application Data
 * (Stated)" display on the opened file.
 */
import { apiClient } from "@/lib/api/client";
import { dtiQueryKey } from "@/lib/api/dti";
import { ltvQueryKey } from "@/lib/api/ltv";
import { verificationQueryKey } from "@/lib/api/verification";
import type { MismoImportResult, StatedFinancials } from "@/lib/types/stated-financials";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";

const API_V1 = "/api/v1";

/** Upload a MISMO file (XML or HTML-wrapped) → the created, populated loan file. */
export async function importMismo(file: File): Promise<MismoImportResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await apiClient.post<MismoImportResult>(`${API_V1}/loan-files/import-mismo`, form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return res.data;
}

/** Mutation for the MISMO upload (the result is the created file + warnings). */
export function useImportMismo() {
  return useMutation({ mutationFn: (file: File) => importMismo(file) });
}

// --- Stated financials (read; LP-55) ---------------------------------------- //

export const statedFinancialsQueryKey = (identifier: string) =>
  ["stated-financials", identifier] as const;

export async function fetchStatedFinancials(identifier: string): Promise<StatedFinancials> {
  const res = await apiClient.get<StatedFinancials>(
    `${API_V1}/loan-files/${identifier}/stated-financials`,
  );
  return res.data;
}

/** A 404 (missing or out-of-company) won't change on retry — surface it. */
function noRetryOn404(failureCount: number, error: unknown): boolean {
  return !(isAxiosError(error) && error.response?.status === 404) && failureCount < 1;
}

export function useStatedFinancials(identifier: string) {
  return useQuery({
    queryKey: statedFinancialsQueryKey(identifier),
    queryFn: () => fetchStatedFinancials(identifier),
    enabled: Boolean(identifier),
    retry: noRetryOn404,
  });
}

// --- Editing the imported data (LP-56) -------------------------------------- //

/** The flat resource segment for a stated row's PATCH/DELETE. */
export type StatedKind =
  | "stated-liabilities"
  | "stated-assets"
  | "stated-income-items"
  | "stated-employers";

type Body = Record<string, unknown>;

async function patchStatedRow(kind: StatedKind, id: string, body: Body): Promise<void> {
  await apiClient.patch(`${API_V1}/${kind}/${id}`, body);
}
async function deleteStatedRow(kind: StatedKind, id: string): Promise<void> {
  await apiClient.delete(`${API_V1}/${kind}/${id}`);
}
async function addFileRow(
  fileId: string,
  kind: "stated-liabilities" | "stated-assets",
  body: Body,
) {
  await apiClient.post(`${API_V1}/loan-files/${fileId}/${kind}`, body);
}
async function addBorrowerRow(
  fileId: string,
  borrowerId: string,
  kind: "stated-income" | "stated-employers",
  body: Body,
) {
  await apiClient.post(`${API_V1}/loan-files/${fileId}/borrowers/${borrowerId}/${kind}`, body);
}
async function patchLoanTerms(fileId: string, body: Body): Promise<void> {
  await apiClient.patch(`${API_V1}/loan-files/${fileId}`, body);
}

/**
 * All the stated-data edit mutations for a file (LP-56), each invalidating the
 * stated-financials read (and the loan-file read for loan terms) so the display
 * updates after a save/add/remove.
 */
export function useStatedFinancialsEdit(fileId: string) {
  const queryClient = useQueryClient();
  // A stated-data edit changes the verification baseline + the DTI/LTV inputs, so
  // refresh those too (LP-80.5) — an open calculator/verification panel updates.
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: statedFinancialsQueryKey(fileId) });
    void queryClient.invalidateQueries({ queryKey: ["loan-file", fileId] });
    void queryClient.invalidateQueries({ queryKey: dtiQueryKey(fileId) });
    void queryClient.invalidateQueries({ queryKey: ltvQueryKey(fileId) });
    void queryClient.invalidateQueries({ queryKey: verificationQueryKey(fileId) });
  };

  return {
    updateRow: useMutation({
      mutationFn: ({ kind, id, body }: { kind: StatedKind; id: string; body: Body }) =>
        patchStatedRow(kind, id, body),
      onSuccess: invalidate,
    }),
    deleteRow: useMutation({
      mutationFn: ({ kind, id }: { kind: StatedKind; id: string }) => deleteStatedRow(kind, id),
      onSuccess: invalidate,
    }),
    addLiability: useMutation({
      mutationFn: (body: Body) => addFileRow(fileId, "stated-liabilities", body),
      onSuccess: invalidate,
    }),
    addAsset: useMutation({
      mutationFn: (body: Body) => addFileRow(fileId, "stated-assets", body),
      onSuccess: invalidate,
    }),
    addIncome: useMutation({
      mutationFn: ({ borrowerId, body }: { borrowerId: string; body: Body }) =>
        addBorrowerRow(fileId, borrowerId, "stated-income", body),
      onSuccess: invalidate,
    }),
    addEmployer: useMutation({
      mutationFn: ({ borrowerId, body }: { borrowerId: string; body: Body }) =>
        addBorrowerRow(fileId, borrowerId, "stated-employers", body),
      onSuccess: invalidate,
    }),
    updateLoanTerms: useMutation({
      mutationFn: (body: Body) => patchLoanTerms(fileId, body),
      onSuccess: invalidate,
    }),
  };
}
