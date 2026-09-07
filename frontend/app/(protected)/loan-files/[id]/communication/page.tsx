"use client";

import { OutboundDraftPanel } from "@/components/file/communication/outbound-draft-panel";
import { useParams } from "next/navigation";

/**
 * Communication — the file's outbound document request (LP-811b).
 *
 * The tab has existed as a Phase 4 placeholder since LP-33. This is the first thing to occupy it:
 * the accumulating request a processor reviews, edits, takes to their mail client, and records as
 * sent. LP-812 adds the timeline around it, LP-818 replies.
 */
export default function CommunicationPage() {
  const { id } = useParams<{ id: string }>();
  return <OutboundDraftPanel fileId={id} />;
}
