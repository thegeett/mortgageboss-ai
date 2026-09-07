/**
 * The outbound draft (LP-811b) — read the file's open document request, and record that it was sent.
 *
 * NOTHING HERE TRANSMITS. M1's send path is copy-and-send: the processor puts the text into their
 * own mail client, or opens a `mailto:` link. "Send" means *record that it went out* — which is what
 * moves every requested document to REQUESTED and starts the reminder clock.
 */
import { apiClient } from "@/lib/api/client";
import type { MessageDetail, OutboundDraft, SentCommunication } from "@/lib/types/communication";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";

const API_V1 = "/api/v1";

export const outboundDraftQueryKey = (fileId: string) => ["outbound-draft", fileId] as const;
const needsQueryKey = (fileId: string) => ["loan-file-needs", fileId] as const;
const activityQueryKey = (fileId: string) => ["loan-file-activity", fileId] as const;

const outboundPath = (fileId: string) => `${API_V1}/loan-files/${fileId}/outbound`;

/** A 404 here means "no open draft", which is an ordinary state and will not change on retry. */
function noRetryOn404(failureCount: number, error: unknown): boolean {
  return !(isAxiosError(error) && error.response?.status === 404) && failureCount < 1;
}

export async function fetchOutboundDraft(fileId: string): Promise<OutboundDraft | null> {
  try {
    const res = await apiClient.get<OutboundDraft>(`${outboundPath(fileId)}/draft`);
    return res.data;
  } catch (error) {
    // A file with nothing outstanding has no draft. That is not an error to show anybody — it is
    // the empty state, and throwing here would put a red banner on a file in good order.
    if (isAxiosError(error) && error.response?.status === 404) return null;
    throw error;
  }
}

export const messageQueryKey = (fileId: string, messageId: string) =>
  ["message", fileId, messageId] as const;

/**
 * One message in full (LP-829) — the dialog's data.
 *
 * FETCHED ON OPEN, not with the timeline. A timeline row is a summary and there can be two hundred
 * of them; loading every body to render a list would make this the fullest copy of a borrower's
 * prose in the browser, for messages nobody opened.
 */
/**
 * Put a secure upload link in this draft (LP-834).
 *
 * INVALIDATES THE LINKS LIST TOO. Minting expires every other live link on the file, so the panel
 * listing them is stale the moment this resolves — and that panel is where a processor would go to
 * check what a borrower still has.
 */
export interface ComposedRequest {
  draft_id: string | null;
  needs_added: number;
  /** Whether a MODEL wrote the framing, or the deterministic template did. */
  composed_by_model: boolean;
}

/**
 * Ask for documents a processor picked, rather than ones a rule found (LP-833).
 *
 * Invalidates the needs list as well as the drafts: the selection becomes real needs items, which is
 * what puts them on that list and what the send moves to REQUESTED.
 */
export function useComposeRequest(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (documentTypes: string[]) =>
      (
        await apiClient.post<ComposedRequest>(`${outboundPath(fileId)}/compose`, {
          document_types: documentTypes,
        })
      ).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["timeline", fileId] });
      void queryClient.invalidateQueries({ queryKey: needsQueryKey(fileId) });
      void queryClient.invalidateQueries({ queryKey: outboundDraftQueryKey(fileId) });
    },
  });
}

export function useAttachUploadLink(fileId: string, messageId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      (
        await apiClient.post<MessageDetail>(
          `${API_V1}/loan-files/${fileId}/messages/${messageId}/upload-link`,
        )
      ).data,
    onSuccess: (detail) => {
      queryClient.setQueryData(messageQueryKey(fileId, messageId), detail);
      void queryClient.invalidateQueries({ queryKey: ["upload-links", fileId] });
      void queryClient.invalidateQueries({ queryKey: ["timeline", fileId] });
    },
  });
}

export function useMessageDetail(fileId: string, messageId: string | null) {
  return useQuery({
    queryKey: messageQueryKey(fileId, messageId ?? ""),
    queryFn: async () =>
      (await apiClient.get<MessageDetail>(`${API_V1}/loan-files/${fileId}/messages/${messageId}`))
        .data,
    enabled: Boolean(fileId) && Boolean(messageId),
    retry: noRetryOn404,
  });
}

export function useOutboundDraft(fileId: string) {
  return useQuery({
    queryKey: outboundDraftQueryKey(fileId),
    queryFn: () => fetchOutboundDraft(fileId),
    enabled: Boolean(fileId),
    retry: noRetryOn404,
  });
}

