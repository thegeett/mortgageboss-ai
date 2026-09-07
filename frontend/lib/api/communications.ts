/**
 * The outbound draft (LP-811b) — read the file's open document request, and record that it was sent.
 *
 * NOTHING HERE TRANSMITS. M1's send path is copy-and-send: the processor puts the text into their
 * own mail client, or opens a `mailto:` link. "Send" means *record that it went out* — which is what
 * moves every requested document to REQUESTED and starts the reminder clock.
 */
import { apiClient } from "@/lib/api/client";
import type { OutboundDraft, SentCommunication } from "@/lib/types/communication";
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
}

/**
 * Record a send. Invalidates the draft, the needs list and the activity feed — all three change:
 * the draft becomes a sent message, every need in it moves to REQUESTED, and the send is audited.
 */
export function useSendDraft(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ draftId, recipient, body }: SendDraftInput) =>
      (
        await apiClient.post<SentCommunication>(`${outboundPath(fileId)}/draft/${draftId}/send`, {
          recipient,
          body,
        })
      ).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: outboundDraftQueryKey(fileId) });
      void queryClient.invalidateQueries({ queryKey: needsQueryKey(fileId) });
      void queryClient.invalidateQueries({ queryKey: activityQueryKey(fileId) });
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
