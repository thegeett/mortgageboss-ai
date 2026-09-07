/**
 * The triage queue (LP-807) — what arrived, and what a processor decides about it.
 *
 * TWO LISTS, DELIBERATELY SEPARATE. A file's own messages come from a file-scoped route and carry
 * everything the sender wrote. The company queue also holds UNROUTED messages, which have no owner
 * and are therefore visible to every company — so the server returns them with the sender, the
 * subject and both filenames stripped. Those nulls are a state to render, not data that failed to
 * load, and `unclaimed()` below is what tells them apart.
 */
import { apiClient } from "@/lib/api/client";
import type { AcceptResult, InboundMessage } from "@/lib/types/inbound";
import { type QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";

const API_V1 = "/api/v1";

/** The cache namespace for preview blobs, named once so the revoker cannot drift from it. */
export const PREVIEW_KEY = "inbound-preview";

export const fileMessagesQueryKey = (fileId: string) => ["inbound-messages", fileId] as const;
export const triageQueueQueryKey = () => ["inbound-queue"] as const;
export const previewQueryKey = (fileId: string, attachmentId: string) =>
  [PREVIEW_KEY, fileId, attachmentId] as const;

const inboundPath = (fileId: string) => `${API_V1}/loan-files/${fileId}/inbound`;

/**
 * True when nobody owns this message yet, so the sender's own words are not in it.
 *
 * Read off `loan_file_id` rather than off a null `from_address`, because a message genuinely CAN
 * arrive with no From header — a malformed one, or a bounce — and rendering that as "redacted for
 * your protection" would be a confident explanation of the wrong thing.
 */
export function unclaimed(message: InboundMessage): boolean {
  return message.loan_file_id === null;
}

export async function fetchFileMessages(fileId: string): Promise<InboundMessage[]> {
  return (await apiClient.get<InboundMessage[]>(`${inboundPath(fileId)}/messages`)).data;
}

export function useFileMessages(fileId: string) {
  return useQuery({
    queryKey: fileMessagesQueryKey(fileId),
    queryFn: () => fetchFileMessages(fileId),
    enabled: Boolean(fileId),
  });
}

export async function fetchTriageQueue(): Promise<InboundMessage[]> {
  return (
    await apiClient.get<InboundMessage[]>(`${API_V1}/inbound/queue`, {
      params: { include_unrouted: true },
    })
  ).data;
}

export function useTriageQueue() {
  return useQuery({ queryKey: triageQueueQueryKey(), queryFn: fetchTriageQueue });
}

/**
 * A thumbnail's object URL, or null when the attachment has no preview.
 *
 * NULL IS AN ORDINARY ANSWER. A 415 means the file is safe and simply cannot be rendered — a HEIC
 * from an iPhone, a TIFF fax — and a 409 means it will not be rendered because it is not safe. Both
 * are states the card shows differently, and neither is worth a retry.
 */
export async function fetchPreview(fileId: string, attachmentId: string): Promise<string | null> {
  try {
    const res = await apiClient.get(`${inboundPath(fileId)}/attachments/${attachmentId}/preview`, {
      responseType: "blob",
    });
    return URL.createObjectURL(res.data as Blob);
  } catch (error) {
    if (isAxiosError(error) && (error.response?.status === 415 || error.response?.status === 409)) {
      return null;
    }
    throw error;
  }
}

export function useAttachmentPreview(
  fileId: string | null,
  attachmentId: string,
  enabled: boolean,
) {
  return useQuery({
    queryKey: previewQueryKey(fileId ?? "", attachmentId),
    queryFn: () => fetchPreview(fileId as string, attachmentId),
    enabled: Boolean(fileId) && enabled,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
}

/**
 * Revoke a preview's object URL when the cache evicts it.
 *
 * THE SAME LESSON AS `revokePageImagesOnEviction`, and the reason this is here rather than in a
 * component: eviction happens LATER by design — TanStack's default `gcTime` is five minutes after
 * the last observer goes away — so a subscription torn down on unmount is gone before the event it
 * is waiting for. A triage queue is a grid of thumbnails, and leaving the page without this holds
 * every one of them as a decoded PNG for the rest of the session.
 */
export function revokePreviewsOnEviction(queryClient: QueryClient): () => void {
  return queryClient.getQueryCache().subscribe((event) => {
    if (event.type !== "removed") return;
    const key = event.query.queryKey;
    if (!Array.isArray(key) || key[0] !== PREVIEW_KEY) return;
    const url = event.query.state.data as string | null | undefined;
    if (url) URL.revokeObjectURL(url);
  });
}

export interface AcceptInput {
  attachmentId: string;
  asCorrespondence?: boolean;
}

/**
 * Accept one attachment onto the file, as a document or as correspondence.
 *
 * Invalidates the messages, the documents list and the activity feed — all three change, and a
 * processor who accepts a document and then does not see it in Documents will accept it again.
 */
export function useAcceptAttachment(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ attachmentId, asCorrespondence = false }: AcceptInput) =>
      (
        await apiClient.post<AcceptResult>(
          `${inboundPath(fileId)}/attachments/${attachmentId}/accept`,
          { as_correspondence: asCorrespondence },
        )
      ).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: fileMessagesQueryKey(fileId) });
      void queryClient.invalidateQueries({ queryKey: triageQueueQueryKey() });
      void queryClient.invalidateQueries({ queryKey: ["loan-file-documents", fileId] });
      void queryClient.invalidateQueries({ queryKey: ["loan-file-activity", fileId] });
      void queryClient.invalidateQueries({ queryKey: ["loan-file-needs", fileId] });
    },
  });
}

export function useRejectAttachment(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (attachmentId: string) =>
      (
        await apiClient.post<AcceptResult>(
          `${inboundPath(fileId)}/attachments/${attachmentId}/reject`,
          {},
        )
      ).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: fileMessagesQueryKey(fileId) });
      void queryClient.invalidateQueries({ queryKey: triageQueueQueryKey() });
    },
  });
}
