/**
 * The email body's schema — ONE list, and the three things that must agree with it (LP-854).
 *
 * THREE PLACES NAME THE SAME TAGS, and LP-849's own notes record what happens when two of them
 * drift: `htmlToEmailBody` stripped `**` from any `<strong>` ending in a colon while the renderer
 * re-bolded only a capitalised run of 3-41 characters, and everything in the gap lost its asterisks
 * on save. A processor watched their formatting vanish.
 *
 * The three, and the exact relation each has to this list:
 *
 *   1. **The Tiptap extensions** (`message-editor.tsx`) — EQUAL. A mark the editor can produce and
 *      the sanitiser strips is formatting that disappears on save; a tag the sanitiser allows and
 *      the editor cannot make is a hole nothing is watching.
 *   2. **The server allowlist** (`app/communications/sanitise.py`) — EQUAL, for the same two
 *      reasons from the other side. It is Python, so it cannot import this; `schema-drift.test.ts`
 *      reads it and fails when the two disagree.
 *   3. **`emailBodyToHtml`'s output** — a SUBSET. The plain body format has no syntax for underline,
 *      links, ordered lists or quotes, so the renderer cannot emit them and is not expected to. What
 *      must hold is that everything it DOES emit is allowed, or a generated draft would be mangled
 *      the first time anything sanitised it.
 *
 * ADDING A MARK MEANS ADDING IT HERE. `schema-drift.test.ts` then fails until the extension and the
 * allowlist follow, which is the point: the list is derived once and the other two are checked
 * against it, rather than three copies that happen to agree on the day they were written.
 */

/** Tag -> the attributes it may carry. Empty for everything except the link. */
export const EMAIL_SCHEMA: Record<string, readonly string[]> = {
  // LP-849's original four, plus the break the identification block needs.
  p: [],
  br: [],
  strong: [],
  ul: [],
  li: [],
  // LP-854 — the seven Gmail marks that need a tag of their own.
  //
  // `em` IS NEW DESPITE THE TICKET SAYING OTHERWISE. LP-854's table lists "Bold · Italic | have
  // them | LP-849", and italic was never built: `EXTENSIONS` had no `Italic` and `emailBodyToHtml`
  // emits no `<em>`. Screen 2's toolbar reads `B I U`, so it ships here with the rest.
  em: [],
  u: [],
  // `ol` reuses `li`; an ordered list is a different container, not a different item.
  ol: [],
  blockquote: [],
  a: ["href"],
};

/** Every tag the editor may produce and the sanitiser must keep. */
export const EMAIL_TAGS: readonly string[] = Object.keys(EMAIL_SCHEMA);

/**
 * The schemes an `href` may use.
 *
 * A LINK IN AN EMAIL TO A BORROWER IS A PHISHING SURFACE if we let it be. Enforced in the editor
 * AND in the server's sanitiser, because the editor is not a security boundary — a request built by
 * hand never goes through it at all.
 */
export const ALLOWED_SCHEMES: readonly string[] = ["http", "https", "mailto"];

/**
 * Which of these Word's rendering engine is known to be awkward about.
 *
 * OUTLOOK ON THE DESKTOP RENDERS WITH WORD, which is why the output carries no classes and no
 * stylesheet dependency. These are the tags to look at when somebody does LP-854's manual paste
 * test, so that "check it survives" is a list rather than a feeling:
 *
 *   • `blockquote` — Word keeps the element but applies its own indent; expect indentation rather
 *     than a left rule, and check the text is not flattened into the paragraph above.
 *   • nested `ul`/`ol` — indentation comes from the nesting, so a composer that flattens one level
 *     loses LP-846's detail block.
 *   • `u` — survives, but is also how several clients render a link; check an underlined word that
 *     is NOT a link does not become clickable.
 *   • `a` — check the href survives intact and the display text is not rewritten.
 *
 * `p`, `br`, `strong` and `em` are not on this list because they are the four every engine keeps.
 */
export const AT_RISK_IN_WORD: readonly string[] = ["blockquote", "ul", "ol", "u", "a"];
