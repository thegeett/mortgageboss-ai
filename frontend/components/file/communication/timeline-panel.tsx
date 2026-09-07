"use client";

/**
 * The communication timeline (LP-812) — everything that happened on this file, once each.
 *
 * ONE ROW PER EVENT, AND THE SERVER DECIDES WHICH. A single inbound arrival writes three rows in
 * three tables; `services/timeline.py` settles that the `Communication` is the timeline's and drops
 * the activity entry that describes it. Nothing here re-merges or re-filters — the pills are a query
 * parameter, because two definitions of "sent" is how one of them starts showing drafts.
 *
 * THE INBOX ADDRESS SITS ON THIS SCREEN because spec 4.3 asks for it here: a processor noticing that
 * nothing has arrived is already looking at the timeline, and that is the moment she wants the
 * address to tell a borrower. It is a bearer capability, not a label — anyone holding it can post
 * documents into this file — so it is shown, copyable, and never linked.
 */

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { useTimeline } from "@/lib/api/timeline";
import type { TimelineEntry, TimelineFilter } from "@/lib/types/timeline";
import { formatDistanceToNow } from "date-fns";
import { Check, Copy, FileText, Mail, MailOpen, PenLine, TriangleAlert } from "lucide-react";
import { useState } from "react";

const PILLS: { value: TimelineFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "sent", label: "Sent" },
  { value: "received", label: "Received" },
  { value: "drafts", label: "Drafts" },
  { value: "activity", label: "Activity" },
];

/**
 * The icon for a row, which encodes what happened as a second channel beside the words.
 *
 * FAILED HAS ITS OWN. "Sent" and "sent, and bounced" are not the same event — LP-819 made that its
 * own activity type for the same reason — and a processor scanning a column of identical envelopes
 * will not notice the one that did not arrive.
 */
function EntryIcon({ entry }: { entry: TimelineEntry }) {
  if (entry.kind === "activity")
    return <FileText className="h-4 w-4 text-muted-foreground" aria-hidden />;
  if (entry.status === "failed")
    return <TriangleAlert className="h-4 w-4 text-danger" aria-hidden />;
  if (entry.status === "draft" || entry.status === "queued") {
    return <PenLine className="h-4 w-4 text-muted-foreground" aria-hidden />;
  }
  if (entry.direction === "inbound")
    return <MailOpen className="h-4 w-4 text-success" aria-hidden />;
  return <Mail className="h-4 w-4 text-primary" aria-hidden />;
}

function when(iso: string): string {
  try {
    return formatDistanceToNow(new Date(iso), { addSuffix: true });
  } catch {
    return "at an unknown time";
  }
}

export function TimelinePanel({ fileId }: { fileId: string }) {
  const [filter, setFilter] = useState<TimelineFilter>("all");
  const { data, isPending, isError } = useTimeline(fileId, filter);
  const [copied, setCopied] = useState(false);

  async function copyAddress(address: string) {
    await navigator.clipboard.writeText(address);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  }

  return (
    <section className="flex flex-col gap-3">
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-base font-semibold text-foreground">History</h2>
          {data ? (
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                This file&apos;s address
              </span>
              <code className="rounded bg-muted px-2 py-0.5 font-mono text-xs">
                {data.inbox_address}
              </code>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => void copyAddress(data.inbox_address)}
              >
                {copied ? (
                  <Check className="h-3.5 w-3.5" aria-hidden />
                ) : (
                  <Copy className="h-3.5 w-3.5" aria-hidden />
                )}
              </Button>
            </div>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-1" role="tablist" aria-label="Filter the history">
          {PILLS.map((pill) => (
            <button
              key={pill.value}
              type="button"
              role="tab"
              aria-selected={filter === pill.value}
              onClick={() => setFilter(pill.value)}
              className={
                filter === pill.value
                  ? "rounded-full bg-primary px-3 py-0.5 text-xs font-medium text-primary-foreground"
                  : "rounded-full border border-input px-3 py-0.5 text-xs text-muted-foreground hover:text-foreground"
              }
            >
              {pill.label}
            </button>
          ))}
        </div>
      </header>

      {isPending ? (
        <p className="text-sm text-muted-foreground">Loading this file&apos;s history…</p>
      ) : isError ? (
        <p className="text-sm text-danger">
          The history could not be loaded. Refresh to try again.
        </p>
      ) : data.entries.length === 0 ? (
        // "filtered" when a pill is on, "nothing-yet" otherwise — they mean different things, and
        // telling a processor who filtered to Drafts that nothing has ever happened is false.
        filter === "all" ? (
          <EmptyState kind="nothing-yet" title="Nothing has happened yet">
            Messages you send and replies that arrive appear here, alongside what changes on the
            file.
          </EmptyState>
        ) : (
          <EmptyState kind="filtered" title={`Nothing in ${filter}`}>
            There is history on this file; this filter hides it.
          </EmptyState>
        )
      ) : (
        <ul className="flex flex-col">
          {data.entries.map((entry) => (
            <li
              key={`${entry.kind}-${entry.id}`}
              className="flex items-start gap-3 border-t border-border py-2 text-sm first:border-t-0"
            >
              <span className="mt-0.5 shrink-0">
                <EntryIcon entry={entry} />
              </span>
              <div className="flex min-w-0 flex-1 flex-col">
                <span className="text-foreground">{entry.summary}</span>
                {entry.subject ? (
                  <span className="truncate text-xs text-muted-foreground">{entry.subject}</span>
                ) : null}
                {entry.counterparty ? (
                  <span className="truncate text-xs text-muted-foreground">
                    {entry.direction === "inbound" ? "From" : "To"} {entry.counterparty}
                  </span>
                ) : null}
                {entry.attachments.length > 0 ? (
                  // THE MANIFEST. Sender-written text, rendered as text — no title, no href, and
                  // nothing built into a URL from it.
                  <ul className="mt-1 flex flex-wrap gap-1">
                    {entry.attachments.map((name) => (
                      <li
                        key={name}
                        className="max-w-full truncate rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground"
                      >
                        {name}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
              <span className="shrink-0 text-xs text-muted-foreground">{when(entry.at)}</span>
            </li>
          ))}
        </ul>
      )}
      {data?.truncated ? (
        // NOT A SILENT CAP. There is no pagination yet, so the entries dropped are the OLDEST —
        // a page that looks complete and is not. A processor hunting the message that started a
        // thread would otherwise find a whole-looking timeline without it and conclude it never
        // arrived.
        <p className="border-t border-border pt-2 text-xs text-muted-foreground">
          Older entries are not shown — this file has more history than fits on one page.
        </p>
      ) : null}
    </section>
  );
}
