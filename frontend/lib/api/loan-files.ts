/**
 * Loan-file list data layer (LP-31): a typed fetch + a TanStack Query hook.
 *
 * Calls `GET /api/v1/loan-files` through the shared authenticated axios client
 * (Bearer + auto-refresh from LP-25). The query key encodes every filter so the
 * cache stays correct as page/status/search change; `keepPreviousData` keeps the
 * current page visible while the next loads (no flicker on filter/search/page).
 */
import { apiClient } from "@/lib/api/client";
import type { LoanFileStatus, PaginatedLoanFiles } from "@/lib/types/loan-file";
import { keepPreviousData, useQuery } from "@tanstack/react-query";

export const LOAN_FILES_PATH = "/api/v1/loan-files";

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
