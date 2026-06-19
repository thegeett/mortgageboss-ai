/**
 * Needs-list data layer (LP-70): the read hook (with live updates) + the
 * disposition mutations (the AI proposes, the processor disposes).
 *
 * Live updates: `useNeeds(fileId, { live })` polls while documents are processing
 * (`live` is the file's "any document in-flight" flag, derived from the documents
 * query) and stops once everything is settled. So as a document arrives and the
 * LP-68 engine advances a need (Pending → Received → Verified), the dashboard
 * reflects it without a manual refresh — and the poll stops once nothing can
 * change. We show the OUTCOME (the needs settling), never the engine's mechanism.
 *
 * The disposition mutations each invalidate the needs list (so the change shows)
 * and the activity feed (every disposition is audited).
 */
import { apiClient } from "@/lib/api/client";
import type { NeedsItemPriority, NeedsItemPublic } from "@/lib/types/needs-item";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";

const API_V1 = "/api/v1";
export const NEEDS_POLL_INTERVAL_MS = 2000;
// Backstop: stop auto-polling after this many fetches even while a document is
// still processing, so a stuck pipeline doesn't make the page poll forever. A
// refresh resumes it. ~45 × 2s ≈ 90s, comfortably past normal settling.
export const MAX_NEEDS_POLLS = 45;

/** A 404 (missing or out-of-company) won't change on retry — surface it. */
function noRetryOn404(failureCount: number, error: unknown): boolean {
  return !(isAxiosError(error) && error.response?.status === 404) && failureCount < 1;
}

export const needsQueryKey = (fileId: string) => ["loan-file-needs", fileId] as const;
const activityQueryKey = (fileId: string) => ["loan-file-activity", fileId] as const;
const needsPath = (fileId: string) => `${API_V1}/loan-files/${fileId}/needs`;

/**
 * The polling interval for the needs list: poll while the file has documents
 * in-flight (`live`), but stop once everything is settled OR the backstop trips.
 * Extracted (and exported) so it is unit-testable.
 */
export function needsRefetchInterval(live: boolean, fetchCount: number): number | false {
  if (!live) return false;
  if (fetchCount > MAX_NEEDS_POLLS) return false;
  return NEEDS_POLL_INTERVAL_MS;
}

export async function fetchNeeds(fileId: string): Promise<NeedsItemPublic[]> {
  const res = await apiClient.get<NeedsItemPublic[]>(needsPath(fileId));
  return res.data;
}

/** The needs list, polling live while documents are processing (`live`). */
export function useNeeds(fileId: string, options: { live?: boolean } = {}) {
  const live = options.live ?? false;
  return useQuery({
    queryKey: needsQueryKey(fileId),
    queryFn: () => fetchNeeds(fileId),
    enabled: Boolean(fileId),
    retry: noRetryOn404,
    refetchInterval: (query) => needsRefetchInterval(live, query.state.dataUpdateCount),
  });
}

// --- Disposition mutations -------------------------------------------------- //

/** Invalidate the needs list + the activity feed after a disposition action. */
function useNeedsInvalidation(fileId: string) {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: needsQueryKey(fileId) });
    void queryClient.invalidateQueries({ queryKey: activityQueryKey(fileId) });
  };
}

export interface AdjustNeedInput {
  title?: string;
  description?: string | null;
  needs_type?: string | null;
  priority?: NeedsItemPriority;
}

export interface AddNeedInput {
  title: string;
  description?: string | null;
  needs_type?: string | null;
  priority?: NeedsItemPriority;
}

/** Confirm a proposed need (proposed → confirmed). */
export function useConfirmNeed(fileId: string) {
  const invalidate = useNeedsInvalidation(fileId);
  return useMutation({
    mutationFn: async (needId: string) =>
      (await apiClient.post<NeedsItemPublic>(`${needsPath(fileId)}/${needId}/confirm`)).data,
    onSuccess: invalidate,
  });
}

/** Adjust a need's content (a correction signal). */
export function useAdjustNeed(fileId: string) {
  const invalidate = useNeedsInvalidation(fileId);
  return useMutation({
    mutationFn: async ({ needId, input }: { needId: string; input: AdjustNeedInput }) =>
      (await apiClient.patch<NeedsItemPublic>(`${needsPath(fileId)}/${needId}`, input)).data,
    onSuccess: invalidate,
  });
}

/** Dismiss a proposed need (doesn't apply), with a reason. */
export function useDismissNeed(fileId: string) {
  const invalidate = useNeedsInvalidation(fileId);
  return useMutation({
    mutationFn: async ({ needId, reason }: { needId: string; reason?: string }) =>
      (
        await apiClient.post<NeedsItemPublic>(`${needsPath(fileId)}/${needId}/dismiss`, {
          reason: reason ?? null,
        })
      ).data,
    onSuccess: invalidate,
  });
}

/** Waive a need (not required for this file), with a reason. */
export function useWaiveNeed(fileId: string) {
  const invalidate = useNeedsInvalidation(fileId);
  return useMutation({
    mutationFn: async ({ needId, reason }: { needId: string; reason?: string }) =>
      (
        await apiClient.post<NeedsItemPublic>(`${needsPath(fileId)}/${needId}/waive`, {
          reason: reason ?? null,
        })
      ).data,
    onSuccess: invalidate,
  });
}

/** Add a need the AI missed (a processor-authored, confirmed need). */
export function useAddNeed(fileId: string) {
  const invalidate = useNeedsInvalidation(fileId);
  return useMutation({
    mutationFn: async (input: AddNeedInput) =>
      (await apiClient.post<NeedsItemPublic>(needsPath(fileId), input)).data,
    onSuccess: invalidate,
  });
}
