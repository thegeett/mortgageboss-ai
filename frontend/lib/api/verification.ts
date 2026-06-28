/**
 * Verification data layer (LP-78) — the status read + the manual trigger.
 *
 * The cross-source pass is an AI call that runs on the worker, so the trigger is a
 * mutation that starts a run; the status query **polls while a run is RUNNING**
 * (and stops once it settles), surfacing the findings + the staleness flag.
 */
import { apiClient } from "@/lib/api/client";
import type { VerificationRun, VerificationStatus } from "@/lib/types/verification";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";

const API_V1 = "/api/v1";

export const verificationQueryKey = (identifier: string) => ["verification", identifier] as const;

export async function fetchVerification(identifier: string): Promise<VerificationStatus> {
  const res = await apiClient.get<VerificationStatus>(
    `${API_V1}/loan-files/${identifier}/verification`,
  );
  return res.data;
}

export async function runVerification(identifier: string): Promise<VerificationRun> {
  const res = await apiClient.post<VerificationRun>(
    `${API_V1}/loan-files/${identifier}/verification/run`,
  );
  return res.data;
}

function noRetryOn404(failureCount: number, error: unknown): boolean {
  return !(isAxiosError(error) && error.response?.status === 404) && failureCount < 1;
}

export function useVerification(identifier: string) {
  return useQuery({
    queryKey: verificationQueryKey(identifier),
    queryFn: () => fetchVerification(identifier),
    enabled: Boolean(identifier),
    retry: noRetryOn404,
    // Poll while a run is in progress; stop once it settles (an AI call takes time).
    refetchInterval: (query) => (query.state.data?.latest_run?.status === "running" ? 2000 : false),
  });
}

export function useRunVerification(identifier: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => runVerification(identifier),
    onSuccess: () => {
      // Refetch the status (now RUNNING) so polling kicks in.
      void queryClient.invalidateQueries({ queryKey: verificationQueryKey(identifier) });
    },
  });
}
