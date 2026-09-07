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

import { MessageDialog } from "@/components/file/communication/message-dialog";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { fetchReplyContext, useMarkRead, useReply, useSetImportant } from "@/lib/api/messages";
import { useTimeline } from "@/lib/api/timeline";
import type { TimelineEntry, TimelineFilter } from "@/lib/types/timeline";
import { formatDistanceToNow } from "date-fns";
import { Check, Copy, Mail, MailOpen, PenLine, Reply, Star, TriangleAlert } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

const PILLS: { value: TimelineFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "sent", label: "Sent" },
  { value: "received", label: "Received" },
  { value: "drafts", label: "Drafts" },
  // LP-825 — NO "Activity" PILL. It matched activity rows, and the timeline no longer has any: the
  // file's document, DTI and field history is on Recent activity, which is what it always
  // described. A pill that answers "Nothing in activity" on every file is a broken control.
];

/**
 * The icon for a row, which encodes what happened as a second channel beside the words.
 *
 * FAILED HAS ITS OWN. "Sent" and "sent, and bounced" are not the same event — LP-819 made that its
 * own activity type for the same reason — and a processor scanning a column of identical envelopes
 * will not notice the one that did not arrive.
 */
function EntryIcon({ entry }: { entry: TimelineEntry }) {
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

/**
 * The per-row actions spec 4.3 asks for: reply, mark important, and read state.
 *
 * REPLY ONLY ON AN ARRIVED MESSAGE. Replying to our own would address it to whoever we sent it to,
 * thread it into their conversation, and read to them as us answering ourselves — the server refuses
 * it, and offering a button the server refuses is a worse way to learn that.
 */
function MessageActions({
  fileId,
  entry,
  replying,
  onReply,
}: {
  fileId: string;
  entry: TimelineEntry;
  replying: boolean;
  onReply: () => void;
}) {
  const important = useSetImportant(fileId);
  const read = useMarkRead(fileId);
  const canReply = entry.direction === "inbound";

  return (
    <>
      <Button
        size="sm"
        variant="ghost"
        aria-label={entry.is_important ? "Remove the flag" : "Mark important"}
        disabled={important.isPending}
        onClick={() =>
          important.mutate({ communicationId: entry.id, important: !entry.is_important })
        }
      >
        <Star
          className={entry.is_important ? "h-3.5 w-3.5 fill-warning text-warning" : "h-3.5 w-3.5"}
          aria-hidden
        />
      </Button>
      {canReply ? (
        <>
          <Button
            size="sm"
            variant="ghost"
            // REVERSIBLE. A processor who opens something at the end of the day and cannot deal
            // with it needs to put it back; a one-way flag makes the badge a thing to get rid of
            // rather than a thing to act on.
            aria-label={entry.unread ? "Mark read" : "Mark unread"}
            disabled={read.isPending}
            onClick={() => read.mutate({ communicationId: entry.id, read: entry.unread })}
          >
            {entry.unread ? (
              <MailOpen className="h-3.5 w-3.5" aria-hidden />
            ) : (
              <Mail className="h-3.5 w-3.5" aria-hidden />
            )}
          </Button>
          <Button size="sm" variant="ghost" aria-label="Reply" onClick={onReply}>
            <Reply className={replying ? "h-3.5 w-3.5 text-primary" : "h-3.5 w-3.5"} aria-hidden />
          </Button>
        </>
      ) : null}
    </>
  );
}

/**
 * The reply box.
 *
 * THE RECIPIENT IS SHOWN, NOT EDITED. It comes from the stored inbound message and is not a
 * processor's to change: a reply sent elsewhere would still be threaded to this conversation and
 * would read, to whoever received it, as part of it.
 *
 * AND SAVING MAKES A DRAFT, NOT A SEND. The copy says so, because a button labelled "Reply" that
 * silently transmitted would be the one outbound message in this product with no guardrails — and
 * one that silently did NOT would be worse.
 */
function ReplyBox({
  fileId,
  entry,
  onDone,
}: {
  fileId: string;
  entry: TimelineEntry;
  onDone: () => void;
}) {
  const [body, setBody] = useState("");
  const [context, setContext] = useState<{ recipient: string; subject: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reply = useReply(fileId);

  // Fetched once when the box opens. Not a query, because it is read exactly once per open and a
  // cached answer would go stale against a message whose sender changed under it.
  //
  // AN EFFECT, NOT A RENDER-PHASE CALL, and the difference is not stylistic. The guard was
  // `context === null`, and the fetch is async — so ANY re-render while the response is outstanding
  // re-fires it, and typing in the textarea below re-renders on every keystroke. Measured: one
  // fetch on open, THREE after two keystrokes with the response still pending. A processor who
  // starts typing before it lands is the ordinary case, not a contrived one.
  //
  // This is not the LP-811b pattern. That one DERIVES STATE FROM PROPS during render, which React
  // documents and this codebase already uses. This performs a side effect, which is what an effect
  // is for — and the dependency list here is honest rather than suppressed.
  useEffect(() => {
    let live = true;
    void fetchReplyContext(fileId, entry.id)
      .then((next) => {
        if (live) setContext(next);
      })
      .catch(() => {
        if (live) setError("This message cannot be replied to.");
      });
    return () => {
      live = false;
    };
  }, [fileId, entry.id]);

  if (error) return <p className="mt-2 text-xs text-danger">{error}</p>;

  return (
    <div className="mt-2 flex flex-col gap-2 rounded border border-input bg-background p-2">
      <p className="text-xs text-muted-foreground">
        {context ? (
          <>
            To {context.recipient} · {context.subject}
          </>
        ) : (
          "Preparing…"
        )}
      </p>
      <textarea
        className="min-h-20 w-full rounded border border-input bg-background p-2 text-sm"
        value={body}
        onChange={(event) => setBody(event.target.value)}
        placeholder="Write your reply…"
        aria-label="Reply body"
      />
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          disabled={!body.trim() || reply.isPending || context === null}
          onClick={() =>
            reply.mutate(
              { communicationId: entry.id, body },
              {
                onSuccess: () => {
                  setBody("");
                  onDone();
                },
                onError: () => setError("The reply could not be saved."),
              },
            )
          }
        >
          Save reply
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <span className="text-xs text-muted-foreground">
          Saved as a draft — send it from the document request above.
        </span>
      </div>
    </div>
  );
}

/** What a processor calls each disposition. An unknown value renders as itself rather than as
 *  nothing — a manifest that silently drops the answer is what this exists to stop. */
const ATTACHMENT_DISPOSITION: Record<string, string> = {
  pending: "not yet accepted",
  accepted: "accepted",
  correspondence: "kept as correspondence",
  rejected: "rejected",
};

export function TimelinePanel({ fileId }: { fileId: string }) {
  const [filter, setFilter] = useState<TimelineFilter>("all");
  const { data, isPending, isError } = useTimeline(fileId, filter);
  const [copied, setCopied] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  // LP-829 — which message the dialog is showing. Separate from `open`, which is the inline reply
  // box: a processor reading a message and a processor answering one are different acts, and
  // sharing the state would make opening one close the other.
  //
  // LP-831 — SEEDED FROM THE URL, so a draft is a thing that can be linked to. LP-837's header
  // popover navigates here and expects the modal to be open on arrival; landing on the list with it
  // shut looks exactly like a mis-click, which is the way that feature fails quietly. Reading it
  // here rather than retrofitting later also makes the modal's open state something a processor can
  // send a colleague.
  const searchParams = useSearchParams();
  // OPTIONAL, because `useSearchParams()` is null outside a router context — which is not only a
  // test artefact: it is also the value during a static render. A deep link is a convenience, and
  // the panel has to render without one.
  const linkedDraft = searchParams?.get("draft") ?? null;
  const [openMessage, setOpenMessage] = useState<string | null>(linkedDraft);
  // Tracked rather than compared against `openMessage`: after a processor CLOSES the linked message
  // the parameter is still in the URL, and re-opening it on the next render would make the dialog
  // impossible to dismiss.
  const [seededFromUrl, setSeededFromUrl] = useState<string | null>(linkedDraft);
  if (linkedDraft !== seededFromUrl) {
    setSeededFromUrl(linkedDraft);
    setOpenMessage(linkedDraft);
  }

  async function copyAddress(address: string) {
    await navigator.clipboard.writeText(address);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  }

  return (
    <section className="flex flex-col gap-3">
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold text-foreground">History</h2>
            {/* THE BADGE. §C.5: "without the badge the queue is pull-only and an evening reply sits
                unseen until she happens to open the tab." Counted over the WHOLE file, so it does
                not shrink when a pill is clicked. */}
            {data && data.unread_count > 0 ? (
              <span
                className="rounded-full bg-primary px-2 py-0.5 text-xs font-medium text-primary-foreground"
                aria-label={`${data.unread_count} unread`}
              >
                {data.unread_count} unread
              </span>
            ) : null}
          </div>
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
                {/* LP-829 — THE SUMMARY IS THE HANDLE. A whole-row click would swallow the reply and
                    flag controls beside it, and a separate "open" affordance would be a second thing
                    to find; the line naming the message is what a processor is already reading when
                    they want to see it. A button, not a div with a handler, so it is reachable from
                    the keyboard and announced as something that does anything at all. */}
                <button
                  type="button"
                  onClick={() => setOpenMessage(entry.id)}
                  className="text-left hover:underline"
                >
                  <span
                    className={entry.unread ? "font-semibold text-foreground" : "text-foreground"}
                  >
                    {entry.summary}
                    {entry.is_important ? (
                      <Star
                        className="ml-1 inline h-3.5 w-3.5 fill-warning text-warning"
                        aria-label="Important"
                      />
                    ) : null}
                  </span>
                </button>
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
                    {entry.attachments.map((attachment) => (
                      <li
                        key={attachment.name}
                        className="max-w-full truncate rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground"
                      >
                        {attachment.name}
                        {/* LP-825 REVIEW — WHAT BECAME OF IT, beside the name. The manifest was
                            names alone, which reads the same whether a document was accepted into
                            the file or is still sitting there unlooked-at. The sentence that used
                            to answer it ("A document arrived by email and was accepted") was an
                            activity row, and LP-825 stopped this timeline reading activity. */}
                        <span className="ml-1 text-[11px] text-foreground-2">
                          ·{" "}
                          {ATTACHMENT_DISPOSITION[attachment.disposition] ?? attachment.disposition}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : null}
                {open === entry.id ? (
                  <ReplyBox fileId={fileId} entry={entry} onDone={() => setOpen(null)} />
                ) : null}
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <span className="text-xs text-muted-foreground">{when(entry.at)}</span>
                {entry.kind === "message" ? (
                  <MessageActions
                    fileId={fileId}
                    entry={entry}
                    replying={open === entry.id}
                    onReply={() => setOpen(open === entry.id ? null : entry.id)}
                  />
                ) : null}
              </div>
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
      <MessageDialog fileId={fileId} messageId={openMessage} onClose={() => setOpenMessage(null)} />
    </section>
  );
}
