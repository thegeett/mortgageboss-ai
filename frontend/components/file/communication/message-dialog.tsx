"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  messageMailtoUrl,
  useAttachUploadLink,
  useMessageDetail,
  useSaveDraftBody,
  useSendDraft,
} from "@/lib/api/communications";
import { copyMessage } from "@/lib/markdown/copy-rich";
import { emailBodyToHtml } from "@/lib/markdown/email-body";
import { htmlToEmailBody } from "@/lib/markdown/from-html";
import dynamic from "next/dynamic";

/**
 * LP-844 — how a rendered body is styled.
 *
 * ARBITRARY VARIANTS RATHER THAN A RULE IN `globals.css`, for two reasons. The base layer resets
 * list styling globally (Tailwind preflight), so a `<ul>` here needs its bullets back — but this is
 * a FEATURE style, not a design token, and `globals.css` has a reference copy in the design ledger
 * that implementers drop in. Adding a message-body rule there would ship this ticket's CSS to every
 * new screen as though it were part of the system.
 *
 * It styles the PREVIEW, never the send: `emailBodyToHtml` emits no classes at all, because a mail
 * client keeps the semantic tags and discards our stylesheet.
 */
/**
 * LP-849 — LOADED WHEN A PROCESSOR OPENS A DRAFT, not with the page.
 *
 * MEASURED: importing the editor statically took the communication route from 195 kB to 299 kB of
 * first-load JS. ProseMirror is not small, and nobody needs it to READ the timeline — which is what
 * this page is for most of the time. Behind `next/dynamic` the cost is paid on the click that
 * actually needs an editor.
 *
 * `ssr: false` because Tiptap parses its content through the DOM; there is nothing here for a
 * crawler and a server render would only warn about the mismatch.
 */
const MessageEditor = dynamic(
  () => import("@/components/file/communication/message-editor").then((m) => m.MessageEditor),
  {
    ssr: false,
    loading: () => (
      <div className="min-h-[16rem] rounded-md border border-input bg-muted px-3 py-2 text-sm text-muted-foreground">
        Loading the editor…
      </div>
    ),
  },
);

const BODY_PROSE =
  "[&_p]:mb-3 [&_p:last-child]:mb-0 [&_ul]:mb-3 [&_ul]:ml-5 [&_ul]:list-disc [&_li]:mb-1.5 [&_strong]:font-semibold";
