"use client";

import { DeleteDraftDialog } from "@/components/file/communication/delete-draft-dialog";
import { MailClientDialog } from "@/components/file/communication/mail-client-dialog";
import { PartyAddressForm } from "@/components/file/communication/party-address-form";
import { Button } from "@/components/ui/button";
import { useCapabilities } from "@/lib/api/capabilities";
import {
  useAttachUploadLink,
  useDeleteDraft,
  useMessageDetail,
  usePolishDraft,
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
import { polishMessage } from "@/lib/communication/polish-messages";
import { getErrorMessage } from "@/lib/errors/api-error";
import { copyMessage } from "@/lib/markdown/copy-rich";
import { emailBodyToHtml } from "@/lib/markdown/email-body";
import { htmlToEmailBody } from "@/lib/markdown/from-html";
import { notifyError, notifySuccess } from "@/lib/toast";
import type { ResponsibleParty } from "@/lib/types/party-request";
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
import { Check, Copy, ExternalLink, Link as LinkIcon, Sparkles, Trash2, X } from "lucide-react";
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
export function DraftPane({
  fileId,
  messageId,
  onClose,
  onDeleted,
}: {
  fileId: string;
  messageId: string | null;
  onClose: () => void;
  /** LP-858 §2.1 rule 6 — the page moves the selection off a row that no longer exists. */
  onDeleted?: (draftId: string) => void;
}) {
  const { data, isPending, isError } = useMessageDetail(fileId, messageId);
  const send = useSendDraft(fileId);
  const save = useSaveDraftBody(fileId);
  const attachLink = useAttachUploadLink(fileId, messageId ?? "");
  // LP-857 — whether this version can receive anything. Same fact as the page's, from the same
  // endpoint: the panel and the button must not disagree about whether an upload link exists.
  const capabilities = useCapabilities().data;
  const receiving = capabilities?.receiving ?? false;
  // LP-858 §5 — ✦ POLISH IS ABSENT WHEN IT IS NOT WIRED, not present and refusing.
  //
  // FALSE WHILE LOADING, like `receiving` and for the same reason: the restrictive default. A
  // button that appeared for a moment and then vanished is worse than one that was never there,
  // and `email_draft_enabled` is false in every environment today, so the flash would be the
  // ordinary case rather than the edge.
  const polishAvailable = capabilities?.polish ?? false;
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
  // LP-858 §8 — WHAT THE OTHER TWO FIELDS HELD WHEN THE PANE OPENED. "No modification" means To,
  // Subject and body all unchanged, so all three need a baseline; the body already had one for
  // autosave, and these two are the rest of the same question.
  const [openedWith, setOpenedWith] = useState({ recipient: "", subject: "" });
  // Starts as the server's answer and becomes "html" once a save has landed.
  const [format, setFormat] = useState<"plain" | "html">("plain");
  if (data !== undefined && data.id !== seededFrom) {
    setSeededFrom(data.id);
    setRecipient(data.counterparty ?? data.suggested_recipient ?? "");
    setSubject(data.subject ?? "");
    const seeded = data.body_format === "html" ? data.body : emailBodyToHtml(data.body);
    setBodyHtml(seeded);
    setOpenedAs(seeded);
    setOpenedWith({
      recipient: data.counterparty ?? data.suggested_recipient ?? "",
      subject: data.subject ?? "",
    });
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
  // LP-858 §1 — WHETHER THE PICKER IS UP. Driven by a button press and nothing else.
  const [pickerOpen, setPickerOpen] = useState(false);
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
  // LP-858 §1 — A CAPABILITY QUESTION, NOT A TRIGGER.
  //
  // This used to drive the picker's `open` prop AND suppress the draft behind it
  // (`open={open && !needsClient}`), so the first editable draft of a session opened onto a
  // question about a message the processor had not read yet. Reported from use: *"on clicking
  // draft, it suddenly asked me to choose what email client you want to open."*
  //
  // It is now read by `copyAndOpen` and by nothing else. Pressing `Copy & open …` is the only
  // moment the answer matters, which is the only moment worth asking it.
  //
  // NO `is_editable` HERE. The only caller is the handler behind a button that renders inside the
  // editable branch, so a condition for it on this line is one no mutation could find — the same
  // decoration LP-857 removed from `needsAnAddress`. A sent message has no button to press.
  const needsClient = preferences.data !== undefined && preferences.data.mail_client === null;

  // LP-856 — ✦ polish. THE PROPOSAL IS HELD, NOT APPLIED.
  //
  // A rewrite that landed silently on save is a message going out in words nobody read — and the
  // processor is the one who will be asked about those words later. One click to accept, one to
  // discard, and the original recoverable until they choose.
  const polishDraft = usePolishDraft(fileId);
  const [proposal, setProposal] = useState<string | null>(null);
  const [polishRefusal, setPolishRefusal] = useState<string | null>(null);

  function askForPolish() {
    if (!data) return;
    setPolishRefusal(null);
    polishDraft.mutate(
      { draftId: data.id, body: bodyForSend },
      {
        onSuccess: (result) => {
          // IT FAILS VISIBLY OR NOT AT ALL. `email_draft_enabled` is off in every environment, so a
          // refusal is the ordinary answer — and returning the text unchanged would look like a
          // polish that decided nothing needed changing, which the processor could not tell apart.
          if (result.polished === null) {
            setPolishRefusal(result.refusal ?? "unavailable");
            return;
          }
          setProposal(result.polished);
        },
        onError: () => setPolishRefusal("unavailable"),
      },
    );
  }

  // LP-857 — WHETHER THIS DRAFT IS BLOCKED ON AN ADDRESS NOBODY HAS RECORDED.
  //
  // FOUR CONDITIONS, AND ALL FOUR ARE LOAD-BEARING. It has to be a PARTY draft (the borrower's
  // address is a borrower record, not a participant row, and `add_party_address` would file it
  // under the wrong thing); nobody may have addressed it (`counterparty`), because an addressed
  // draft is not blocked; the file must not already know the answer (`suggested_recipient`),
  // because asking again for something already recorded is how a second title company ends up on a
  // file; and the box must be empty. `party` comes from the server — five parties share
  // `document_request_third_party`, so deriving it from `template_key` here would file a lender's
  // address under the title company.
  //
  // THE MIDDLE TWO ARE NOT REDUNDANT WITH THE LAST, though at open time they agree: an addressed
  // draft seeds the box, so an empty box already means nobody is addressed. They part company the
  // moment a processor CLEARS it — "No address on file" would then be false for a file that has one
  // and is offering it.
  //
  // NO `is_editable` HERE, deliberately. The form renders inside the `data.is_editable` branch
  // below, so a condition for it on this line is one no mutation can find: dropping it left every
  // test green, which makes it decoration rather than a guard. A sent message has no form because
  // it has no editable block, and that is what the test asserts against.
  const needsAnAddress =
    data !== undefined &&
    // TRUTHY, not `!== null`. Null is the documented "no party" answer, but a payload that simply
    // omits the field gives `undefined`, and `undefined !== null` would render the form with no
    // role to save against — an address filed under nothing, from a control that looked ordinary.
    Boolean(data.party) &&
    data.party !== "borrower" &&
    !data.counterparty &&
    !data.suggested_recipient &&
    recipient.trim() === "";

  // LP-858 §7 — DELETE, AND THE CONFIRM THAT ONLY APPEARS WHEN THERE IS SOMETHING TO LOSE.
  //
  // `body_format === "html"` IS `body_edited`. LP-853 made that one fact in one place: the column
  // records that a person wrote this body, and there is no second flag to disagree with it.
  const deleteDraft = useDeleteDraft(fileId);
  const [confirming, setConfirming] = useState(false);
  const edited = data?.body_format === "html";

  function removeDraft() {
    if (!data) return;
    setConfirming(false);
    deleteDraft.mutate(
      { draftId: data.id },
      {
        // THE SELECTION MOVES FIRST, and the page decides where to. Leaving it on a row that is
        // gone paints "This message could not be loaded" over a delete that worked — an error for
        // something the processor just did on purpose.
        onSuccess: () => {
          onDeleted?.(data.id);
          notifySuccess({
            title: "Draft deleted",
            consequence:
              "The documents it asked for are still on the needs list — deleting a draft does not un-request them.",
          });
        },
        onError: (error) =>
          notifyError({ title: "Couldn’t delete the draft", whatToDo: getErrorMessage(error) }),
      },
    );
  }

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
  async function copyAndOpen(chosen?: MailClient) {
    if (!data) return;

    // LP-858 §1 — ASK HERE, AND ONLY HERE. `Copy message`, `Mark as sent` and simply reading the
    // draft need no client and must not raise this.
    //
    // `chosen` is the answer arriving from the picker, passed in rather than read from state
    // because `setChosenClient` has not re-rendered yet when `onChoose` calls back. That is what
    // makes answering COMPLETE the action in the same gesture instead of arming it for a second
    // press — the failure this section of the ticket is about, one step later.
    const client = chosen ?? activeClient;
    if (client === null && needsClient) {
      setPickerOpen(true);
      return;
    }

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

    const url = composeUrl(effectiveClient(client), {
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
    // LP-859 §3 FOLLOW-UP — AN EMPTY DOCUMENT IS NOT A CHANGE TO AN EMPTY DRAFT.
    //
    // A blank compose draft seeds this editor with `""`, and Tiptap's empty document serialises to
    // `<p></p>`. So typing one character and deleting it makes `html !== openedAs` true and the
    // debounce saves `body = "<p></p>"` — after which the server's `draft_row_is_blank` tests
    // `(body or "").strip()`, finds it non-empty forever, and the row reverts to "cannot be sent
    // yet" over "A document request is being prepared" for a draft that is visibly empty.
    // `_is_untouched_compose_draft` refuses the hard delete too, leaving precisely the `deleted_at`
    // row for a message that never held a word that LP-858 §8 exists to prevent. Two keystrokes.
    //
    // ANSWERED HERE, WITH THE CONVERTER THAT ALREADY EXISTS. `sanitise.py` declined an html-to-plain
    // on the backend in writing — *"`from-html.ts` already derives it… a second implementation on
    // this side would be two answers to one question"* — and this is the side that holds the
    // converter AND writes the offending value.
    //
    // NARROW ON PURPOSE: it suppresses the save only when NEITHER side holds a message. A
    // formatting-only edit (bold, a bullet) still saves, because its plain form is not empty; and
    // clearing a draft that HAD words is a real change, because `openedAs` is not empty then.
    const changed = html !== openedAs;
    const neitherHoldsAMessage =
      htmlToEmailBody(html).trim() === "" && htmlToEmailBody(openedAs).trim() === "";
    dirtyRef.current = changed && !neitherHoldsAMessage;
  }

  function close() {
    // LP-858 §8 — A COMPOSE DRAFT NOBODY TOUCHED IS REMOVED, not soft-deleted. It never held
    // anything, so a `deleted_at` row would be litter with a timestamp on it.
    //
    // "NO MODIFICATION" IS ALL THREE FIELDS, and a recipient alone counts as work: *"A processor
    // who typed a recipient and stopped has done work; do not destroy it."* Compared against what
    // the pane OPENED with rather than against emptiness, so a draft seeded from the file's own
    // suggestion — which the processor did not type — is not mistaken for one they filled in.
    //
    // THE SERVER DECIDES WHETHER IT MAY GO. This is a request: `discard` is refused for anything
    // with a template key, a needs link or any content, so a bug in the comparison below can only
    // cost a soft delete, never a processor's words. That asymmetry is deliberate — the client
    // decides whether to ask, the server decides whether the row is one that may be removed.
    const untouched =
      data !== undefined &&
      data.template_key === null &&
      bodyHtml === openedAs &&
      recipient === openedWith.recipient &&
      subject === openedWith.subject &&
      bodyPlain.trim() === "" &&
      recipient.trim() === "" &&
      subject.trim() === "";

    if (untouched && data) {
      // NOT FLUSHED FIRST. There is nothing to save — `dirtyRef` is false by construction here, and
      // a save would write `body_format = html` onto a row about to be removed.
      const draftId = data.id;
      deleteDraft.mutate(
        { draftId, discard: true },
        // SILENT, per §7: no toast and no undo, because there is nothing to undo. A refusal is
        // silent too — the draft simply stays in the list, which is the safe outcome.
        { onSuccess: () => onDeleted?.(draftId) },
      );
      onClose();
      return;
    }
    flush();
    onClose();
  }

  return (
    <>
      {/* LP-858 §2/§3 — A PANE, NOT A MODAL. This was a Radix modal, which is what made reading a
          draft an interruption: the list vanished behind a scrim, and a processor comparing two
          drafts had to close one to see the other. The design contract names the component NOT to
          use as well as the one to use, because "everything became a modal" is what happened last
          time an unstated choice was left to a default.

          The two overlays that remain on this tab are the genuine interruptions — the mail-client
          question below, and the delete confirm — and they sit over this pane rather than
          replacing it. */}
      <section className="flex min-h-0 flex-1 flex-col" aria-label="Selected message">
        <header className="flex items-start justify-between gap-2 border-b border-border pb-2">
          <div className="flex min-w-0 flex-col">
            <h2 className="truncate text-base font-semibold text-foreground">
              {data?.subject ?? (isPending ? "Loading…" : "New message")}
            </h2>
            <p className="truncate text-xs text-muted-foreground">
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
            </p>
          </div>
          {/* THE CLOSE IS THE PANE'S OWN, because a pane has no scrim to click and no Escape
              handler of its own. §2's diagram puts it top-right of the right pane. */}
          <Button type="button" variant="ghost" size="sm" aria-label="Close" onClick={close}>
            <X className="h-4 w-4" aria-hidden />
          </Button>
        </header>

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
                {/* LP-857 — THE ADDRESS IS ASKED WHERE IT BLOCKS. This was a form inside "Write to
                      another party", a dialog on the Communication page that a processor opened only
                      if they already knew they needed it. A party draft with no address is created
                      anyway (LP-841 — the message is the part they want), so the question belongs
                      in front of the person who knows the answer at the moment it stops them.

                      ABOVE "Send to", not instead of it. The box below still works and still sends
                      this one message; what this adds is the option to record the address as a fact
                      about the file, which is the difference between answering once and answering
                      every time. */}
                {needsAnAddress ? (
                  <PartyAddressForm
                    fileId={fileId}
                    party={data.party as ResponsibleParty}
                    onSaved={setRecipient}
                  />
                ) : null}
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
                  {proposal === null ? (
                    <>
                      {/* LP-859 §1 — THE STORED BODY, UNCONVERTED. This passed
                          `emailBodyToHtml(data.body)` while ALSO passing `format="plain"`, so the
                          editor — whose own contract is *"`value`: the stored body; `format` says
                          which language it arrived in"* — converted it a second time. And
                          `emailBodyToHtml` escapes before it wraps, so the first pass's own `<p>`
                          came out as four characters of text. Every draft nobody had edited took
                          that path, because `body_format` is `plain` until a person writes into it:
                          it was the DEFAULT state of the screen, not an edge.

                          THE FIX IS THAT THE CALLER MUST NOT PRE-CONVERT A VALUE IT IS ALSO
                          LABELLING. Passing `format="html"` here would also have stopped the double
                          escape, and would have been the wrong fix: it makes the flag mean "what
                          this string is" in one place and "whether a person wrote it" in another,
                          which is the root cause wearing different clothes. LP-853 spent a ticket
                          making that column mean exactly one thing. */}
                      <MessageEditor
                        value={data.body}
                        format={data.body_format}
                        onChange={onEdit}
                      />
                      {/* LP-856 — ✦ polish. VIOLET, because violet in the Ledger marks
                            PROVENANCE — a model touched this — and never status. It is the one AI
                            control on this screen and it is the only violet thing on it.

                            AVAILABLE ON ANY DRAFT, not only a free one: a generated request a
                            processor has rewritten by hand is exactly where it is wanted.

                            LP-858 §5 — AND ABSENT WHEN IT IS NOT WIRED. `email_draft_enabled` is
                            false in every environment, so this button rendered, was pressed, and
                            answered with a sentence naming the environment as the reason. That is
                            not a bug — it is the flag doing its job — but it reads as breakage, and
                            the processor cannot switch it on, so the button could only ever
                            disappoint them. The page's own principle, applied to the one control
                            LP-857 did not reach: *"a processor cannot tell a feature that is broken
                            from one that was never wired."*

                            The old sentence is quoted NOWHERE in this repo: §9 greps the whole
                            frontend for it, and a comment repeating it would hold that check red
                            forever. */}
                      {polishAvailable ? (
                        <div className="flex flex-wrap items-center gap-2">
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            className="gap-1.5 border-ai text-ai hover:bg-ai/5 hover:text-ai"
                            disabled={polishDraft.isPending || bodyPlain.trim() === ""}
                            onClick={askForPolish}
                          >
                            <Sparkles className="h-3.5 w-3.5" aria-hidden />
                            {polishDraft.isPending ? "Polishing…" : "polish"}
                          </Button>
                          {polishRefusal ? (
                            // IT FAILS VISIBLY OR NOT AT ALL. Each reason is a sentence rather than
                            // a code, and none of them claims the text was changed.
                            <span className="text-xs text-warning">
                              {polishMessage(polishRefusal)}
                            </span>
                          ) : (
                            <span className="text-xs text-muted-foreground">
                              Rewrites how it reads. It cannot add a date, an amount or a document.
                            </span>
                          )}
                        </div>
                      ) : null}
                    </>
                  ) : (
                    /* THE PROPOSAL REPLACES THE EDITOR IN PLACE, under a violet header — Screen 8.
                         The original is held in `data.body` until one of the two actions is taken,
                         so "Undo" is a restore rather than a second rewrite. */
                    <div className="flex flex-col gap-2 border border-ai/40">
                      <p className="border-b border-ai/40 bg-ai/5 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-ai">
                        After ✦ polish — not saved yet
                      </p>
                      <div
                        className={`message-body break-words px-3 py-2 text-sm text-foreground ${BODY_PROSE}`}
                        // biome-ignore lint/security/noDangerouslySetInnerHtml: the proposal is model output rendered through the same escape-first renderer as a plain body — see below
                        dangerouslySetInnerHTML={{ __html: emailBodyToHtml(proposal) }}
                      />
                      <div className="flex flex-wrap justify-end gap-2 border-t border-ai/40 px-3 py-2">
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => setProposal(null)}
                        >
                          Undo — put mine back
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          onClick={() => {
                            // ACCEPTING IS A SAVE, which is what makes it authored content:
                            // LP-853's rule says the body becomes `html` the moment a person
                            // decides on it, and `_regenerate` then refuses it — correctly, since
                            // there is nothing to regenerate on a message somebody chose.
                            const html = emailBodyToHtml(proposal);
                            setBodyHtml(html);
                            setProposal(null);
                            save.mutate(
                              { draftId: data.id, body: html, subject },
                              { onSuccess: () => setFormat("html") },
                            );
                          }}
                        >
                          Keep this
                        </Button>
                      </div>
                    </div>
                  )}
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

                  {/* LP-834 — the secure link. LP-857 TAKES IT OFF WITH THE REST OF THE NEXT
                      PHASE, which this comment has been promising since LP-834.

                      NOT COSMETIC. This button mints a link and writes it into the body, so leaving
                      it while the upload panel is hidden would let a processor put a live upload
                      link in a message on a version that cannot receive anything through it — which
                      is acceptance 5 broken by a click rather than by a template. The server
                      refuses the same call for the same reason; this is the half a processor sees.
                      */}
                  {receiving ? (
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
                  ) : null}

                  {/* LP-858 §4 — DELETE, AFTER A SPACER, QUIET, IN DANGER TEXT. Specified since the
                      v1 spec's §6 and never built: the comment above this row described this exact
                      button and shipped without it, which is the failure the design contract's §6
                      rule exists to stop.

                      THE SPACER IS THE POINT, not decoration. It is the only destructive control on
                      the screen and it sits away from the three a processor presses all day, so the
                      miss that lands on it is a miss nobody makes twice. */}
                  <div className="ml-auto">
                    <Button
                      type="button"
                      variant="ghost"
                      className="text-danger hover:bg-danger/5 hover:text-danger"
                      disabled={deleteDraft.isPending}
                      onClick={() => (edited ? setConfirming(true) : removeDraft())}
                    >
                      <Trash2 className="h-4 w-4" aria-hidden /> Delete
                    </Button>
                  </div>
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
      </section>
      {/* LP-858 §1 — ASKED ON THE BUTTON, AND RENDERED LAST.

          LAST MEANS TOPMOST, and that half is still load-bearing. Radix marks everything outside
          the topmost modal `aria-hidden`, so with the picker rendered FIRST it was visible to
          `getByText` and absent from the accessibility tree: a question a screen reader never
          announced, sitting in front of the button it configures. Caught by the picker's own test
          failing to find its primary.

          WHAT CHANGED IS THE TRIGGER, NOT THE ORDER. The previous fix for that collision also
          suppressed the draft underneath (`open={open && !needsClient}`), which solved the
          accessibility bug by creating the one this ticket is about. Opening on a button press
          means there is never a second modal to collide with on mount — the draft is a pane now,
          not a competing dialog — so both fixes hold and neither is re-solved. */}
      {/* §7 — THE CONFIRM, on an edited draft only. `firstEditedLine` is derived from the body in
          the pane rather than from the stored one: the processor is looking at their own unsaved
          sentence, and quoting the last SAVED version back at them would show words that are not
          on their screen. */}
      <DeleteDraftDialog
        open={confirming}
        firstEditedLine={firstLineOf(bodyPlain)}
        pending={deleteDraft.isPending}
        onCancel={() => setConfirming(false)}
        onConfirm={removeDraft}
      />
      <MailClientDialog
        open={pickerOpen}
        suggested={preferences.data?.suggested_mail_client ?? "mailto"}
        reason={preferences.data?.mail_client_suggestion_reason ?? ""}
        pending={savePreferences.isPending}
        onChoose={(client) => {
          // THE ANSWER TAKES EFFECT NOW, not when the PUT returns. See `chosenClient`.
          setChosenClient(client);
          setPickerOpen(false);
          savePreferences.mutate({ mail_client: client });
          // AND THE ORIGINAL ACTION COMPLETES IN THE SAME GESTURE. The processor pressed
          // `Copy & open`; answering a question we interrupted them with is not a reason to make
          // them press it again. `client` is passed rather than read back from state, which has
          // not re-rendered yet.
          void copyAndOpen(client);
        }}
      />
    </>
  );
}

/**
 * The first line of a body that says something — for the delete confirm's quote.
 *
 * BLANK LINES ARE NOT THE FIRST LINE. A body that opens with a greeting and a gap would otherwise
 * quote the gap, and the confirm would ask a processor to recognise nothing at all.
 *
 * Returns "" for a body with no readable line, which the dialog renders as an ellipsis rather than
 * as an empty quote block.
 */
export function firstLineOf(plain: string): string {
  for (const line of (plain ?? "").split("\n")) {
    const trimmed = line.trim();
    if (trimmed) return trimmed;
  }
  return "";
}
