"use client";

import { InboundMessagesPanel } from "@/components/file/communication/inbound-messages-panel";
import { OutboundDraftPanel } from "@/components/file/communication/outbound-draft-panel";
import { TimelinePanel } from "@/components/file/communication/timeline-panel";
import { UploadLinkPanel } from "@/components/file/communication/upload-link-panel";
import { useParams } from "next/navigation";

/**
 * Communication — the file's outbound request, and what came back (LP-811b, LP-807).
 *
 * The tab was a Phase 4 placeholder from LP-33 until LP-811b put the outbound draft in it. LP-807
 * adds the other half: the request goes out, the borrower replies, and the reply is reviewed here
 * rather than on a separate screen. LP-815 adds the secure link the request should carry instead of
 * asking for an attachment. LP-812 adds the history below them — one row per event, with the
 * activity entries that merely describe a message dropped, so a single arrival appears once.
 */
export default function CommunicationPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <div className="flex flex-col gap-8">
      <OutboundDraftPanel fileId={id} />
      {/* LP-815 — BETWEEN the request and what came back, because that is where it is used: the
          processor composes the request above, and the link is what the request should carry
          instead of asking for an attachment. */}
      <UploadLinkPanel fileId={id} />
      <InboundMessagesPanel fileId={id} />
      {/* LP-812 — LAST, and that is the order of the work: compose the request, offer the secure
          link, triage what came back, then look at the whole history. The panels above are the two
          things a processor DOES; this is the record of what has been done. */}
      <TimelinePanel fileId={id} />
    </div>
  );
}
