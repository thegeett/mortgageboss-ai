/**
 * LTV calculator data layer (LP-77) — mirrors the DTI data layer (LP-76).
 *
 * The override endpoints return the recomputed calculation, so a mutation primes
 * the query cache directly (`setQueryData`) — real-time recalc from one
 * round-trip. The activity feed is invalidated so the audited override appears.
 */
import { apiClient } from "@/lib/api/client";
import type { LtvCalculation, LtvOverrideInput } from "@/lib/types/ltv";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";

const API_V1 = "/api/v1";

export const ltvQueryKey = (identifier: string) => ["ltv", identifier] as const;

export async function fetchLtv(identifier: string): Promise<LtvCalculation> {
  const res = await apiClient.get<LtvCalculation>(`${API_V1}/loan-files/${identifier}/ltv`);
  return res.data;
}

/** A 404 (missing or out-of-company) won't change on retry — surface it. */
function noRetryOn404(failureCount: number, error: unknown): boolean {
  return !(isAxiosError(error) && error.response?.status === 404) && failureCount < 1;
}

export function useLtv(identifier: string) {
  return useQuery({
    queryKey: ltvQueryKey(identifier),
    queryFn: () => fetchLtv(identifier),
    enabled: Boolean(identifier),
    retry: noRetryOn404,
  });
}

export async function setLtvOverride(
  identifier: string,
  fieldKey: string,
  input: LtvOverrideInput,
): Promise<LtvCalculation> {
  const res = await apiClient.put<LtvCalculation>(
    `${API_V1}/loan-files/${identifier}/ltv/overrides/${fieldKey}`,
    input,
  );
  return res.data;
}

export async function clearLtvOverride(
  identifier: string,
  fieldKey: string,
): Promise<LtvCalculation> {
  const res = await apiClient.delete<LtvCalculation>(
    `${API_V1}/loan-files/${identifier}/ltv/overrides/${fieldKey}`,
  );
  return res.data;
}

/** Set an override → prime the cache with the recomputed result (real-time recalc). */
export function useSetLtvOverride(identifier: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ fieldKey, input }: { fieldKey: string; input: LtvOverrideInput }) =>
      setLtvOverride(identifier, fieldKey, input),
    onSuccess: (data) => {
      queryClient.setQueryData(ltvQueryKey(identifier), data);
      void queryClient.invalidateQueries({ queryKey: ["loan-file-activity", identifier] });
    },
  });
}

/** Clear an override (revert to the auto value) → prime the cache with the recompute. */
export function useClearLtvOverride(identifier: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (fieldKey: string) => clearLtvOverride(identifier, fieldKey),
    onSuccess: (data) => {
      queryClient.setQueryData(ltvQueryKey(identifier), data);
      void queryClient.invalidateQueries({ queryKey: ["loan-file-activity", identifier] });
    },
  });
}
