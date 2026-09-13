"use client";

import { MailClientDialog } from "@/components/file/communication/mail-client-dialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  useAttachUploadLink,
  useMessageDetail,
  useSaveDraftBody,
  useSendDraft,
} from "@/lib/api/communications";
import type { MailClient } from "@/lib/api/preferences";
import { usePreferences, useUpdatePreferences } from "@/lib/api/preferences";
import {
  composeButtonLabel,
  composeUrl,
  effectiveClient,
} from "@/lib/communication/compose-routes";
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
import { Check, Copy, ExternalLink, Link as LinkIcon } from "lucide-react";
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

  // LP-855 — WHERE THIS PROCESSOR WRITES THEIR EMAIL, and the picker that asks once.
  //
  // `null` is "nobody has been asked", which is not the same as choosing the desktop default —
  // see `MailClient`. The picker opens on the first EDITABLE draft they see, which is the moment
  // the answer is about to matter, and never again once answered.
  const preferences = usePreferences();
  const savePreferences = useUpdatePreferences();
  const [askedThisSession, setAskedThisSession] = useState(false);
  // LP-855 REVIEW — WHAT THEY JUST PICKED, HELD HERE UNTIL THE SERVER AGREES.
  //
  // `onChoose` closes the picker and fires the save, and the compose route read
  // `preferences.data.mail_client` — which is still `null` until the round trip lands. So between
  // choosing Gmail and the response arriving, the button read "Copy & open mail app" and opened
  // `mailto:`. A processor who clicks straight through, which is the whole shape of this dialog,
  // gets the route they just said they did not want.
  //
  // AND IF THE SAVE FAILS IT NEVER RESOLVES. `useUpdatePreferences` has no `onError`, so a failed
  // PUT is silent; `askedThisSession` is already true, so the picker cannot come back; and
  // `mail_client` stays `null` for the rest of the session. Every compose then goes to `mailto:`
  // with nothing on screen saying why.
  //
  // Held locally rather than written optimistically into the query cache, because a rollback on
  // error would put it back to `null` and reintroduce exactly the bug. Their answer stands for this
  // session whatever the network did; the server not having it means they are asked again next
  // time, which is true and is the right thing to happen.
  const [chosenClient, setChosenClient] = useState<MailClient | null>(null);
  const activeClient = chosenClient ?? preferences.data?.mail_client ?? null;
  const needsClient =
    data?.is_editable === true &&
    preferences.data !== undefined &&
    preferences.data.mail_client === null &&
    !askedThisSession;

  /** What just happened to the compose window — see the sentence under the buttons. */
  const [opened, setOpened] = useState<"idle" | "opened" | "blocked" | "copy-failed">("idle");

  /**
   * The whole send path, in one click.
   *
   * ORDER MATTERS: THE CLIPBOARD FIRST. `window.open` can be refused by a popup blocker, and if it
   * were first a refusal would leave the processor with neither a window nor a copy. Copying first
   * means the worst case is "the message is on your clipboard, open your mail app yourself" —
   * which is exactly what the sentence under the buttons then says.
   */
  async function copyAndOpen() {
    if (!data) return;

    // LP-855 REVIEW — A REJECTED CLIPBOARD MUST NOT MAKE THE BUTTON DO NOTHING.
    //
    // `copyMessage` falls back from `ClipboardItem` to `writeText`, but `writeText` itself rejects
    // when the permission is denied outright — and an unhandled rejection here meant `window.open`
    // was never reached and no state was set. No copy, no window, no sentence: a primary button
    // that appears broken. That is the mirror image of the blocked-popup case, which WAS handled.
    //
    // THE WINDOW STILL OPENS. To and Subject are worth having even without the body, and it leaves
    // the processor one action short rather than at a dead end.
    let copyFailed = false;
    try {
      await copyMessage(bodyForSend, format);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      copyFailed = true;
    }

    const url = composeUrl(effectiveClient(activeClient), {
      to: recipient.trim(),
      subject,
    });
    // `mailto:` is handled by the OS rather than opened as a tab, and a blocker does not apply; the
    // web routes are ordinary windows and can be refused.
    const window_ = window.open(url, "_blank", "noopener,noreferrer");
    // PRECEDENCE: say what is MISSING. A failed copy is the worse of the two, because the message
    // is the half a processor cannot reconstruct from the screen behind them.
    setOpened(copyFailed ? "copy-failed" : window_ === null ? "blocked" : "opened");
  }
  // LP-855 — `messageMailtoUrl` AND ITS LENGTH GATE ARE GONE FROM THIS SCREEN.
  //
  // `mailto_max_chars` exists because a long BODY overflows the URL, and `mailto:` does not fail
  // when it is too long — it opens a compose window holding half a message. There is no longer a
  // body in the URL, so the ceiling has nothing to measure: what remains is the subject and the
  // address, capped by `SendDraftRequest` at 256 each, against a ceiling of 1,800. Hiding the
  // button because a message is long is the behaviour that stops.

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
    // LP-853 REVIEW — ASSIGNED, NOT ONLY RAISED. This was `if (html !== openedAs) dirty = true`,
    // which never cleared the flag on the way back: type one letter and undo it, and the flag set
    // by the keystroke survived the undo, so the flush saved a body identical to the one the editor
    // was handed. That flips `body_format` to html for a draft nobody changed — `_regenerate` then
    // refuses it and LP-851 warns about losing changes that do not exist, which is acceptance 2
    // failing by a longer route than the one it was written for. The comment above already claimed
    // this case was covered; now it is.
    dirtyRef.current = html !== openedAs;
  }

  function close() {
    flush();
    onClose();
  }

  return (
    <>
      {/* LP-855 — THE MESSAGE WAITS WHILE THE PICKER IS UP, and this is a correctness fix rather
          than a preference about order.

          TWO OPEN RADIX MODALS HIDE EACH OTHER. Each marks everything outside itself `aria-hidden`,
          so with both open NOTHING is in the accessibility tree — measured: zero buttons and zero
          dialogs reachable by role, while the picker's text was still findable by `getByText`. A
          screen reader would have announced neither, and a keyboard user could have reached
          neither. Reordering them did not help, because the problem is that there are two.

          So there is one at a time. The picker is one question that takes one click, and the draft
          opens behind it the moment it is answered. */}
      <Dialog open={open && !needsClient} onOpenChange={(next) => !next && close()}>
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
                <div className="flex flex-col gap-2 border-t border-border pt-3">
                  {/* SCREEN 2's BUTTON BAR:
                      `Copy & open <client>` · `Copy message` · `Mark as sent` — spacer — `Delete`

                    THERE IS NO SEND BUTTON, NOT EVEN DISABLED. `mail_transport` is an interface
                    with no provider behind it, so a greyed-out Send would be a promise this version
                    cannot keep and the first thing a processor would click. The absence is asserted
                    in `message-dialog.test.tsx`, with a positive control naming the buttons that
                    ARE here — a not-assertion over a whole screen otherwise passes on a screen that
                    failed to render. */}
                  <div className="flex flex-wrap items-center gap-2">
                    {/* THE WHOLE SEND PATH IN ONE CLICK. It copies the RICH body AND opens the
                      compose window with To and Subject filled and the body EMPTY — every compose
                      route takes the body as plain text, so filling it would hand the processor a
                      message that looks finished and has quietly lost its structure. An empty body
                      is obviously unfinished, which is the point. */}
                    <Button
                      type="button"
                      className="gap-2"
                      disabled={!canSend}
                      onClick={() => void copyAndOpen()}
                    >
                      <ExternalLink className="h-4 w-4" />
                      {composeButtonLabel(activeClient)}
                    </Button>

                    {/* KEPT FOR ANYBODY DOING IT THEIR OWN WAY — and it is the fallback when a popup
                      blocker eats the compose window. */}
                    <Button
                      type="button"
                      variant="outline"
                      className="gap-2"
                      onClick={async () => {
                        // LP-844 — BOTH FLAVOURS. This is the send path, so bold and bullets survive
                        // here or nowhere.
                        await copyMessage(bodyForSend, format);
                        setCopied(true);
                        window.setTimeout(() => setCopied(false), 2000);
                      }}
                    >
                      {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                      {copied ? "Copied" : "Copy message"}
                    </Button>

                    {/* THE CLAIM, ATTRIBUTED. Nothing observed a send, so what this records is that a
                      processor says they sent it — `Marked sent by Priya · Tue 16:41` on the list.
                      It starts no clock, because there are no reminders in this version. */}
                    <Button
                      type="button"
                      variant="outline"
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
                      <Check className="h-4 w-4" /> {send.isPending ? "Recording…" : "Mark as sent"}
                    </Button>

                    {/* LP-834 — the secure link. LP-857 takes it off the page with the rest of the
                      next phase; it stays here until then. */}
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
                  </div>

                  {/* WHAT JUST HAPPENED, in the processor's next action rather than as reassurance.
                    A popup blocker eating the compose window is the ordinary failure here, and the
                    copy still worked — so the message says so rather than reporting an error about
                    a window. */}
                  <p className="text-xs text-muted-foreground">
                    {/* NAMES WHAT FAILED AND OFFERS THE NEXT MOVE — the Ledger's rule 9, no
                        apologies and no "something went wrong". Each says which HALF is missing,
                        because the recovery is different for each. */}
                    {opened === "copy-failed"
                      ? "Your browser refused the copy — the compose window is open, so select the message above and copy it in yourself."
                      : opened === "blocked"
                        ? "Your browser blocked the compose window — the message is on your clipboard, so open your mail app and paste it."
                        : opened === "opened"
                          ? "Paste into the message — ⌘V."
                          : "Records that you sent it. Nothing is transmitted from here."}
                  </p>
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
      {/* LP-855 — ASKED ONCE, ON THE FIRST DRAFT, AND RENDERED LAST.

          The order is load-bearing rather than stylistic. Two modals are open at once here, and
          Radix marks everything outside the TOPMOST one `aria-hidden` — so with the picker first it
          was rendered, visible to `getByText`, and absent from the accessibility tree: a question a
          screen reader never announced and a keyboard user could not reach, sitting in front of the
          button it configures. Caught by the picker's own test failing to find its primary.

          Last means topmost, which is also the right order for the person: answer where you write
          your email, then send the message. */}
      <MailClientDialog
        open={needsClient}
        suggested={preferences.data?.suggested_mail_client ?? "mailto"}
        reason={preferences.data?.mail_client_suggestion_reason ?? ""}
        pending={savePreferences.isPending}
        onChoose={(client) => {
          // THE ANSWER TAKES EFFECT NOW, not when the PUT returns. See `chosenClient`.
          setChosenClient(client);
          setAskedThisSession(true);
          savePreferences.mutate({ mail_client: client });
        }}
      />
    </>
  );
}
