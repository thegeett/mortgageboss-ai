"use client";

import { InboundMessagesPanel } from "@/components/file/communication/inbound-messages-panel";
import { PartyRequestsPanel } from "@/components/file/communication/party-requests-panel";
import { TimelinePanel } from "@/components/file/communication/timeline-panel";
import { UploadLinkPanel } from "@/components/file/communication/upload-link-panel";
import { useParams } from "next/navigation";

/**
 * Communication — the file's mailbox (LP-831).
 *
 * The tab was a Phase 4 placeholder from LP-33 until LP-811b put the outbound draft in it. LP-807
 * adds the other half: the request goes out, the borrower replies, and the reply is reviewed here
 * rather than on a separate screen. LP-815 adds the secure link the request should carry instead of
 * asking for an attachment.
 *
 * LP-831 turns it into a mailbox: the message list leads, and the compose form that used to sit open
 * at the top is now the modal a row opens. The panels below it are the two things still waiting to
 * be folded in — the secure link (LP-834) and the other parties (LP-835).
 */
export default function CommunicationPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <div className="flex flex-col gap-8">
      {/* LP-831 — THE LIST LEADS, and the compose form is gone from the page.
          `OutboundDraftPanel` was a full editor open at all times, which works while a file has ONE
          draft. LP-832 makes several the ordinary state: a request creates a new draft carrying
          everything outstanding, and the older ones stay. A page with one form on it cannot show
          that, and it could never show a PARTY draft at all — `get_open_draft` filters on the
          borrower's template key, which is why a title company's request was built and no screen
          could send it.
          A list has no template filter to be wrong about. Every draft is reachable, and the modal
          it opens is the one editor. */}
      <TimelinePanel fileId={id} />
      {/* LP-815 — BETWEEN the request and what came back, because that is where it is used: the
          processor composes the request above, and the link is what the request should carry
          instead of asking for an attachment. */}
      <UploadLinkPanel fileId={id} />
      {/* LP-820 — after the borrower's request and before what came back. The borrower is who a
          processor asks first; the other parties are the ones whose requests had nowhere to go. */}
      <PartyRequestsPanel fileId={id} />
      <InboundMessagesPanel fileId={id} />
    </div>
  );
}
