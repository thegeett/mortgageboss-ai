"use client";

import { ComposeDraftButton } from "@/components/file/communication/compose-draft-dialog";
import { ComposeRequestButton } from "@/components/file/communication/compose-request-button";
import { InboundMessagesPanel } from "@/components/file/communication/inbound-messages-panel";
import { TimelinePanel } from "@/components/file/communication/timeline-panel";
import { UploadLinkPanel } from "@/components/file/communication/upload-link-panel";
import { useCapabilities } from "@/lib/api/capabilities";
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
 * at the top is now the modal a row opens.
 *
 * LP-857 — THE PAGE DOES NOT OFFER WHAT THE VERSION CANNOT DO. *"In this version I want to limit to
 * draft only... No receiving, sending, secure upload link, reply email and all."* Half the confusion
 * in the screen this replaces came from controls that existed as an interface with nothing behind
 * them — `mail_transport` is the standing example — and a processor cannot tell a feature that is
 * broken from one that was never wired.
 */
export default function CommunicationPage() {
  const { id } = useParams<{ id: string }>();
  // FALSE WHILE LOADING AND FALSE ON ERROR. The safe default is the restrictive one: a panel that
  // flashed in before the answer arrived would be a control a processor could click on a version
  // where the thing behind it does not exist.
  const receiving = useCapabilities().data?.receiving ?? false;

  return (
    <div className="flex flex-col gap-8">
      {/* LP-857 — TWO BUTTONS, AND THE THIRD IS NOT MISSING. "Write to another party" was the only
          place a missing address could be added, so the button went and the FORM was lifted: a
          party draft with no address is still created, says "cannot be sent yet" on the list, and
          carries the address form inside it. LP-820 measured why that matters — of 166 document
          types, 13 across title, agent, CPA, insurer and employer had no address anywhere in the
          schema, and the blocker was never "no way to compose", it was "nobody to send to".

          Asking in the draft asks the person who knows, at the moment it is stopping them, instead
          of in a panel nobody visits. */}
      <div className="flex items-center justify-end gap-2">
        {/* LP-833 — asking for a document no rule flagged. Until this, a draft could come only from
            a FINDING: a processor who knew what they needed could add a needs item by hand and
            nothing drafted from it. */}
        {/* LP-856 — a draft with no documents behind it. Outline to "Request documents"' primary,
            which is Screen 1's order — requesting is the common act and writing a free message is
            the occasional one. */}
        <ComposeDraftButton fileId={id} />
        <ComposeRequestButton fileId={id} />
      </div>
      <TimelinePanel fileId={id} />
      {/* LP-857 — FLAGGED OUT, NOT DELETED. LP-815 and LP-807 are written, reviewed and tested, and
          they return in the phase that brings sending and receiving back; deleting them would buy
          nothing and cost the review that already happened. Their tests still run — a flag that
          rots is a deletion with extra steps. */}
      {receiving ? (
        <>
          {/* LP-815 — BETWEEN the request and what came back, because that is where it is used. */}
          <UploadLinkPanel fileId={id} />
          <InboundMessagesPanel fileId={id} />
        </>
      ) : null}
    </div>
  );
}
