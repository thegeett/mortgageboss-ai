/**
 * Loan-file list data layer (LP-31): a typed fetch + a TanStack Query hook.
 *
 * Calls `GET /api/v1/loan-files` through the shared authenticated axios client
 * (Bearer + auto-refresh from LP-25). The query key encodes every filter so the
 * cache stays correct as page/status/search change; `keepPreviousData` keeps the
 * current page visible while the next loads (no flicker on filter/search/page).
 */
import { apiClient } from "@/lib/api/client";
import type { ActivityPublic } from "@/lib/types/activity";
import type { BorrowerDetail } from "@/lib/types/borrower";
import type { LoanFileDetail, LoanFileStatus, PaginatedLoanFiles } from "@/lib/types/loan-file";
import type { NeedsItemPublic } from "@/lib/types/needs-item";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { isAxiosError } from "axios";

export const LOAN_FILES_PATH = "/api/v1/loan-files";

/** A 404 (missing or out-of-company) won't change on retry — surface it now. */
function noRetryOn404(failureCount: number, error: unknown): boolean {
  return !(isAxiosError(error) && error.response?.status === 404) && failureCount < 1;
}

export interface LoanFilesQuery {
  page?: number;
  pageSize?: number;
  statuses?: LoanFileStatus[];
  search?: string;
}

export async function fetchLoanFiles(query: LoanFilesQuery): Promise<PaginatedLoanFiles> {
  const params = new URLSearchParams();
  params.set("page", String(query.page ?? 1));
  params.set("page_size", String(query.pageSize ?? 20));
  for (const status of query.statuses ?? []) {
    params.append("status", status);
  }
  if (query.search) {
    params.set("search", query.search);
  }
  const response = await apiClient.get<PaginatedLoanFiles>(`${LOAN_FILES_PATH}?${params}`);
  return response.data;
}

/** Stable query key for a list query (filters fully encoded). */
export function loanFilesQueryKey(query: LoanFilesQuery) {
  return [
    "loan-files",
    {
      page: query.page ?? 1,
      pageSize: query.pageSize ?? 20,
      statuses: query.statuses ?? [],
      search: query.search ?? "",
    },
  ] as const;
}

export function useLoanFiles(query: LoanFilesQuery) {
  return useQuery({
    queryKey: loanFilesQueryKey(query),
    queryFn: () => fetchLoanFiles(query),
    placeholderData: keepPreviousData,
  });
}

// --- Single-file detail (LP-33) --------------------------------------------- //

/** Fetch one file by UUID or display_id. The API 404s for not-found *or*
 * out-of-company (tenant-safe — both surface the same). */
export async function fetchLoanFile(identifier: string): Promise<LoanFileDetail> {
  const response = await apiClient.get<LoanFileDetail>(`${LOAN_FILES_PATH}/${identifier}`);
  return response.data;
}

export function useLoanFile(identifier: string) {
  return useQuery({
    queryKey: ["loan-file", identifier],
    queryFn: () => fetchLoanFile(identifier),
    enabled: Boolean(identifier),
    retry: noRetryOn404,
  });
}

// --- Overview reads (LP-34): borrowers, needs, activity --------------------- //

export function useLoanFileBorrowers(identifier: string) {
  return useQuery({
    queryKey: ["loan-file-borrowers", identifier],
    queryFn: async () =>
      (await apiClient.get<BorrowerDetail[]>(`${LOAN_FILES_PATH}/${identifier}/borrowers`)).data,
    enabled: Boolean(identifier),
    retry: noRetryOn404,
  });
}

export function useLoanFileNeeds(identifier: string) {
  return useQuery({
    queryKey: ["loan-file-needs", identifier],
    queryFn: async () =>
      (await apiClient.get<NeedsItemPublic[]>(`${LOAN_FILES_PATH}/${identifier}/needs`)).data,
    enabled: Boolean(identifier),
    retry: noRetryOn404,
  });
}

export function useLoanFileActivity(identifier: string) {
  return useQuery({
    queryKey: ["loan-file-activity", identifier],
    queryFn: async () =>
      (await apiClient.get<ActivityPublic[]>(`${LOAN_FILES_PATH}/${identifier}/activity`)).data,
    enabled: Boolean(identifier),
    retry: noRetryOn404,
  });
}