import { messageInstant, messageTimeFull, messageTimeLabel } from "@/lib/message-time";
import { Check, Copy, Link as LinkIcon, Mail, Send } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

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
  const save = useSaveDraftBody(fileId);
  const attachLink = useAttachUploadLink(fileId, messageId ?? "");
  const [copied, setCopied] = useState(false);
  const open = messageId !== null;

  // SEEDED ON THE MESSAGE'S IDENTITY, not in an effect — the same pattern `OutboundDraftPanel` used
  // and for the same reason. A draft regenerates on every add and remove, so re-seeding whenever the
  // body changes would throw away an edit mid-sentence; keying on identity means the fields fill
  // when a different message is opened and never again.
  const [seededFrom, setSeededFrom] = useState<string | null>(null);
  const [recipient, setRecipient] = useState("");
  const [subject, setSubject] = useState("");
  // LP-853 — THE EDITOR'S CURRENCY IS HTML, and this holds it. A `plain` body is converted on the
  // way in by `emailBodyToHtml`, which is still the single renderer for that path; an `html` body
  // is what a processor already wrote and is loaded as-is.
  const [bodyHtml, setBodyHtml] = useState("");
  // What the draft LOOKED like when it was opened. Kept so that "did anything actually change?"
  // is answerable — see `onEdit`.
  const [openedAs, setOpenedAs] = useState("");
  // Starts as the server's answer and becomes "html" once a save has landed.
  const [format, setFormat] = useState<"plain" | "html">("plain");
  if (data !== undefined && data.id !== seededFrom) {
    setSeededFrom(data.id);
    setRecipient(data.counterparty ?? data.suggested_recipient ?? "");
    setSubject(data.subject ?? "");
    const seeded = data.body_format === "html" ? data.body : emailBodyToHtml(data.body);
    setBodyHtml(seeded);
    setOpenedAs(seeded);
    setFormat(data.body_format);
  }

  // LP-853 — WHAT IS SENT AND COPIED, derived rather than held twice.
  //
  // An untouched draft still posts its PLAIN body, which is what LP-849's send record has always
  // stored and what keeps the round-trip fixed point meaningful. Once a processor has written into
  // it the HTML is the message, and the plain form is derived for `mailto:` — never stored, because
  // two copies of one message is the anti-pattern this ticket declines twice.
  const bodyPlain = htmlToEmailBody(bodyHtml);
  const bodyForSend = format === "html" ? bodyHtml : bodyPlain;
  // LP-847 — NO RECIPIENT REQUIRED. LP-843 gives a party with no contact on file a draft with an
  // empty To, deliberately; requiring one here meant every such draft had a permanently greyed
  // "Mark as sent" with nothing saying why, which is how it was reported. Nothing in this product
  // transmits — this records that a PROCESSOR sent the message from their own mail client, possibly
  // to an address they know and have never typed in here. A body is still required: there is no
  // message to have sent without one.
  const canSend = bodyPlain.trim().length > 0 && !send.isPending;
  // Built from the EDITED body and the typed recipient, so the link carries what is on screen.
  // ALWAYS THE PLAIN DERIVATION: `mailto:` bodies are plain text by RFC 6068 and no client renders
  // markup in one, so handing it HTML would put tags in the borrower's message.
  const mailtoHref = data ? messageMailtoUrl(data, recipient, bodyPlain) : null;

  // LP-853 — SAVED WHEN THE WORDS MOVE, AND NOT WHEN THEY DO NOT.
  //
  // Acceptance 2 is "opening a generated draft and not typing leaves it plain — focus is not an
  // edit". The server cannot tell the difference: a save IS the edit, which is the whole reason
  // there is no `body_format` field on the payload. So the guarantee lives on this side.
  //
  // WHAT ACTUALLY KEEPS IT IS THAT TIPTAP DOES NOT FIRE `onUpdate` WITHOUT A DOCUMENT CHANGE —
  // not mounting, not focusing, not clicking. That is asserted against the real editor in
  // `message-editor.test.tsx`, because it is a fact about Tiptap and this file cannot hold it.
  //
  // The `openedAs` comparison below is a second line and is honestly that. It cannot be the first:
  // if Tiptap ever DID report on mount it would report its own normalisation of the seed, which is
  // a different string, and an exact comparison would call that an edit. What it does cover is a
  // processor undoing back to where they started.
  const dirtyRef = useRef(false);
  const latest = useRef({ draftId: "", html: "", subject: "" });
  latest.current = { draftId: data?.id ?? "", html: bodyHtml, subject };

  const flush = useCallback(() => {
    if (!dirtyRef.current) return;
    dirtyRef.current = false;
    const { draftId, html, subject: currentSubject } = latest.current;
    if (!draftId) return;
    save.mutate(
      { draftId, body: html, subject: currentSubject },
      { onSuccess: () => setFormat("html") },
    );
  }, [save]);

  // DEBOUNCED, because this fires on every keystroke. One request per pause rather than per letter,
  // and a flush on close so the last sentence typed is never the one that is lost.
  useEffect(() => {
    if (!dirtyRef.current) return;
    const timer = window.setTimeout(flush, 800);
    return () => window.clearTimeout(timer);
  }, [flush]);

  function onEdit(html: string) {
    setBodyHtml(html);
    if (html !== openedAs) dirtyRef.current = true;
  }

  function close() {
    flush();
    onClose();
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && close()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="text-base">
            {data?.subject ?? (isPending ? "Loading…" : "Message")}
          </DialogTitle>
          <DialogDescription className="text-xs">
            {data
              ? [
                  data.direction === "inbound" ? "From" : "To",
                  data.counterparty ?? "nobody yet",
                  "·",
                  // LP-838 — SAME INSTANT AS THE LIST, SAME RULE, longer form. `messageInstant`
                  // applies `_message_at`'s rule rather than restating it, so a row and the message
                  // it opens cannot disagree about when it happened.
                  messageTimeLabel(data),
                  messageTimeFull(messageInstant(data)),
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
                <div className="flex flex-col gap-1 text-sm">
                  <span className="font-medium text-foreground">Message</span>
                  {/* LP-849 — A MESSAGE BOX, NOT A NOTEPAD. LP-844 put Markdown in a textarea with
                      a Preview toggle to avoid an editor dependency; a processor used it and
                      reported it as "simple notepad version" with "old scholl ***bold***". The
                      toggle is gone because a WYSIWYG IS the preview.

                      LP-853 — THE EDITOR NOW SPEAKS HTML, and the stored body follows the moment a
                      processor types. `data.body_format` says which language the body arrived in;
                      everything below derives the plain form on demand rather than holding a
                      second copy of the message. */}
                  <MessageEditor
                    value={data.body_format === "html" ? data.body : emailBodyToHtml(data.body)}
                    format={data.body_format}
                    onChange={onEdit}
                  />
                  <p className="text-xs text-muted-foreground">
                    {/* WHICH ROUTE KEEPS THE FORMATTING. `mailto:` bodies are plain text by RFC
                        6068 — no client renders markup in one — so the two buttons below are not
                        equivalent and a processor should not have to discover that by sending a
                        flattened email. */}
                    Formatting survives <span className="text-foreground">Copy message</span>; the
                    mail-client link sends plain text.
                  </p>
                </div>
              </div>
            ) : (
              // LP-844 — READ AS A LETTER, NOT AS A DUMP. This was a monospace `<pre>`, which is
              // part of why the message read as machine-generated: the product showed a business
              // letter in a code font.
              //
              // A borrower's sentence is still not markup. `emailBodyToHtml` escapes every
              // character that could start a tag BEFORE it emits one, so `dangerouslySetInnerHTML`
              // here is handed a string in which the only tags are the ones that function built.
              // That ordering is the entire safety argument and it is tested directly.
              <div
                className={`message-body break-words rounded-md border border-input bg-muted px-3 py-2 text-sm text-foreground ${BODY_PROSE}`}
                // biome-ignore lint/security/noDangerouslySetInnerHtml: escape-first renderer for a plain body, server-side allowlist for an authored one — see below
                dangerouslySetInnerHTML={{
                  // LP-853 — AN AUTHORED BODY IS ALREADY MARKUP AND IS NOT RE-RENDERED. Running it
                  // through `emailBodyToHtml` would escape the processor's own tags into view, so
                  // the message they wrote would read back as source. What makes this safe is the
                  // server: `sanitise_html` rebuilds every saved body from an allowlist on the way
                  // IN, so the column cannot hold a tag that was not permitted — which is a
                  // stronger guarantee than sanitising here, because every other reader of the row
                  // inherits it without knowing the rule.
                  __html: data.body_format === "html" ? data.body : emailBodyToHtml(data.body),
                }}
              />
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
                {/* LP-831 REVIEW — THE TWO CONTROLS THAT ACTUALLY SEND, restored.
                    `OutboundDraftPanel` carried "Copy message" and "Open in mail client" and this
                    ticket took it off the page, leaving "Mark as sent" alone. Nothing in this
                    product transmits mail — LP-828's own analysis says so — so those two were the
                    only ways a message reached anybody, and the one remaining button records an
                    outbound event, moves every need to REQUESTED and starts LP-814's reminder
                    clock. A processor could mark a message sent with no way to send it. */}
                <Button
                  type="button"
                  variant="outline"
                  className="gap-2"
                  onClick={async () => {
                    // LP-844 — BOTH FLAVOURS. This is the send path, so bold and bullets survive
                    // here or nowhere: `mailto:` bodies are plain text by RFC 6068 and no client
                    // renders markup in one.
                    await copyMessage(bodyForSend, format);
                    setCopied(true);
                    window.setTimeout(() => setCopied(false), 2000);
                  }}
                >
                  {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                  {copied ? "Copied" : "Copy message"}
                </Button>

                {/* THE EDITED BODY, not the stored one — the borrower must receive what the record
                    stores. A null href is the length gate: `mailto:` does not fail when it is too
                    long, it opens a compose window holding half a message. */}
                {mailtoHref ? (
                  <Button asChild variant="outline" className="gap-2">
                    <a href={mailtoHref}>
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
                  onClick={() =>
                    send.mutate(
                      {
                        draftId: data.id,
                        recipient: recipient.trim(),
                        subject,
                        body: bodyForSend,
                      },
                      { onSuccess: onClose },
                    )
                  }
                >
                  <Send className="h-4 w-4" /> {send.isPending ? "Recording…" : "Mark as sent"}
                </Button>
                {/* LP-834 — THE LINK IS ADDED FROM INSIDE THE DRAFT, which is the gap this
                    closes: it was minted on a panel below and pasted by hand.

                    THE WARNING IS BEFORE THE CLICK, NOT AFTER. Minting expires every other live
                    link on the file, so a borrower already sent one loses it — they click and are
                    refused, with no explanation on their end. That is the right trade against two
                    live credentials and it is not a thing to discover afterwards. */}
                <Button
                  type="button"
                  variant="outline"
                  className="gap-2"
                  disabled={attachLink.isPending}
                  title={
                    data.body.includes("/upload/")
                      ? "Replaces the link in this draft. Any link already sent stops working."
                      : "Any link already sent to this borrower stops working."
                  }
                  onClick={() => attachLink.mutate()}
                >
                  <LinkIcon className="h-4 w-4" />
                  {data.body.includes("/upload/")
                    ? "Replace the secure link"
                    : "Add a secure upload link"}
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
