"use client";

import { Button } from "@/components/ui/button";
import { mailtoUrl, useOutboundDraft, useSendDraft } from "@/lib/api/communications";
import { Check, Copy, Mail, Send } from "lucide-react";
import { useState } from "react";

/**
 * The document request a processor reviews, edits and sends (LP-811b).
 *
 * NOTHING HERE TRANSMITS. The processor copies the text into their own mail client, or opens a
 * `mailto:` link; "Mark as sent" records that it went out, which is what moves every requested
 * document to REQUESTED and starts the reminder clock. LP-816 is the ticket that sends as her.
 *
 * The controls follow the order of the work: read it, edit it, take it, then say you sent it. "Mark
 * as sent" is last because it is the one action that cannot be taken back — a second attempt is
 * refused deliberately, so a processor who clicks twice is told the first one went rather than left
 * unsure.
 */
export function OutboundDraftPanel({ fileId }: { fileId: string }) {
  const { data: draft, isPending, isError } = useOutboundDraft(fileId);
  const send = useSendDraft(fileId);
  const [recipient, setRecipient] = useState("");
  const [body, setBody] = useState("");
  const [copied, setCopied] = useState(false);
  const draftId = draft?.id;
  const draftBody = draft?.body;

  // THE DRAFT REGENERATES ON EVERY ADD AND REMOVE (LP-809), so re-seeding the textarea whenever the
  // body changes would throw away a processor's edits mid-sentence. Seeding is keyed on the draft's
  // IDENTITY instead, tracked explicitly rather than through an effect dependency list: an effect
  // that lies about its dependencies is a lint suppression somebody later "fixes", and the fix is
  // the data loss.
  const [seededFrom, setSeededFrom] = useState<string | undefined>(undefined);
  if (draftId !== undefined && draftId !== seededFrom) {
    setSeededFrom(draftId);
    setBody(draftBody ?? "");
  }

  if (isPending) {
    return <p className="text-sm text-muted-foreground">Loading the current request…</p>;
  }
  if (isError) {
    return (
      <p className="text-sm text-danger">
        The current request could not be loaded. Refresh to try again.
      </p>
    );
  }
  if (!draft) {
    return (
      <div className="rounded-lg border border-dashed border-input bg-card px-6 py-12 text-center">
        <h2 className="text-base font-semibold text-foreground">Nothing to request</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          When you request documents from the needs list or a verification finding, they collect
          here as one email rather than several.
        </p>
      </div>
    );
  }

  const href = mailtoUrl(draft, recipient);
  const canSend = recipient.trim().length > 0 && body.trim().length > 0 && !send.isPending;

  const copyToClipboard = async () => {
    await navigator.clipboard.writeText(body);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };

  return (
    <section className="flex flex-col gap-4">
      <header className="flex flex-col gap-1">
        <h2 className="text-base font-semibold text-foreground">Document request</h2>
        <p className="text-sm text-muted-foreground">
          {draft.needs_item_count === 1
            ? "1 document is included in this request."
            : `${draft.needs_item_count} documents are included in this request.`}
        </p>
      </header>

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

      <div className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-foreground">Subject</span>
        <p className="rounded-md border border-input bg-muted px-3 py-2 text-sm">{draft.subject}</p>
      </div>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-foreground">Message</span>
        <textarea
          value={body}
          onChange={(event) => setBody(event.target.value)}
          rows={18}
          className="rounded-md border border-input bg-background px-3 py-2 font-mono text-xs"
        />
      </label>

      <dl className="grid gap-1 rounded-md border border-input bg-muted px-3 py-2 text-xs">
        <div className="flex gap-2">
          <dt className="font-medium text-foreground">Reply-To</dt>
          <dd className="text-muted-foreground">{draft.reply_to}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="font-medium text-foreground">Bcc this address</dt>
          <dd className="text-muted-foreground">
            {draft.suggested_bcc} — so the sent copy is filed against this loan
          </dd>
        </div>
      </dl>

      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="outline" className="gap-2" onClick={copyToClipboard}>
          {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
          {copied ? "Copied" : "Copy message"}
        </Button>

        {href ? (
          <Button asChild variant="outline" className="gap-2">
            <a href={href}>
              <Mail className="h-4 w-4" /> Open in mail client
            </a>
          </Button>
        ) : (
          <Button type="button" variant="outline" className="gap-2" disabled>
            <Mail className="h-4 w-4" /> Open in mail client
          </Button>
        )}

        <Button
          type="button"
          className="gap-2"
          disabled={!canSend}
          onClick={() => send.mutate({ draftId: draft.id, recipient: recipient.trim(), body })}
        >
          <Send className="h-4 w-4" /> {send.isPending ? "Recording…" : "Mark as sent"}
        </Button>
      </div>

      {!draft.mailto_available && (
        <p className="text-xs text-muted-foreground">
          This message is too long to open in a mail client without being cut short (the limit is
          about {draft.mailto_max_chars} characters). Copy it instead.
        </p>
      )}

      {send.isError && (
        <p className="text-sm text-danger">
          This request was not recorded as sent. It may already have been sent, or this borrower may
          have been emailed too recently.
        </p>
      )}
      {send.isSuccess && (
        <p className="text-sm text-success">
          Recorded as sent. {send.data.needs_items_requested} document
          {send.data.needs_items_requested === 1 ? "" : "s"} moved to requested.
        </p>
      )}
    </section>
  );
}
