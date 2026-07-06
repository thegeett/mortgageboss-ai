/**
 * DTI calculator data layer (LP-76): the read + the override mutations.
 *
 * The override endpoints return the *recomputed* calculation in the response, so
 * a mutation primes the query cache directly (`setQueryData`) — the calculator
 * updates in real time from one round-trip. The activity feed is invalidated so
 * the audited override appears there too.
 */
import { apiClient } from "@/lib/api/client";
import type { DtiCalculation, DtiOverrideInput } from "@/lib/types/dti";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";

const API_V1 = "/api/v1";

export const dtiQueryKey = (identifier: string) => ["dti", identifier] as const;

export async function fetchDti(identifier: string): Promise<DtiCalculation> {
  const res = await apiClient.get<DtiCalculation>(`${API_V1}/loan-files/${identifier}/dti`);
  return res.data;
}

/** A 404 (missing or out-of-company) won't change on retry — surface it. */
function noRetryOn404(failureCount: number, error: unknown): boolean {
  return !(isAxiosError(error) && error.response?.status === 404) && failureCount < 1;
}

export function useDti(identifier: string) {
  return useQuery({
    queryKey: dtiQueryKey(identifier),
    queryFn: () => fetchDti(identifier),
    enabled: Boolean(identifier),
    retry: noRetryOn404,
  });
}

export async function setDtiOverride(
  identifier: string,
  fieldKey: string,
  input: DtiOverrideInput,
): Promise<DtiCalculation> {
  const res = await apiClient.put<DtiCalculation>(
    `${API_V1}/loan-files/${identifier}/dti/overrides/${fieldKey}`,
    input,
  );
  return res.data;
}

export async function clearDtiOverride(
  identifier: string,
  fieldKey: string,
): Promise<DtiCalculation> {
  const res = await apiClient.delete<DtiCalculation>(
    `${API_V1}/loan-files/${identifier}/dti/overrides/${fieldKey}`,
  );
  return res.data;
}

/** Set an override → prime the cache with the recomputed result (real-time recalc). */
export function useSetDtiOverride(identifier: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ fieldKey, input }: { fieldKey: string; input: DtiOverrideInput }) =>
      setDtiOverride(identifier, fieldKey, input),
    onSuccess: (data) => {
      queryClient.setQueryData(dtiQueryKey(identifier), data);
      void queryClient.invalidateQueries({ queryKey: ["loan-file-activity", identifier] });
    },
  });
}

/** Clear an override (revert to the auto value) → prime the cache with the recompute. */
export function useClearDtiOverride(identifier: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (fieldKey: string) => clearDtiOverride(identifier, fieldKey),
    onSuccess: (data) => {
      queryClient.setQueryData(dtiQueryKey(identifier), data);
      void queryClient.invalidateQueries({ queryKey: ["loan-file-activity", identifier] });
    },
  });
}