export interface SendDraftInput {
  draftId: string;
  recipient: string;
  body: string;
  /** LP-831 — omitted means "the subject already on the draft", which the server treats as a
   * complete answer. Only the modal sends one, because only the modal offers a subject field. */
  subject?: string;
}

/**
 * Record a send. Invalidates the draft, the needs list and the activity feed — all three change:
 * the draft becomes a sent message, every need in it moves to REQUESTED, and the send is audited.
 */
export function useSendDraft(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ draftId, recipient, body, subject }: SendDraftInput) =>
      (
        await apiClient.post<SentCommunication>(`${outboundPath(fileId)}/draft/${draftId}/send`, {
          recipient,
          body,
          subject,
        })
      ).data,
    onSuccess: (_sent, variables) => {
      void queryClient.invalidateQueries({ queryKey: outboundDraftQueryKey(fileId) });
      void queryClient.invalidateQueries({ queryKey: needsQueryKey(fileId) });
      void queryClient.invalidateQueries({ queryKey: activityQueryKey(fileId) });
      // LP-831 — THE LIST AND THE MESSAGE ITSELF. A send moves a draft out of the drafts filter and
      // changes its status, so the timeline is stale; and the modal that just sent it is showing a
      // row that is no longer a draft. Neither was invalidated while the compose form lived on the
      // page and the timeline was somewhere else to scroll to.
      void queryClient.invalidateQueries({ queryKey: ["timeline", fileId] });
      void queryClient.invalidateQueries({
        queryKey: messageQueryKey(fileId, variables.draftId),
      });
    },
  });
}

/**
 * The `mailto:` URL for a draft, or null when the message is too long to survive one.
 *
 * NULL RATHER THAN A TRUNCATED LINK. A `mailto:` over the client's limit does not fail — it opens a
 * compose window containing part of the message, which a processor may send without noticing. The
 * server decides whether it fits; this only builds the URL when it said yes.
 */
/**
 * The `mailto:` link for the message AS IT STANDS IN THE TEXTAREA — never the composed draft.
 *
 * `body` is a parameter rather than read off `draft` because those two diverge the moment a
 * processor types. Built from `draft.body`, this link opened the mail client on the UNEDITED text
 * while "Copy message" and "Mark as sent" both used the edit: the borrower would receive one
 * version and the record would store the other, which is the one failure an evidence record cannot
 * survive.
 *
 * The length gate is recomputed here for the same reason. `draft.mailto_available` is the server's
 * verdict on the COMPOSED body (LP-811a's `build_outbound`), and an edit that runs past the limit
 * would otherwise still be offered a link that silently truncates. The server still owns the limit;
 * only the measurement moves to the text actually being sent.
 */
/**
 * The same link for a message opened from the list (LP-831 review).
 *
 * `mailtoUrl` takes an `OutboundDraft`, the payload of the panel this ticket took off the page.
 * `MessageDetail` now carries the same three fields, for the same reason and with the same two
 * gates: the server's verdict on the composed body, and a length check on the text actually being
 * sent, because an edit can run past the limit after that verdict was formed.
 *
 * Kept as its own function rather than widening `mailtoUrl`'s parameter type: the two payloads are
 * different shapes and a union would let a caller pass a draft where a message is meant and get an
 * answer about the wrong body.
 */
export function messageMailtoUrl(
  message: MessageDetail,
  recipient: string,
  body: string,
): string | null {
  if (!message.mailto_available) return null;
  const subject = message.subject ?? "";
  if (body.length + subject.length > message.mailto_max_chars) return null;
  const params = new URLSearchParams({ subject, body, bcc: message.suggested_bcc });
  return `mailto:${encodeURIComponent(recipient)}?${params.toString()}`;
}

export function mailtoUrl(draft: OutboundDraft, recipient: string, body: string): string | null {
  // BOTH gates. `draft.mailto_available` is the server's verdict on the composed body and may
  // know things this side does not; the length check catches an EDIT that ran past the limit after
  // that verdict was formed. Either one saying no is a no.
  if (!draft.mailto_available) return null;
  if (body.length + draft.subject.length > draft.mailto_max_chars) return null;
  const params = new URLSearchParams({
    subject: draft.subject,
    body,
    bcc: draft.suggested_bcc,
  });
  return `mailto:${encodeURIComponent(recipient)}?${params.toString()}`;
}
