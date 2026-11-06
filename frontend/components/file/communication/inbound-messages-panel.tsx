"use client";

import { InboundMessageCard } from "@/components/file/communication/inbound-message-card";
import { EmptyState } from "@/components/ui/empty-state";
import { useFileMessages } from "@/lib/api/inbound";
import { useEffect } from "react";

/**
 * What arrived for this file (LP-807).
 *
 * Sits BELOW the outbound draft on the same tab, because that is the order of the work: a processor
 * asks for documents, then the documents come back. Two tabs would separate a request from its
 * reply, which is the one pairing this feature exists to keep together.
 */
export function InboundMessagesPanel({
  fileId,
  onOpen,
}: {
  fileId: string;
  /** Open this message's timeline row in the reading pane (LP-1009). */
  onOpen?: (communicationId: string) => void;
}) {
  const { data: messages, isPending, isError } = useFileMessages(fileId);

  // LP-1009 — a document's "Email · from …" label links to `#email-<id>`, and this content arrives
  // after the browser has looked for that anchor.
  useEffect(() => {
    if (!messages || !window.location.hash.startsWith("#email-")) return;
    document.getElementById(window.location.hash.slice(1))?.scrollIntoView?.();
  }, [messages]);

  if (isPending) {
    return <p className="text-sm text-muted-foreground">Loading what has arrived…</p>;
  }
  if (isError) {
    return (
      <p className="text-sm text-danger">
        Incoming mail could not be loaded. Refresh to try again.
      </p>
    );
  }
  if (messages.length === 0) {
    return (
      // "nothing-yet", not "structural": mail genuinely arrives here, and the one thing that fills
      // it is telling the borrower the address.
      <EmptyState kind="nothing-yet" title="Nothing has arrived yet">
        Replies to this file&apos;s address land here for you to review before anything is filed.
        The address is on the document request above.
      </EmptyState>
    );
  }

  return (
    <section className="flex flex-col gap-3">
      <header className="flex flex-col gap-1">
        <h2 className="text-base font-semibold text-foreground">Received</h2>
        <p className="text-sm text-muted-foreground">
          Nothing is filed until you accept it. {messages.length}{" "}
          {messages.length === 1 ? "message" : "messages"}.
        </p>
      </header>
      {messages.map((message) => (
        <InboundMessageCard
          key={message.id}
          message={message}
          fileId={fileId}
          {...(onOpen ? { onOpen } : {})}
        />
      ))}
    </section>
  );
}
