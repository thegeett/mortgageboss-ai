/**
 * Verification data layer (LP-78) — the status read + the manual trigger.
 *
 * The cross-source pass is an AI call that runs on the worker, so the trigger is a
 * mutation that starts a run; the status query **polls while a run is RUNNING**
 * (and stops once it settles), surfacing the findings + the staleness flag.
 */
import { apiClient } from "@/lib/api/client";
import { dtiQueryKey } from "@/lib/api/dti";
import { ltvQueryKey } from "@/lib/api/ltv";
import type {
  AggressionLevel,
  VerificationRun,
  VerificationStatus,
} from "@/lib/types/verification";
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

/**
 * Trigger the cross-source pass. By default the backend returns the CACHED result
 * when the inputs are unchanged (no AI re-run); `force` re-runs the AI anyway.
 */
export async function runVerification(identifier: string, force = false): Promise<VerificationRun> {
  const res = await apiClient.post<VerificationRun>(
    `${API_V1}/loan-files/${identifier}/verification/run${force ? "?force=true" : ""}`,
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
    // `force` re-runs the AI even when inputs are unchanged (the escape hatch).
    mutationFn: (force?: boolean) => runVerification(identifier, force ?? false),
    onSuccess: () => {
      // Refetch the status (now RUNNING, or the cached completed run) so the UI updates.
      void queryClient.invalidateQueries({ queryKey: verificationQueryKey(identifier) });
    },
  });
}

/**
 * Set (or clear) this file's aggression override (LP-79). A pure read-time re-filter
 * over the STORED findings — it never re-runs the AI. `level = null` clears the override
 * (revert to the user default). Returns the re-filtered status (new in-scope + blocking).
 */
export async function setAggression(
  identifier: string,
  level: AggressionLevel | null,
): Promise<VerificationStatus> {
  const res = await apiClient.put<VerificationStatus>(
    `${API_V1}/loan-files/${identifier}/verification/aggression`,
    { level },
  );
  return res.data;
}

export function useSetAggression(identifier: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (level: AggressionLevel | null) => setAggression(identifier, level),
    onSuccess: (status) => {
      // The cutoff changed → the in-scope set + the finding-coupled calculators' alerts
      // change too. Seed the new status and refresh DTI/LTV (no AI re-run anywhere).
      queryClient.setQueryData(verificationQueryKey(identifier), status);
      void queryClient.invalidateQueries({ queryKey: dtiQueryKey(identifier) });
      void queryClient.invalidateQueries({ queryKey: ltvQueryKey(identifier) });
    },
  });
}

// --- Per-finding action set (LP-81 + LP-88) -------------------------------- //
// LP-81: Apply / Override / Add note. LP-88: Accept-risk (acknowledge, distinct from
// override) + Request-docs (create a needs item from the finding).

/** The kind of resolution action + its body. */
type Resolution =
  | { kind: "apply"; findingId: string }
  | { kind: "override"; findingId: string; reason: string }
  | { kind: "note"; findingId: string; note: string }
  | { kind: "accept-risk"; findingId: string; reason: string }
  | { kind: "request-docs"; findingId: string; note: string };

async function resolveFinding(identifier: string, action: Resolution): Promise<VerificationStatus> {
  const base = `${API_V1}/loan-files/${identifier}/findings/${action.findingId}`;
  let body: Record<string, string> = {};
  if (action.kind === "override") body = { reason: action.reason };
  else if (action.kind === "note") body = { note: action.note };
  else if (action.kind === "accept-risk") body = { reason: action.reason };
  else if (action.kind === "request-docs") body = { note: action.note };
  const res = await apiClient.post<VerificationStatus>(`${base}/${action.kind}`, body);
  return res.data;
}

/**
 * Resolve a finding (Apply / Override / Note / Accept-risk / Request-docs). The endpoint
 * returns the re-filtered status (updated findings + blocking); APPLY also changes the
 * structured data (refresh DTI/LTV — the recompute interlock); Request-docs creates a
 * needs item (refresh the needs list).
 */
export function useResolveFinding(identifier: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (action: Resolution) => resolveFinding(identifier, action),
    onSuccess: (status) => {
      queryClient.setQueryData(verificationQueryKey(identifier), status);
      void queryClient.invalidateQueries({ queryKey: dtiQueryKey(identifier) });
      void queryClient.invalidateQueries({ queryKey: ltvQueryKey(identifier) });
      void queryClient.invalidateQueries({ queryKey: ["needs", identifier] });
      void queryClient.invalidateQueries({ queryKey: ["loan-file-activity", identifier] });
    },
  });
}

// --- Run history (LP-88) — the version selector ---------------------------- //

export async function fetchVerificationRuns(identifier: string): Promise<VerificationRun[]> {
  const res = await apiClient.get<VerificationRun[]>(
    `${API_V1}/loan-files/${identifier}/verification/runs`,
  );
  return res.data;
}

export function useVerificationRuns(identifier: string, enabled = true) {
  return useQuery({
    queryKey: ["verification-runs", identifier],
    queryFn: () => fetchVerificationRuns(identifier),
    enabled: Boolean(identifier) && enabled,
    retry: noRetryOn404,
  });
}
