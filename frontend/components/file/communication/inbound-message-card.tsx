"use client";

import { InboundAttachmentRow } from "@/components/file/communication/inbound-attachment";
import { MoveToFile } from "@/components/file/communication/move-to-file";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { canAttachPdf, useConditionRounds } from "@/lib/api/conditions";
import {
  unclaimed,
  useAcceptAttachment,
  useDismissMessage,
  useForwardAttachmentAsSheet,
  useRejectAttachment,
} from "@/lib/api/inbound";
import { getErrorMessage } from "@/lib/errors/api-error";
import { messageTimeShort } from "@/lib/message-time";
import { notifySuccess } from "@/lib/toast";
import type { ConditionRound } from "@/lib/types/conditions";
import type { InboundMessage } from "@/lib/types/inbound";
import { cn } from "@/lib/utils";
import { Mail, MailQuestion, ShieldCheck, ShieldQuestion } from "lucide-react";
import { useState } from "react";

/**
 * The authentication badge (§2.3).
 *
 * `GRAY` IS NOT `PASS`, and the badge must not round it to one. SES returns GRAY most often when a
 * message is signed by a domain that does not match `From:` — precisely the spoofing case — so it
 * reads as "Not verified", the same as a failure.
 */
function AuthBadge({ verdicts }: { verdicts: Record<string, string> }) {
  const dmarc = (verdicts.dmarcVerdict ?? "").toUpperCase();
  if (dmarc === "PASS") {
    return (
      <Badge className="gap-1 border-transparent bg-success/10 text-success hover:bg-success/10">
        <ShieldCheck className="h-3 w-3" aria-hidden />
        Verified sender
      </Badge>
    );
  }
  return (
    <Badge className="gap-1 border-transparent bg-warning/10 text-warning hover:bg-warning/10">
      <ShieldQuestion className="h-3 w-3" aria-hidden />
      Not verified
    </Badge>
  );
}

/**
 * How this message reached this file, in a processor's words. The SIGNAL rather than the confidence:
 * a processor about to accept a document wants to know it came to the file's own address, not that
 * a number was 1.0.
 *
 * EXACTLY THE VALUES THAT EXIST. LP-805 built two — `inbox_token` and `thread_reference` — and LP-1009
 * added `manual`. The first draft of this map had five, inventing copy for rungs 3 to 6 that no message can carry, and
 * spelling rung 2 `references`, which is not the value the server sends. The one real rung-2 message
 * would have fallen through to the generic fallback while the map looked complete.
 *
 * Anything unrecognised falls back rather than rendering a raw enum value, so a rung added later is
 * vague rather than wrong until its label lands here.
 */
export const SIGNAL_LABEL: Record<string, string> = {
  inbox_token: "Sent to this file's address",
  thread_reference: "A reply to a message we sent",
  manual: "Moved to this file by a person",
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
  // written to catch. This used the browser's locale-dependent absolute formatter, beside a timeline
  // showing "2 hours ago" and a modal showing "4 Sep 2026, 14:30" — three formats for the same kind
  // of fact, on one screen, none of which was wrong on its own.
  //
  // The formatter is NAMED rather than quoted, deliberately: the class guard in
  // `lib/message-time.test.ts` is a plain substring scan over this directory, and prose containing
  // the literal token would report the file it had just fixed. It stripped comments to cope with
  // this one sentence, and that strip could be defeated by an unclosed `/*` in a string literal —
  // measured, not supposed. Rewording one comment is cheaper than a regex that can hide real code.
  //
  // `received_at` is when we received the email: since LP-1011 the server sends the row's
  // `created_at`, not the sender-written `Date` header.
  if (!iso) return "Arrival time unknown";
  return `Received ${messageTimeShort(iso)}`;
}

/**
 * One message in the queue: who it is from, whether they authenticated, and what they attached.
 *
 * `fileId` is the loan file this card can accept into, and it is null in the company-level queue,
 * where there is nothing to accept INTO; an unmatched message offers Move to file there instead
 * (LP-1009). Passing the file down rather than reading it off the message means the accept call is
 * scoped by the route the caller is already on.
 */
