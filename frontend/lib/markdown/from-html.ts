/**
 * HTML back to the plain body we store (LP-849).
 *
 * THE EXACT INVERSE OF `emailBodyToHtml`, and it has to be. The editor is a WYSIWYG — a processor
 * never sees markup — but `Communication.body` stays ONE PLAIN STRING, because that is what the
 * templates emit, what `finalise_draft_body` resolves placeholders in, what `mailto:` can carry, and
 * what the send record means when it says "this is what went out". Storing HTML would cost every
 * template a new ADR-401 version to buy nothing a processor can see.
 *
 * So every keystroke round-trips: stored text → HTML → the editor → HTML → stored text. A lossy
 * inverse silently eats a processor's formatting, which is why this file exists separately and is
 * tested against the renderer rather than on its own.
 *
 * THE ONE ASYMMETRY, and it is deliberate. `emailBodyToHtml` renders a catalog detail line
 * "Where to get it: …" as `<strong>Where to get it:</strong> …`. It also renders a processor's own
 * `**bold**` as `<strong>bold</strong>`. The same HTML, two different plain forms — so the inverse
 * has to tell them apart, and it uses the renderer's own rule: a `<strong>` that OPENS a nested
 * detail item and ENDS IN A COLON is a label and loses its asterisks; anything else is emphasis and
 * keeps them. Getting this wrong inflates every template body with `**` on every reopen.
 */

const BOLD = /<strong>(.*?)<\/strong>/g;

/** Undo the five entities `escapeHtml` writes, and nothing else. */
function unescapeHtml(text: string): string {
  return (
    text
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      // LAST, mirroring `escapeHtml` doing it FIRST. Otherwise `&amp;lt;` — a literal "&lt;" the
      // author typed — decodes twice and becomes a "<" they never wrote.
      .replace(/&amp;/g, "&")
  );
}

/** Inline content to text. `asLabel` suppresses the `**` for a catalog label (see the header). */
function inlineText(html: string, { asLabel }: { asLabel: boolean }): string {
  const marked = html.replace(BOLD, (_match, inner: string) => {
    const content = String(inner);
    if (asLabel && content.trimEnd().endsWith(":")) return content;
    return `**${content}**`;
  });
  return unescapeHtml(marked.replace(/<br\s*\/?>/g, "\n").replace(/<[^>]+>/g, ""));
}

/**
 * A `<li>`'s own text, without its nested list.
 *
 * Split rather than parsed, because the nested `<ul>` is always at the END of an item the renderer
 * produced — a document's guidance follows its name — and a regex that tried to match balanced tags
 * would be the wrong tool for a structure we generate ourselves.
 */
function splitItem(html: string): { own: string; nested: string | null } {
  const at = html.indexOf("<ul>");
  if (at === -1) return { own: html, nested: null };
  const closed = html.lastIndexOf("</ul>");
  return { own: html.slice(0, at), nested: html.slice(at + 4, closed === -1 ? undefined : closed) };
}

/** `<li>…</li>` items at this level, ignoring any nested inside them. */
function items(listHtml: string): string[] {
  const found: string[] = [];
  let depth = 0;
  let start = -1;
  const tag = /<(\/?)(ul|li)>/g;
  let match = tag.exec(listHtml);
  while (match !== null) {
    const closing = match[1] === "/";
    const name = match[2];
    if (name === "ul") depth += closing ? -1 : 1;
    else if (depth === 0) {
      if (!closing) start = match.index + match[0].length;
      else if (start !== -1) {
        found.push(listHtml.slice(start, match.index));
        start = -1;
      }
    }
    match = tag.exec(listHtml);
  }
  return found;
}

/**
 * The stored body for `html`.
 *
 * INDENTED WITH FOUR SPACES, which is what the catalog emits and therefore what the renderer's
 * detail rule recognises. Any other width round-trips to a paragraph instead of a detail line.
 */
/**
 * Top-level `<p>` and `<ul>` blocks, in order.
 *
 * DEPTH-AWARE, not a regex. The first version used `/<(p|ul)>([\s\S]*?)<\/\1>/g` and a non-greedy
 * match stops at the FIRST `</ul>` — which, for a document with nested guidance, is the inner one.
 * Every catalog body came back empty or inside out, which is the one shape that actually matters
 * here.
 */
function blocksOf(html: string): { kind: string; inner: string }[] {
  const found: { kind: string; inner: string }[] = [];
  const tag = /<(\/?)(p|ul)>/g;
  let depth = 0;
  let kind = "";
  let start = -1;
  let match = tag.exec(html);
  while (match !== null) {
    const closing = match[1] === "/";
    const name = match[2] ?? "";
    if (!closing) {
      if (depth === 0) {
        kind = name;
        start = match.index + match[0].length;
      }
      depth += 1;
    } else {
      depth -= 1;
      if (depth === 0 && start !== -1) {
        found.push({ kind, inner: html.slice(start, match.index) });
        start = -1;
      }
    }
    match = tag.exec(html);
  }
  return found;
}

/**
 * The stored body for `html`.
 *
 * INDENTED WITH FOUR SPACES, which is what the catalog emits and therefore what the renderer's
 * detail rule recognises. Any other width round-trips to a paragraph instead of a detail line.
 */
export function htmlToEmailBody(html: string): string {
  const blocks: string[] = [];
  for (const { kind, inner } of blocksOf(html)) {
    if (kind === "p") {
      blocks.push(inlineText(inner, { asLabel: false }));
      continue;
    }
    const lines: string[] = [];
    for (const item of items(inner)) {
      const { own, nested } = splitItem(item);
      lines.push(`- ${inlineText(own, { asLabel: false })}`);
      if (nested) {
        for (const detail of items(nested)) {
          lines.push(`    ${inlineText(detail, { asLabel: true })}`);
        }
      }
    }
    blocks.push(lines.join("\n"));
  }
  return blocks.join("\n\n");
}
