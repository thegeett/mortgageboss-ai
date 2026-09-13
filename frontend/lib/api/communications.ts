/**
 * The outbound draft (LP-811b) — read the file's open document request, and record that it was sent.
 *
 * NOTHING HERE TRANSMITS. M1's send path is copy-and-send: the processor puts the text into their
 * own mail client, or opens a `mailto:` link. "Send" means *record that it went out* — which is what
 * moves every requested document to REQUESTED and starts the reminder clock.
 */
import { apiClient } from "@/lib/api/client";
import type { ConflictChoice } from "@/lib/api/draft-conflict";
import { invalidateDraftViews } from "@/lib/api/draft-views";
import type { MessageDetail, OutboundDraft, SentCommunication } from "@/lib/types/communication";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";

const API_V1 = "/api/v1";

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
export interface ComposeRequestInput {
  documentTypes: string[];
  onConflict?: ConflictChoice;
}

/** One party's share of a compose — who it is to, and how much (LP-852). */
export interface DraftMade {
  party: string;
  needs_added: number;
}

export interface ComposedRequest {
  draft_id: string | null;
  needs_added: number;
  /** LP-852 — per party, because the toast has to name one. Only parties that got something. */
  drafts: DraftMade[];
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
    mutationFn: async (input: ComposeRequestInput) =>
      (
        await apiClient.post<ComposedRequest>(`${outboundPath(fileId)}/compose`, {
          document_types: input.documentTypes,
          // LP-851 — the processor's answer to the open-draft dialog. Absent means nobody has been
          // asked, and the server refuses with a 409 rather than writing anything.
          on_conflict: input.onConflict ?? null,
        })
      ).data,
    onSuccess: () => {
      invalidateDraftViews(queryClient, fileId);
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
      invalidateDraftViews(queryClient, fileId);
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

export interface SavedDraft {
  id: string;
  body_format: "plain" | "html";
  subject: string | null;
}

export interface SaveDraftBodyInput {
  draftId: string;
  /** HTML, as the editor produced it. Sanitised server-side against the allowlist. */
  body: string;
  subject?: string;
}

/**
 * Store the processor's own words on an unsent draft (LP-853).
 *
 * EVERY CALL IS AN EDIT. The server flips `body_format` to `html` on the act of posting, because a
 * save from a person IS the edit — so a caller that posted on open, or on focus, would record an
 * edit that never happened and LP-851 would warn about losing changes nobody made. Acceptance 2 is
 * "focus is not an edit", and this is the side that has to keep it: `message-dialog` posts only
 * when the editor's content has actually moved.
 *
 * THE CACHE IS PATCHED RATHER THAN INVALIDATED. Refetching mid-typing would hand the editor a body
 * from the server while a processor is still writing into it, which is the re-seed LP-831 keyed on
 * message identity to avoid. Only the format and the subject are written back; the body on screen
 * is already the newest copy.
 */
export function useSaveDraftBody(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: SaveDraftBodyInput) =>
      (
        await apiClient.put<SavedDraft>(`${outboundPath(fileId)}/draft/${input.draftId}/body`, {
          body: input.body,
          subject: input.subject ?? null,
        })
      ).data,
    onSuccess: (saved) => {
      queryClient.setQueryData<MessageDetail>(messageQueryKey(fileId, saved.id), (previous) =>
        previous
          ? { ...previous, body_format: saved.body_format, subject: saved.subject }
          : previous,
      );
      // The list row says `Draft · edited · 2m` (LP-852), which is this fact.
      invalidateDraftViews(queryClient, fileId);
    },
  });
}

/** A ✦ polish proposal, or the reason there is none (LP-856). */
export interface PolishResult {
  polished: string | null;
  refusal: string | null;
}

/**
 * Ask the model to tidy the processor's own words.
 *
 * IT PROPOSES; IT DOES NOT REPLACE. Nothing is written — this returns text the dialog shows beside
 * the original, and accepting it is a separate save. A rewrite that landed on save would be a
 * message going out in words nobody read, and the processor is the one who will be asked about
 * those words later.
 *
 * A REFUSAL IS AN ORDINARY OUTCOME, not an error: `email_draft_enabled` is off in every environment,
 * so `refusal: "unavailable"` is what a processor gets today and the button has to say so.
 */
export function usePolishDraft(fileId: string) {
  return useMutation({
    mutationFn: async (input: { draftId: string; body: string }) =>
      (
        await apiClient.post<PolishResult>(
          `${outboundPath(fileId)}/draft/${input.draftId}/polish`,
          { body: input.body },
        )
      ).data,
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
      // LP-840 — one helper, so a mutation that changes a draft cannot refresh a different list
      // from the one a processor is looking at.
      invalidateDraftViews(queryClient, fileId);
      // AND THE MESSAGE ITSELF: the modal that just sent it is showing a row that is no longer a
      // draft.
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
