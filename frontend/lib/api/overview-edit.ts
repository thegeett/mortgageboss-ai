/**
 * Subject Property + Loan edit data layer (LP-80.5).
 *
 * PATCH the file's loan core (loan terms, program, purpose, target lender) and the
 * subject property, reusing the existing backend endpoints. Each edit changes the
 * verification baseline, so every mutation invalidates the loan-file + stated-
 * financials reads AND the DTI / LTV / verification queries — an open calculator or
 * verification panel refreshes, and the "out of date — re-run" prompt appears.
 */
import { apiClient } from "@/lib/api/client";
import { type QueryClient, useMutation, useQueryClient } from "@tanstack/react-query";

const API_V1 = "/api/v1";
type Body = Record<string, unknown>;

/**
 * Every baseline edit refreshes the file, the stated read, and the coupled engines.
 *
 * Invalidate by key **prefix** (not `[key, fileId]`): these cards pass the file's
 * UUID, but the same queries are cached under the route's display_id — a per-id key
 * would miss them and the view would stay stale until a manual refresh. A prefix
 * match invalidates the query whichever identifier variant keyed it.
 */
function invalidateBaseline(queryClient: QueryClient) {
  for (const key of ["loan-file", "stated-financials", "dti", "ltv", "verification"]) {
    void queryClient.invalidateQueries({ queryKey: [key] });
  }
}

/** PATCH the loan file core (loan terms, program, purpose, target lender). */
export function useUpdateLoanFile(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Body) => apiClient.patch(`${API_V1}/loan-files/${fileId}`, body),
    onSuccess: (_data, body) => {
      invalidateBaseline(queryClient);
      if ("lender_id" in body) {
        // LP-949 review — THE CONDITIONS TAB SENDS HER HERE TO SET THE LENDER, and the lender types
        // the file's conditions. Without this, the banner kept saying "This file has no lender" for
        // up to a minute (the default staleTime) after she set it. By prefix, as above.
        for (const key of [
          "condition-file-lender",
          "conditions",
          "conditions-summary",
          "condition-rounds",
          "condition-round-plan",
          // LP-952 review — the lender queues a reading of the unread conditions.
          "condition-reading-state",
        ]) {
          void queryClient.invalidateQueries({ queryKey: [key] });
        }
      }
    },
  });
}

/** PATCH the subject property (404 if the file has none — use create first). */
export function useUpdateProperty(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Body) => apiClient.patch(`${API_V1}/loan-files/${fileId}/property`, body),
    onSuccess: () => invalidateBaseline(queryClient),
  });
}

/** Attach an (empty) subject property so it can then be edited (singleton; 409 if one exists). */
export function useCreateProperty(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Body = {}) =>
      apiClient.post(`${API_V1}/loan-files/${fileId}/property`, body),
    onSuccess: () => invalidateBaseline(queryClient),
  });
}
