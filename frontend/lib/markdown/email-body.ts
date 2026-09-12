/**
 * The email body as HTML, for the reader and for the clipboard (LP-844).
 *
 * WHY NOT A MARKDOWN LIBRARY. `send_draft` records a send; it does not transmit. A processor
 * delivers by copying the body into their own mail client, so the CLIPBOARD is the send path and
 * the HTML produced here is what actually reaches a borrower. That makes this an output surface
 * carrying a borrower's own words, a processor's free text and a rule's sentence — and every
 * general-purpose renderer has a raw-HTML passthrough that must be configured off, or paired with a
 * sanitiser. Neither `marked` nor `dompurify` is in this project today.
 *
 * ESCAPE FIRST, THEN BUILD. Every character that could start markup is neutralised before any tag
 * is emitted, so injection is impossible by construction rather than by configuration. There is no
 * passthrough to leave on, and no sanitiser whose rules have to keep up with the renderer's.
 *
 * A DELIBERATE SUBSET, matched to what the templates emit: paragraphs, `- ` bullets with their
 * indented detail lines, and `**bold**`. A body is a business letter, not a document — headings,
 * links, images, tables and code blocks are things we never write and therefore never parse.
 */

/** Neutralise everything that could begin markup. Runs before a single tag is emitted. */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * `**bold**` on ALREADY-ESCAPED text.
 *
 * Safe only in that order, and the order is the whole design: by the time this runs there is no `<`
 * left in the string that the author did not have escaped, so the tags it adds are the only tags
 * present.
 */
function inline(escaped: string): string {
  return escaped.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

const LIST_ITEM = /^[-*]\s+(.*)$/;

/**
 * The body as a self-contained HTML fragment.
 *
 * NO CLASSES AND NO STYLESHEET. This string is pasted into Gmail, Outlook or Word, which keep the
 * semantic tags and discard everything that depends on our page — a class name that styles the
 * detail lines here would leave them indistinguishable there. Emphasis and structure survive
 * because they are `<strong>` and `<ul>`, not because of CSS.
 */
export function emailBodyToHtml(body: string): string {
  const out: string[] = [];
  let list: string[] = [];
  let paragraph: string[] = [];

  const flushParagraph = () => {
    if (paragraph.length > 0) {
      out.push(`<p>${paragraph.join("<br>")}</p>`);
      paragraph = [];
    }
  };
  const flushList = () => {
    if (list.length > 0) {
      out.push(`<ul>${list.join("")}</ul>`);
      list = [];
    }
  };

  for (const raw of body.split("\n")) {
    const line = raw.replace(/\s+$/, "");
    if (line.trim() === "") {
      flushParagraph();
      flushList();
      continue;
    }
    const item = LIST_ITEM.exec(line.trim());
    if (item) {
      flushParagraph();
      list.push(`<li>${inline(escapeHtml(item[1] ?? ""))}`);
      continue;
    }
    // AN INDENTED LINE UNDER A BULLET IS THAT BULLET'S DETAIL, not a new paragraph and not a code
    // block. The catalog emits "Where to get it: …" indented beneath each document, and a general
    // markdown reader would treat four spaces as preformatted code — which is why the subset is
    // written against what the templates actually produce.
    if (list.length > 0 && /^\s+\S/.test(raw)) {
      list[list.length - 1] += `<br>${inline(escapeHtml(line.trim()))}`;
      continue;
    }
    flushList();
    paragraph.push(inline(escapeHtml(line)));
  }
  flushParagraph();
  flushList();
  // `</li>` is closed here rather than per push, because a detail line appends to the item that is
  // still open. Browsers forgive an unclosed `<li>`; a mail client pasted into may not.
  return out.join("\n").replace(/<li>((?:(?!<\/li>).)*?)(?=<\/ul>|<li>)/g, "<li>$1</li>");
}
