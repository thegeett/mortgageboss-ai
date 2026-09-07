/**
 * DTI calculator data layer (LP-76): the read + the override mutations.
 *
 * The override endpoints return the *recomputed* calculation in the response, so
 * a mutation primes the query cache directly (`setQueryData`) — the calculator
 * updates in real time from one round-trip. The activity feed is invalidated so
 * the audited override appears there too.
 */
import { apiClient } from "@/lib/api/client";
import type {
  DtiCalculation,
  DtiCustomLineInput,
  DtiOverrideInput,
  DtiUngatePreview,
} from "@/lib/types/dti";
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

/* -------------------------------------------------------------------------- */
/* LP-643 — processor-added lines, and the ungate                             */
/* -------------------------------------------------------------------------- */

export async function addDtiLine(
  identifier: string,
  input: DtiCustomLineInput,
): Promise<DtiCalculation> {
  const res = await apiClient.post<DtiCalculation>(
    `${API_V1}/loan-files/${identifier}/dti/lines`,
    input,
  );
  return res.data;
}

export async function removeDtiLine(identifier: string, lineId: string): Promise<DtiCalculation> {
  const res = await apiClient.delete<DtiCalculation>(
    `${API_V1}/loan-files/${identifier}/dti/lines/${lineId}`,
  );
  return res.data;
}

export async function fetchDtiUngatePreview(identifier: string): Promise<DtiUngatePreview> {
  const res = await apiClient.get<DtiUngatePreview>(
    `${API_V1}/loan-files/${identifier}/dti/ungate`,
  );
  return res.data;
}

export async function applyDtiUngate(
  identifier: string,
  note: string | null,
): Promise<DtiCalculation> {
  const res = await apiClient.post<DtiCalculation>(
    `${API_V1}/loan-files/${identifier}/dti/ungate`,
    { amount: 0, note },
  );
  return res.data;
}

/** Add a processor's own line → prime the cache with the recompute. */
export function useAddDtiLine(identifier: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: DtiCustomLineInput) => addDtiLine(identifier, input),
    onSuccess: (data) => {
      queryClient.setQueryData(dtiQueryKey(identifier), data);
      void queryClient.invalidateQueries({ queryKey: ["loan-file-activity", identifier] });
    },
  });
}

/** Remove a line the processor added (never an engine line — the API has no such route). */
export function useRemoveDtiLine(identifier: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (lineId: string) => removeDtiLine(identifier, lineId),
    onSuccess: (data) => {
      queryClient.setQueryData(dtiQueryKey(identifier), data);
      void queryClient.invalidateQueries({ queryKey: ["loan-file-activity", identifier] });
    },
  });
}

/**
 * The ungate preview — fetched ONLY when the dialog opens (`enabled`).
 *
 * It is the popup's entire content and it is deliberately not cached alongside the calculation: it
 * is a statement about what an action WOULD do, computed against the file as it stands right now.
 * Serving a stale one would show a processor a consequence that has since changed, on the screen
 * where they accept it personally.
 */
export function useDtiUngatePreview(identifier: string, enabled: boolean) {
  return useQuery({
    queryKey: ["dti-ungate-preview", identifier],
    queryFn: () => fetchDtiUngatePreview(identifier),
    enabled: Boolean(identifier) && enabled,
    staleTime: 0,
    gcTime: 0,
  });
}

/** Apply the ungate → prime the cache with the recompute. */
export function useApplyDtiUngate(identifier: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (note: string | null) => applyDtiUngate(identifier, note),
    onSuccess: (data) => {
      queryClient.setQueryData(dtiQueryKey(identifier), data);
      void queryClient.invalidateQueries({ queryKey: ["loan-file-activity", identifier] });
      void queryClient.invalidateQueries({ queryKey: ["dti-ungate-preview", identifier] });
    },
  });
}
