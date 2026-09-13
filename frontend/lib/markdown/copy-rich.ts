import { emailBodyToHtml } from "@/lib/markdown/email-body";
import { htmlToEmailBody } from "@/lib/markdown/from-html";

/**
 * Put a message on the clipboard in BOTH flavours (LP-844).
 *
 * THE CLIPBOARD IS THE SEND PATH. `send_draft` records that a message went out; it does not
 * transmit. A processor delivers by pasting into their own Gmail or Outlook, so whether bold and
 * bullets survive is decided here and nowhere else.
 *
 * `text/html` AND `text/plain` TOGETHER, not one or the other. A mail composer takes the HTML and
 * keeps the structure; a plain textarea, a terminal, a notes app take the text. Writing only HTML
 * would paste tag soup into anything that cannot read it, and writing only text is what this
 * function exists to stop.
 *
 * FALLS BACK TO TEXT RATHER THAN FAILING. `ClipboardItem` is unavailable in some browsers and
 * throws behind a few privacy settings; a processor whose copy silently did nothing has no way to
 * send the message at all, and plain text is exactly what they had before this ticket. The return
 * value says which happened so a caller can tell them the truth about it.
 */
export async function copyMessage(
  body: string,
  format: "plain" | "html" = "plain",
): Promise<"rich" | "plain"> {
  // LP-853 — THE PAIRING IS UNTOUCHED; ONLY THE SOURCE CHANGED. A `plain` body is still rendered by
  // `emailBodyToHtml`, which is the single renderer for that path. An `html` body is what a
  // processor wrote and what the server already sanitised, so it IS the rich flavour — rendering it
  // again would escape their own tags into the clipboard — and its plain flavour is derived by
  // `htmlToEmailBody` rather than stored, because two stored copies of one message is the
  // anti-pattern this ticket declines twice.
  const html = format === "html" ? body : emailBodyToHtml(body);
  const plain = format === "html" ? htmlToEmailBody(body) : body;
  try {
    if (typeof ClipboardItem !== "undefined" && navigator.clipboard?.write) {
      await navigator.clipboard.write([
        new ClipboardItem({
          "text/html": new Blob([html], { type: "text/html" }),
          "text/plain": new Blob([plain], { type: "text/plain" }),
        }),
      ]);
      return "rich";
    }
  } catch {
    // Fall through. The catch is deliberately silent: the fallback below is a complete answer, and
    // an error toast about a clipboard flavour is noise on top of a copy that worked.
  }
  await navigator.clipboard.writeText(plain);
  return "plain";
}
