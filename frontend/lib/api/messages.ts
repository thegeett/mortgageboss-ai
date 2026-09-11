/**
 * Reply, compose, and the two flags (LP-818).
 *
 * REPLY PRODUCES A DRAFT, NOT A SEND. LP-811a's send endpoint takes it from there, with the same
 * rate limit, the same suppression check and the same record of what actually went out — a reply
 * that skipped that would be the one outbound message in the product with no guardrails on it.
 */
import { apiClient } from "@/lib/api/client";
import { invalidateDraftViews } from "@/lib/api/draft-views";
import { useMutation, useQueryClient } from "@tanstack/react-query";

const messagesPath = (fileId: string) => `/api/v1/loan-files/${fileId}/messages`;

export interface ReplyContext {
  recipient: string;
  subject: string;
}

export interface MessageSummary {
  id: string;
  direction: string;
  status: string;
  subject: string | null;
  recipient: string | null;
  is_important: boolean;
  read_at: string | null;
}

export async function fetchReplyContext(
  fileId: string,
  communicationId: string,
): Promise<ReplyContext> {
  return (
    await apiClient.get<ReplyContext>(`${messagesPath(fileId)}/${communicationId}/reply-context`)
  ).data;
}

/** Everything on this screen changes when a message does — the list, the flags and the badge.
 *
 * LP-840 REVIEW — THROUGH THE ONE PLACE, and the deleted draft key is gone from it. (Named rather
 * than quoted: the guard in `verification-draft-invalidation.test.ts` is a substring scan, and
 * prose holding the literal would report the file it had just fixed — LP-838's lesson.) That key
 * was spelled here as a literal, so deleting `outboundDraftQueryKey` and its named usages left this
 * copy behind: an invalidation of a query with no reader, which is the exact thing the ticket was
 * written about. A reply IS a draft, so this goes through `invalidateDraftViews` rather than keeping
 * a second list — the drift between those lists is what produced the reported bug.
 */
function invalidateTimeline(queryClient: ReturnType<typeof useQueryClient>, fileId: string) {
  invalidateDraftViews(queryClient, fileId);
}

export function useReply(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ communicationId, body }: { communicationId: string; body: string }) =>
      (
        await apiClient.post<MessageSummary>(`${messagesPath(fileId)}/${communicationId}/reply`, {
          body,
        })
      ).data,
    onSuccess: () => invalidateTimeline(queryClient, fileId),
  });
}

export function useSetImportant(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      communicationId,
      important,
    }: {
      communicationId: string;
      important: boolean;
    }) =>
      (
        await apiClient.post<MessageSummary>(
          `${messagesPath(fileId)}/${communicationId}/important`,
          { important },
        )
      ).data,
    onSuccess: () => invalidateTimeline(queryClient, fileId),
  });
}

export function useMarkRead(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ communicationId, read }: { communicationId: string; read: boolean }) =>
      (
        await apiClient.post<MessageSummary>(`${messagesPath(fileId)}/${communicationId}/read`, {
          read,
        })
      ).data,
    onSuccess: () => invalidateTimeline(queryClient, fileId),
  });
}
