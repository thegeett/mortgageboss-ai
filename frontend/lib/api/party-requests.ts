/**
 * Non-borrower request paths (LP-820).
 *
 * BUILDING A DRAFT IS NOT SENDING. The draft goes onto LP-811a's existing send path — same rate
 * limit, same suppression check, and the same `request_needs_item` call that stamps `requested_at`
 * and starts LP-814's clock. That call is the whole reason these are real drafts.
 */
import { apiClient } from "@/lib/api/client";
import { invalidateDraftViews } from "@/lib/api/draft-views";
import type { PartyRequest, ResponsibleParty } from "@/lib/types/party-request";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const path = (fileId: string) => `/api/v1/loan-files/${fileId}/party-requests`;

export const partyRequestsQueryKey = (fileId: string) => ["party-requests", fileId] as const;

export function usePartyRequests(fileId: string) {
  return useQuery({
    queryKey: partyRequestsQueryKey(fileId),
    queryFn: async () => (await apiClient.get<PartyRequest[]>(path(fileId))).data,
    enabled: Boolean(fileId),
  });
}

/** Everything a party change touches: this list, the draft panel, and the file's timeline. */
function invalidate(queryClient: ReturnType<typeof useQueryClient>, fileId: string) {
  void queryClient.invalidateQueries({ queryKey: partyRequestsQueryKey(fileId) });
  // LP-840 REVIEW — THROUGH THE ONE PLACE. `build_party_draft` creates a Communication, and
  // `build_timeline` has no template filter, so a party draft IS a row in the mailbox. This listed
  // the timeline by hand and also the draft key LP-840 deleted the query for — named rather than
  // quoted, because the guard is a substring scan and prose holding the literal would report the
  // file it had just fixed (LP-838's lesson, one module over),
  // spelled as a literal here and so missed when the named constant went. Two hand-kept lists
  // drifting apart is what produced the reported bug; this is the second of them.
  invalidateDraftViews(queryClient, fileId);
}

export interface AddAddressInput {
  role: string;
  email: string;
  name?: string | null;
}

export function useAddPartyAddress(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: AddAddressInput) => {
      await apiClient.post(`${path(fileId)}/addresses`, input);
    },
    onSuccess: () => invalidate(queryClient, fileId),
  });
}

export function useBuildPartyDraft(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (party: ResponsibleParty) =>
      (
        await apiClient.post<{
          communication_id: string;
          recipient: string | null;
          needs_count: number;
        }>(`${path(fileId)}/draft`, { party })
      ).data,
    onSuccess: () => invalidate(queryClient, fileId),
  });
}
