"use client";

import { InboundAttachmentRow } from "@/components/file/communication/inbound-attachment";
import { Badge } from "@/components/ui/badge";
import { unclaimed, useAcceptAttachment, useRejectAttachment } from "@/lib/api/inbound";
import { messageTimeShort } from "@/lib/message-time";
import type { InboundMessage } from "@/lib/types/inbound";
import { Mail, MailQuestion, ShieldCheck, ShieldQuestion } from "lucide-react";

/**
 * The authentication badge (§2.3).
 *
 * `GRAY` IS NOT `PASS`, and the badge must not round it to one. SES returns GRAY most often when a
 * message is signed by a domain that does not match `From:` — precisely the spoofing case — so it
 * reads as "not verified", the same as a failure, with the raw verdict beside it.
 */
function AuthBadge({ verdicts }: { verdicts: Record<string, string> }) {
  const dmarc = (verdicts.dmarcVerdict ?? "").toUpperCase();
  if (dmarc === "PASS") {
    return (
      <Badge className="gap-1 border-transparent bg-success/10 text-success hover:bg-success/10">
        <ShieldCheck className="h-3 w-3" aria-hidden />
        Sender verified
      </Badge>
    );
  }
  return (
    <Badge className="gap-1 border-transparent bg-warning/10 text-warning hover:bg-warning/10">
      <ShieldQuestion className="h-3 w-3" aria-hidden />
      {dmarc ? `Not verified (${dmarc})` : "Not verified"}
    </Badge>
  );
}

/**
 * How this message reached this file, in a processor's words. The SIGNAL rather than the confidence:
 * a processor about to accept a document wants to know it came to the file's own address, not that
 * a number was 1.0.
 *
 * EXACTLY THE RUNGS THAT EXIST. LP-805 built two — `inbox_token` and `thread_reference` — and the
 * first draft of this map had five, inventing copy for rungs 3 to 6 that no message can carry, and
 * spelling rung 2 `references`, which is not the value the server sends. The one real rung-2 message
 * would have fallen through to the generic fallback while the map looked complete.
 *
 * Anything unrecognised falls back rather than rendering a raw enum value, so a rung added later is
 * vague rather than wrong until its label lands here.
 */
export const SIGNAL_LABEL: Record<string, string> = {
  inbox_token: "Sent to this file's address",
  thread_reference: "A reply to a message we sent",
};

function RoutingNote({ message }: { message: InboundMessage }) {
  if (unclaimed(message)) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
        <MailQuestion className="h-3 w-3" aria-hidden />
        Not matched to a file
      </span>
    );
  }
  const label = message.routing_signal ? SIGNAL_LABEL[message.routing_signal] : undefined;
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
      <Mail className="h-3 w-3" aria-hidden />
      {label ?? "Matched to this file"}
    </span>
  );
}

function receivedLabel(iso: string | null): string {
  // LP-838 — THE THIRD FORMAT ON THIS PAGE, and the one the ticket's class-level statement was
  // written to catch. `toLocaleString()` gave a locale-dependent absolute time beside a timeline
  // showing "2 hours ago" and a modal showing "4 Sep 2026, 14:30" — three formats for the same kind
  // of fact, on one screen, none of which was wrong on its own.
  //
  // `received_at` STAYS the instant, and is not swapped for the timeline's. It is the message's own
  // arrival time; `_message_at` falls back to `created_at` for inbound only to avoid joining
  // `inbound_messages` to order a list, and its own comment says received_at "is the better answer".
  // This card already holds it, so it uses it.
  if (!iso) return "Arrival time unknown";
  return `Received ${messageTimeShort(iso)}`;
}

/**
 * One message in the queue: who it is from, whether they authenticated, and what they attached.
 *
 * ACTIONS ONLY WHEN SOMEBODY OWNS IT. `onFile` is the loan file this card can accept into, and it
 * is null in the company-level queue — where the message has no file, the sender's words have been
 * stripped, and there is nothing to accept INTO. Passing the file down rather than reading it off
 * the message means the accept call is scoped by the route the caller is already on.
 */
export function InboundMessageCard({
  message,
  fileId,
}: {
  message: InboundMessage;
  /** The file whose page this is, or null in the company queue. */
  fileId: string | null;
}) {
  const accept = useAcceptAttachment(fileId ?? "");
  const reject = useRejectAttachment(fileId ?? "");
  const busy = accept.isPending || reject.isPending;
  const hidden = unclaimed(message);

  return (
    <article className="flex flex-col gap-3 rounded-lg border border-input bg-card p-4">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col gap-1">
          <p className="truncate text-sm font-medium text-foreground">
            {hidden ? (
              <span className="italic text-muted-foreground">Sender hidden until claimed</span>
            ) : (
              (message.from_address ?? "Sender unknown")
            )}
          </p>
          <p className="truncate text-sm text-muted-foreground">
            {hidden ? (
              <span className="italic">Subject hidden until claimed</span>
            ) : (
              (message.subject ?? "No subject")
            )}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <AuthBadge verdicts={message.auth_verdicts} />
          <span className="text-xs text-muted-foreground">
            {receivedLabel(message.received_at)}
          </span>
        </div>
      </header>

      <div className="flex flex-wrap items-center gap-3">
        <RoutingNote message={message} />
        {message.is_dsn ? (
          <span className="text-xs text-warning">A delivery failure notice, not a document</span>
        ) : null}
        {message.is_auto_reply ? (
          <span className="text-xs text-muted-foreground">An automatic reply</span>
        ) : null}
      </div>

      {hidden ? (
        <p className="rounded border border-dashed border-input px-3 py-2 text-xs text-muted-foreground">
          This message could not be matched to a loan file, so it is shown to every company and
          nothing the sender wrote is included. Everything appears once somebody claims it.
        </p>
      ) : null}

      {message.attachments.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {message.attachments.map((attachment) => (
            <InboundAttachmentRow
              key={attachment.id}
              fileId={fileId}
              attachment={attachment}
              busy={busy}
              {...(fileId
                ? {
                    onAccept: () => accept.mutate({ attachmentId: attachment.id }),
                    onAcceptAsCorrespondence: () =>
                      accept.mutate({ attachmentId: attachment.id, asCorrespondence: true }),
                    onReject: () => reject.mutate(attachment.id),
                  }
                : {})}
            />
          ))}
        </ul>
      ) : (
        <p className="text-xs text-muted-foreground">No attachments.</p>
      )}

      {accept.isError || reject.isError ? (
        <p className="text-sm text-danger">
          That could not be done. The file may have changed since this page loaded — refresh and try
          again.
        </p>
      ) : null}
      {accept.data?.possible_duplicate ? (
        <p className="text-sm text-warning">
          A document of the same type is already on this file. Both are kept and flagged so you can
          decide which is current.
        </p>
      ) : null}
    </article>
  );
}
