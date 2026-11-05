"use client";

import { InboundMessageCard } from "@/components/file/communication/inbound-message-card";
import { EmptyState } from "@/components/ui/empty-state";
import { unclaimed, useTriageQueue } from "@/lib/api/inbound";

/**
 * The company inbox (LP-807) — this company's mail, and no other company's.
 *
 * A message that matched no file and has no company is not returned here or anywhere else (LP-1008).
 * So "Not matched to a file" appears only when this company has such a row, and has no empty state:
 * "everything has been matched" would be a claim this page cannot see to make.
 */
export default function InboundQueuePage() {
  const { data: messages, isPending, isError } = useTriageQueue();

  if (isPending) {
    return <p className="text-sm text-muted-foreground">Loading the inbox…</p>;
  }
  if (isError) {
    return (
      <p className="text-sm text-danger">The inbox could not be loaded. Refresh to try again.</p>
    );
  }

  const unclaimedMessages = messages.filter(unclaimed);
  const claimed = messages.filter((message) => !unclaimed(message));

  return (
    <div className="flex max-w-3xl flex-col gap-8 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold text-foreground">Inbox</h1>
        <p className="text-sm text-muted-foreground">
          Mail that arrived for this company. Nothing is filed until somebody accepts it.
        </p>
      </header>

      {unclaimedMessages.length > 0 ? (
        <section className="flex flex-col gap-3">
          <h2 className="text-base font-semibold text-foreground">Not matched to a file</h2>
          {unclaimedMessages.map((message) => (
            <InboundMessageCard key={message.id} message={message} fileId={null} />
          ))}
        </section>
      ) : null}

      <section className="flex flex-col gap-3">
        <h2 className="text-base font-semibold text-foreground">Matched to a file</h2>
        {claimed.length === 0 ? (
          <EmptyState kind="structural" title="Nothing matched yet">
            Messages that reached a loan file are reviewed on that file&apos;s Communication tab.
          </EmptyState>
        ) : (
          // fileId is null here too: this page is company-scoped, and accepting belongs on the
          // file's own route where the caller has already proved they own it.
          claimed.map((message) => (
            <InboundMessageCard key={message.id} message={message} fileId={null} />
          ))
        )}
      </section>
    </div>
  );
}
