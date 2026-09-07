/**
 * Reply, compose, and the two flags (LP-818).
 *
 * REPLY PRODUCES A DRAFT, NOT A SEND. LP-811a's send endpoint takes it from there, with the same
 * rate limit, the same suppression check and the same record of what actually went out — a reply
 * that skipped that would be the one outbound message in the product with no guardrails on it.
 */
import { apiClient } from "@/lib/api/client";
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

/** Everything on this screen changes when a message does — the list, the flags and the badge. */
function invalidateTimeline(queryClient: ReturnType<typeof useQueryClient>, fileId: string) {
  void queryClient.invalidateQueries({ queryKey: ["timeline", fileId] });
  void queryClient.invalidateQueries({ queryKey: ["outbound-draft", fileId] });
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
