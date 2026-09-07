/**
 * The reconciliation ledger's data layer (LP-UI-018).
 *
 * One read, `GET /loan-files/{id}/reconciliation`. The rows are computed on
 * every request from data that already exists — there is nothing to invalidate
 * and nothing to re-run, which is why this file has no mutation.
 */
import { apiClient } from "@/lib/api/client";
import { LOAN_FILES_PATH } from "@/lib/api/loan-files";
import type { ReconciliationRow } from "@/lib/types/reconciliation";
import { useQuery } from "@tanstack/react-query";
import { isAxiosError } from "axios";

export async function fetchReconciliation(identifier: string): Promise<ReconciliationRow[]> {
  const response = await apiClient.get<ReconciliationRow[]>(
    `${LOAN_FILES_PATH}/${identifier}/reconciliation`,
  );
  return response.data;
}

export function reconciliationQueryKey(identifier: string) {
  return ["loan-file", identifier, "reconciliation"] as const;
}

export function useReconciliation(identifier: string) {
  return useQuery({
    queryKey: reconciliationQueryKey(identifier),
    queryFn: () => fetchReconciliation(identifier),
    // A 404 here is a file this company cannot see; retrying cannot change that.
    retry: (failureCount, error) =>
      !(isAxiosError(error) && error.response?.status === 404) && failureCount < 1,
  });
}
