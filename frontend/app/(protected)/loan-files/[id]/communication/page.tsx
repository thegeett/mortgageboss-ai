"use client";

import { InboundMessagesPanel } from "@/components/file/communication/inbound-messages-panel";
import { OutboundDraftPanel } from "@/components/file/communication/outbound-draft-panel";
import { UploadLinkPanel } from "@/components/file/communication/upload-link-panel";
import { useParams } from "next/navigation";

/**
 * Communication — the file's outbound request, and what came back (LP-811b, LP-807).
 *
 * The tab was a Phase 4 placeholder from LP-33 until LP-811b put the outbound draft in it. LP-807
 * adds the other half: the request goes out, the borrower replies, and the reply is reviewed here
 * rather than on a separate screen. LP-815 adds the secure link the request should carry instead of
 * asking for an attachment. LP-812 threads them into one timeline.
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
    </div>
  );
}