export function InboundMessageCard({
  message,
  fileId,
  onOpen,
}: {
  message: InboundMessage;
  /** The file whose page this is, or null in the company queue. */
  fileId: string | null;
  /** Open this message's timeline row (LP-1009). Opening is what marks it read. */
  onOpen?: (communicationId: string) => void;
}) {
  const accept = useAcceptAttachment(fileId ?? "");
  const reject = useRejectAttachment(fileId ?? "");
  const useAsSheet = useForwardAttachmentAsSheet(fileId ?? "");
  const busy = accept.isPending || reject.isPending || useAsSheet.isPending;
  const unmatched = unclaimed(message);
  const communicationId = message.communication_id;

  /**
   * The file's rounds, for the two things S1-13 needs that an attachment cannot answer.
   *
   * `enabled` IS ALREADY `Boolean(fileId)`, so the company-level queue fetches nothing — which is
   * also exactly where neither of these may appear: there is no file, so no round to merge into and
   * no round for an attachment to have become.
   */
  const rounds = useConditionRounds(fileId ?? "");
  const roundList = rounds.data ?? [];

  /**
   * The round a forward would merge into, or null to open a new one (S1-13 Must-match).
   *
   * THE NEWEST ROUND, NOT ANY MERGEABLE ONE. The design's condition is "when the file's NEWEST
   * round was pasted and has no PDF yet" — a `find` across the list would offer to merge into an
   * older paste while a newer round sat on top of it, which is a different and wrong question.
   * `roundList` is newest-first, as `list_rounds` orders it and `imported-view` documents it.
   *
   * AND MERGEABILITY IS `canAttachPdf`, NOT "has no bytes". The server refuses on TWO counts —
   * a status outside `draft`/`imported`, and bytes already stored — so asking only the second would
   * offer a merge into a discarded or failed round that answers 409. That predicate is the mirror of
   * the server's rule and already carries the reasoning.
   */
  const newest = roundList[0] ?? null;
  const mergeTarget = newest && canAttachPdf(newest) ? newest : null;

  /** Which round an attachment already became, matched on the id the source recorded. */
  const roundFor = (attachmentId: string): ConditionRound | null =>
    roundList.find((round) =>
      round.sources.some((source) => source.inbound_attachment_id === attachmentId),
    ) ?? null;

  /** The attachment whose attach-or-new question is open, if any. */
  const [askingFor, setAskingFor] = useState<string | null>(null);

  function useAsSheetNow(attachmentId: string, attachToRoundId: string | null) {
    setAskingFor(null);
    useAsSheet.mutate({ attachmentId, attachToRoundId });
  }

  return (
    <article
      id={`email-${message.id}`}
      className="flex scroll-mt-4 flex-col gap-3 rounded-lg border border-input bg-card p-4"
    >
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col gap-1">
          <p
            className={cn(
              "flex items-center gap-1.5 truncate text-sm text-foreground",
              message.unread ? "font-semibold" : "font-medium",
            )}
          >
            {message.unread ? (
              <span
                role="img"
                aria-label="Unread"
                className="h-2 w-2 shrink-0 rounded-full bg-primary"
              />
            ) : null}
            {message.from_address ?? "Sender unknown"}
          </p>
          <p className="truncate text-sm text-muted-foreground">
            {message.subject ?? "No subject"}
          </p>
          {onOpen && communicationId ? (
            <button
              type="button"
              className="w-fit text-xs text-primary underline underline-offset-2"
              onClick={() => onOpen(communicationId)}
            >
              Open
            </button>
          ) : null}
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

      {unmatched && !fileId ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded border border-dashed border-input px-3 py-2">
          <p className="text-xs text-muted-foreground">
            This email could not be matched to a loan file.
          </p>
          <div className="flex items-center gap-2">
            <DismissMessage messageId={message.id} />
            <MoveToFile messageId={message.id} />
          </div>
        </div>
      ) : null}

      {message.attachments.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {message.attachments.map((attachment) => (
            <InboundAttachmentRow
              key={attachment.id}
              fileId={fileId}
              attachment={attachment}
              busy={busy}
              usedAsRound={(() => {
                const round = roundFor(attachment.id);
                return round ? { id: round.id, number: round.round_number } : null;
              })()}
              {...(fileId
                ? {
                    onAccept: () => accept.mutate({ attachmentId: attachment.id }),
                    onAcceptAsCorrespondence: () =>
                      accept.mutate({ attachmentId: attachment.id, asCorrespondence: true }),
                    onReject: () => reject.mutate(attachment.id),
                    // INSIDE THE `fileId` SPREAD, WITH THE OTHERS, AND THAT IS THE POINT OF THE
                    // SPREAD. In the company queue there is no file to open a round on — the
                    // server 404s an unrouted attachment rather than letting one company create a
                    // round from a message no company owns yet. Omitting the callback there makes
                    // the button absent rather than present and failing.
                    // ASKS RATHER THAN ASSUMES (S1-13). Without a merge target this is the
                    // create path exactly as before; with one, choosing silently opened a SECOND
                    // round on a file whose newest round was still waiting for its letter — which
                    // is the outcome a processor almost never wants, and the server would happily
                    // have done it.
                    onUseAsConditionSheet: () =>
                      mergeTarget
                        ? setAskingFor(attachment.id)
                        : useAsSheetNow(attachment.id, null),
                  }
                : {})}
            />
          ))}
        </ul>
      ) : (
        <p className="text-xs text-muted-foreground">No attachments.</p>
      )}

      {/* THE CONFIRM UI IS "May differ" IN THE PACK, BUT THE QUESTION IS NOT. S1-13 requires that
          choosing the action ASKS when the newest round was pasted and has no PDF yet; only the
          shape of the asking is free, and this repo has `Dialog` and no AlertDialog. */}
      <Dialog open={askingFor !== null} onOpenChange={(open) => !open && setAskingFor(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Attach to this round, or start a new one?</DialogTitle>
            <DialogDescription>
              {mergeTarget
                ? `The newest round on this file ${
                    mergeTarget.sources.some((source) => source.kind === "paste")
                      ? "was pasted"
                      : "was typed"
                  } and has no PDF yet. Attaching merges the lender's letter into it — it fills in the letter details and creates no second round.`
                : null}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => askingFor && useAsSheetNow(askingFor, null)}
              disabled={busy}
            >
              Start a new round
            </Button>
            <Button
              onClick={() => askingFor && mergeTarget && useAsSheetNow(askingFor, mergeTarget.id)}
              disabled={busy}
            >
              {mergeTarget?.round_number === null
                ? "Attach to the draft round"
                : `Attach to Round ${mergeTarget?.round_number}`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {accept.isError || reject.isError ? (
        <p className="text-sm text-danger">
          That could not be done. The file may have changed since this page loaded — refresh and try
          again.
        </p>
      ) : null}
      {/* ITS OWN LINE, SHOWING THE SERVER'S SENTENCE, RATHER THAN JOINING THE ONE ABOVE. The
          generic copy — "the file may have changed, refresh and try again" — is a guess, and it is
          the wrong guess for every refusal this action actually produces: the attachment has
          already been used as a condition sheet (409, naming the round that exists), the round it
          would attach to is not on this file, the attachment is quarantined, or the message is
          unrouted. Each names a different next step, and "refresh" is none of them (spec §9.8). */}
      {useAsSheet.isError ? (
        <p className="text-sm text-danger">{getErrorMessage(useAsSheet.error)}</p>
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

/** LP-1011 — take an unmatched email (spam, a stray) off the Inbox. It stays on record. */
function DismissMessage({ messageId }: { messageId: string }) {
  const dismiss = useDismissMessage();
  return (
    <div className="flex flex-col items-end gap-1">
      <Button
        type="button"
        size="sm"
        variant="ghost"
        disabled={dismiss.isPending}
        onClick={() =>
          dismiss.mutate(messageId, {
            onSuccess: () =>
              notifySuccess({ title: "Dismissed", consequence: "It is no longer in the Inbox." }),
          })
        }
      >
        Dismiss
      </Button>
      {/* A 409 when someone moved it first, or a 404: say so, as Move to file does. */}
      {dismiss.isError ? (
        <p className="text-sm text-danger">{getErrorMessage(dismiss.error)}</p>
      ) : null}
    </div>
  );
}
