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
/** `Where to get it: …` — a catalog detail line, whose label is worth seeing separately. */
const LABELLED = /^([A-Z][^:]{2,40}):\s*(.*)$/;

/**
 * Whether `text` is a label THIS RENDERER WOULD ITSELF EMPHASISE — exported so the inverse strips the
 * asterisks for exactly those and no others (LP-849 review).
 *
 * THE TWO RULES HAD DRIFTED, which is the whole reason this is a function rather than a comment.
 * `htmlToEmailBody` removed the `**` from any `<strong>` ending in a colon; this rule re-bolds only a
 * capitalised run of three to forty-one characters. Everything in the gap — `**note:**`, `**A:**`,
 * `**2 things:**`, a label longer than forty-one characters — lost its asterisks on the way to storage
 * and was not bolded on the way back. A processor watched their formatting vanish on save, which is
 * the exact failure the editor's schema restriction exists to prevent.
 *
 * Derived from `LABELLED` rather than restating it, so a change to one cannot leave the other behind.
 */
export function isCatalogLabel(text: string): boolean {
  const trimmed = text.trimEnd();
  if (!trimmed.endsWith(":")) return false;
  const match = LABELLED.exec(`${trimmed} rest`);
  return match !== null && `${match[1]}:` === trimmed;
}

/**
 * One document's detail lines, as a nested list (LP-846).
 *
 * A NESTED `<ul>` RATHER THAN `<br>` OR A CLASS, and the constraint decides it. The clipboard's
 * HTML carries no classes and a mail client discards our stylesheet, so indentation has to come
 * from a tag a composer keeps. A nested list is the only structure that indents AND separates
 * without CSS — `<br>`-joining is what LP-844 did, and it turned three labelled facts into one
 * run-on sentence inside the bullet.
 *
 * THE LABEL IS EMPHASISED SEPARATELY because it is what makes the block scannable: a borrower
 * looking for where to get a document should find "Where to get it:" without reading the sentence
 * around it. `<strong>` survives a paste; a colour or an indent would not.
 */
function detailBlock(lines: string[]): string {
  const items = lines.map((line) => {
    const labelled = LABELLED.exec(line);
    if (!labelled) return `<li>${inline(escapeHtml(line))}</li>`;
    const label = escapeHtml(labelled[1] ?? "");
    const rest = inline(escapeHtml(labelled[2] ?? ""));
    return `<li><strong>${label}:</strong> ${rest}</li>`;
  });
  return `<ul>${items.join("")}</ul>`;
}

export function emailBodyToHtml(body: string): string {
  const out: string[] = [];
  /** Open list items, each with its own detail lines. */
  let items: { text: string; details: string[] }[] = [];
  let paragraph: string[] = [];
  /** A blank line was seen and not yet acted on — see the flush rules below. */
  let blank = false;

  const flushParagraph = () => {
    if (paragraph.length > 0) {
      out.push(`<p>${paragraph.join("<br>")}</p>`);
      paragraph = [];
    }
  };
  const flushList = () => {
    if (items.length > 0) {
      const rendered = items.map(
        (item) =>
          `<li>${item.text}${item.details.length > 0 ? detailBlock(item.details) : ""}</li>`,
      );
      out.push(`<ul>${rendered.join("")}</ul>`);
      items = [];
    }
  };

  for (const raw of body.split("\n")) {
    const line = raw.replace(/\s+$/, "");
    if (line.trim() === "") {
      // A BLANK LINE ENDS A PARAGRAPH BUT NOT A LIST. The catalog separates documents with one, and
      // flushing on it made every document its own single-item `<ul>` — two documents rendering as
      // two lists with a gap between them rather than as one list of two.
      flushParagraph();
      blank = true;
      continue;
    }
    const item = LIST_ITEM.exec(line.trim());
    if (item) {
      flushParagraph();
      items.push({ text: inline(escapeHtml(item[1] ?? "")), details: [] });
      blank = false;
      continue;
    }
    const indented = /^\s+\S/.test(raw);
    // AN INDENTED LINE IMMEDIATELY UNDER A BULLET is that bullet's detail. Separated from it by a
    // blank line it is not: the borrower template indents `$inbox_address` further down, and
    // adopting it into the document above would put the file's address inside "what we cannot
    // accept".
    if (indented && items.length > 0 && !blank) {
      const last = items[items.length - 1];
      if (last) last.details.push(line.trim());
      continue;
    }
    flushList();
    paragraph.push(inline(escapeHtml(line)));
    blank = false;
  }
  flushParagraph();
  flushList();
  return out.join("\n");
}
