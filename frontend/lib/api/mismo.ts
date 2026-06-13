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
import type { MismoImportResult, StatedFinancials } from "@/lib/types/stated-financials";
import { useMutation, useQuery } from "@tanstack/react-query";
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
