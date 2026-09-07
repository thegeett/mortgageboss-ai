"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useMessageDetail, useSendDraft } from "@/lib/api/communications";
import { format } from "date-fns";
import { Send } from "lucide-react";
import { useState } from "react";

/**
 * One message, opened from the timeline (LP-829).
 *
 * LP-831 — NOW THE ONLY EDITOR, WHICH IS WHY THE ARGUMENT FOR READ-ONLY NO LONGER APPLIES.
 *
 * LP-829 made this a reader on the reasoning that `OutboundDraftPanel` already owned editing on the
 * same page, and two components holding separate local state for one body means whichever saves
 * last wins with nothing on screen to say so. That reasoning was right and its premise is gone: the
 * panel is off the page, because a compose form open at all times works only while a file has ONE
 * draft, and LP-832 makes several the ordinary state.
 *
 * So the rule stands and its application moves. Exactly one editor, and it is here.
 *
 * WHAT STAYS READ-ONLY, and this is not a limitation:
 *   • a SENT message — LP-821's evidence record must not change after the fact;
 *   • an INBOUND message — a borrower's words are not ours to rewrite.
 * `is_editable` comes from the server rather than being re-derived here, so the screen and the send
 * path cannot disagree about what may be edited.
 *
 * A PARTY DRAFT IS EDITABLE AND SENDABLE HERE, and that closes a defect rather than adding a
 * feature. `party_requests` builds drafts for the title company, the agent, the lender, the CPA, the
 * insurer and the employer; `get_open_draft` filters on the BORROWER's template key, so the panel
 * never showed one — while the party panel's own success message said "Send it from the document
 * request above", where the draft above is the borrower's. A processor following that instruction
 * mailed the borrower believing they had contacted the title company. `send_draft` takes a draft id
 * and has never cared which template rendered it; the missing piece was always a screen.
 */
function when(iso: string): string {
  try {
    return format(new Date(iso), "d MMM yyyy, HH:mm");
  } catch {
    return iso;
  }
}

export function MessageDialog({
  fileId,
  messageId,
  onClose,
}: {
  fileId: string;
  messageId: string | null;
  onClose: () => void;
}) {
  const { data, isPending, isError } = useMessageDetail(fileId, messageId);
  const send = useSendDraft(fileId);
  const open = messageId !== null;

  // SEEDED ON THE MESSAGE'S IDENTITY, not in an effect — the same pattern `OutboundDraftPanel` used
  // and for the same reason. A draft regenerates on every add and remove, so re-seeding whenever the
  // body changes would throw away an edit mid-sentence; keying on identity means the fields fill
  // when a different message is opened and never again.
  const [seededFrom, setSeededFrom] = useState<string | null>(null);
  const [recipient, setRecipient] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  if (data !== undefined && data.id !== seededFrom) {
    setSeededFrom(data.id);
    setRecipient(data.counterparty ?? data.suggested_recipient ?? "");
    setSubject(data.subject ?? "");
    setBody(data.body);
  }
  const canSend = recipient.trim().length > 0 && body.trim().length > 0 && !send.isPending;

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="text-base">
            {data?.subject ?? (isPending ? "Loading…" : "Message")}
          </DialogTitle>
          <DialogDescription className="text-xs">
            {data
              ? [
                  data.direction === "inbound" ? "Received from" : "To",
                  data.counterparty ?? "nobody yet",
                  "·",
                  when(data.sent_at ?? data.created_at),
                ].join(" ")
              : null}
          </DialogDescription>
        </DialogHeader>

        {isError ? (
          <p className="text-sm text-danger">
            This message could not be loaded. It may have been deleted.
          </p>
        ) : isPending ? (
          <p className="text-sm text-muted-foreground">Loading the message…</p>
        ) : data ? (
          <div className="flex flex-col gap-4">
            {/* THE BODY IS THE POINT — before this endpoint a sent message's words were readable
                nowhere in the product. Pre-wrapped rather than rendered: this is plain text a person
                wrote, and interpreting it as anything else is how a borrower's sentence becomes
                markup. */}
            {data.is_editable ? (
              <div className="flex flex-col gap-3">
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium text-foreground">Send to</span>
                  <input
                    type="email"
                    value={recipient}
                    onChange={(event) => setRecipient(event.target.value)}
                    placeholder="borrower@example.com"
                    className="rounded-md border border-input bg-background px-3 py-2 text-sm"
                  />
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium text-foreground">Subject</span>
                  <input
                    type="text"
                    value={subject}
                    onChange={(event) => setSubject(event.target.value)}
                    className="rounded-md border border-input bg-background px-3 py-2 text-sm"
                  />
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium text-foreground">Message</span>
                  <textarea
                    value={body}
                    onChange={(event) => setBody(event.target.value)}
                    rows={16}
                    className="rounded-md border border-input bg-background px-3 py-2 font-mono text-xs"
                  />
                </label>
              </div>
            ) : (
              // READ-ONLY, AND RENDERED AS TEXT. A borrower's sentence is not markup and a dollar
              // sign in it is a dollar sign; this is the one place a body is shown in full, so it is
              // the one place that could get it wrong.
              <pre className="whitespace-pre-wrap break-words rounded-md border border-input bg-muted px-3 py-2 font-mono text-xs text-foreground">
                {data.body}
              </pre>
            )}

            {data.documents.length > 0 ? (
              <div className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-foreground">What it asks for</span>
                <ul className="list-inside list-disc text-muted-foreground">
                  {data.documents.map((title) => (
                    <li key={title}>{title}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            {data.attachments.length > 0 ? (
              <div className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-foreground">What arrived</span>
                <ul className="list-inside list-disc text-muted-foreground">
                  {/* The disposition travels with the name (LP-825): "accepted" and "not yet
                      accepted" are the difference between a document in the file and one still
                      waiting for somebody. */}
                  {data.attachments.map((attachment) => (
                    <li key={attachment.name}>
                      {attachment.name} · {attachment.disposition.replaceAll("_", " ")}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {data.error_detail ? (
              <p className="rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-xs text-danger">
                Delivery failed: {data.error_detail}
              </p>
            ) : null}

            <dl className="grid gap-1 border-t border-border pt-3 text-xs text-muted-foreground">
              <div className="flex gap-2">
                <dt className="font-medium text-foreground">Status</dt>
                <dd>{data.status}</dd>
              </div>
              {data.template_key ? (
                <div className="flex gap-2">
                  <dt className="font-medium text-foreground">Template</dt>
                  <dd>
                    {data.template_key} {data.template_version ?? ""}
                  </dd>
                </div>
              ) : null}
            </dl>

            {data.is_editable ? (
              <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
                <Button
                  type="button"
                  className="gap-2"
                  disabled={!canSend}
                  onClick={() =>
                    send.mutate(
                      {
                        draftId: data.id,
                        recipient: recipient.trim(),
                        subject,
                        body,
                      },
                      { onSuccess: onClose },
                    )
                  }
                >
                  <Send className="h-4 w-4" /> {send.isPending ? "Recording…" : "Mark as sent"}
                </Button>
                {/* NOTHING HERE TRANSMITS, and the label says so rather than implying otherwise.
                    LP-816 shipped the transport seam with no provider, so the message still leaves
                    from the processor's own mail client and this records that it went. */}
                <span className="text-xs text-muted-foreground">
                  Records that you sent it. Nothing is transmitted from here.
                </span>
              </div>
            ) : null}
            {send.isError ? (
              <p className="text-sm text-danger">
                This was not recorded as sent. It may already have been sent, or this address may
                have been emailed too recently.
              </p>
            ) : null}
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
