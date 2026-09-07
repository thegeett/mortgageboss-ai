"use client";

import { InboundMessagesPanel } from "@/components/file/communication/inbound-messages-panel";
import { OutboundDraftPanel } from "@/components/file/communication/outbound-draft-panel";
import { useParams } from "next/navigation";

/**
 * Communication — the file's outbound request, and what came back (LP-811b, LP-807).
 *
 * The tab was a Phase 4 placeholder from LP-33 until LP-811b put the outbound draft in it. LP-807
 * adds the other half: the request goes out, the borrower replies, and the reply is reviewed here
 * rather than on a separate screen. LP-812 threads the two into one timeline.
 */
export default function CommunicationPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <div className="flex flex-col gap-8">
      <OutboundDraftPanel fileId={id} />
      <InboundMessagesPanel fileId={id} />
    </div>
  );
}
