"use client";

import { InboundMessageCard } from "@/components/file/communication/inbound-message-card";
import { EmptyState } from "@/components/ui/empty-state";
import { unclaimed, useTriageQueue } from "@/lib/api/inbound";

/**
 * The company inbox (LP-807) — everything awaiting a decision, including the mail nobody owns.
 *
 * WHY THIS PAGE EXISTS AT ALL. A message that could not be matched to a loan file has no
 * `company_id`, because LP-805 refuses to guess one from the sender. It therefore cannot appear on
 * any file's tab, and §2.2's rule is that "confidence gates auto-acceptance, never visibility" — so
 * it has to be visible somewhere, and this is the somewhere.
 *
 * The honest consequence is that an unclaimed message is visible to EVERY company, which is why the
 * server returns it stripped of the sender, the subject and both filenames, and why no thumbnail
 * can be fetched for it. The card renders those nulls as a state rather than as missing data.
 *
 * Claiming — moving an unrouted message onto a file — is the one operation here that would cross a
 * tenant boundary, and it is deliberately not built yet.
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

      <section className="flex flex-col gap-3">
        <h2 className="text-base font-semibold text-foreground">Not matched to a file</h2>
        {unclaimedMessages.length === 0 ? (
          <EmptyState kind="structural" title="Everything has been matched">
            Mail that cannot be matched to a loan file waits here. There is none.
          </EmptyState>
        ) : (
          unclaimedMessages.map((message) => (
            <InboundMessageCard key={message.id} message={message} fileId={null} />
          ))
        )}
      </section>

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
