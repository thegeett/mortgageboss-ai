"use client";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useMessageDetail } from "@/lib/api/communications";
import { format } from "date-fns";

/**
 * One message, opened from the timeline (LP-829).
 *
 * A READER, NEVER AN EDITOR. The open draft is already rendered and editable in
 * `OutboundDraftPanel` on the same page; a dialog that also edited it would be two components
 * holding separate local state for one body, and whichever saved last would win with nothing on
 * screen to say so. Sent and received messages are not editable at all — the first because the
 * evidence record must not change after the fact, the second because a borrower's words are not
 * ours to rewrite.
 *
 * SO WHY OPEN THE DRAFT HERE AT ALL. Because "what does this say" is a different question from
 * "let me change it", and answering it should not mean scrolling to a textarea and reading around
 * an edit somebody is halfway through. The draft's row points at the panel that owns editing.
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
  const open = messageId !== null;

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
            <pre className="whitespace-pre-wrap break-words rounded-md border border-input bg-muted px-3 py-2 font-mono text-xs text-foreground">
              {data.body}
            </pre>

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

            {data.is_open_draft ? (
              // ONE EDITOR. The panel above owns the draft; this says where to change it rather
              // than becoming a second place that can.
              <p className="rounded-md border border-input bg-muted px-3 py-2 text-xs text-muted-foreground">
                This is the file's open draft. Edit it in <strong>Document request</strong> at the
                top of this page.
              </p>
            ) : null}
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
