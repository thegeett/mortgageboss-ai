// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { emailBodyToHtml } from "@/lib/markdown/email-body";
import { htmlToEmailBody } from "@/lib/markdown/from-html";
import { cleanup, render, screen } from "@testing-library/react";
import { Editor } from "@tiptap/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EXTENSIONS, MessageEditor } from "./message-editor";

/**
 * LP-849 — a rich box, and the plain body it keeps underneath.
 *
 * The requirements are all about what a processor SEES: a toolbar, no markup anywhere, and a copy
 * that pastes as ordinary formatted text. The storage staying plain is how the templates, the
 * placeholder pass, `mailto:` and the audit record keep working — so what these assert is that both
 * halves are true at once.
 */
afterEach(cleanup);

const CATALOG_BODY = [
  "- Driver's licence — front and back",
  "    Where to get it: A photograph or scan of your current licence.",
].join("\n");

describe("MessageEditor", () => {
  it("shows the body as formatted text, with no markup visible", async () => {
    render(<MessageEditor value="Send the **most recent** statement" onChange={vi.fn()} />);

    // THE REPORTED REQUIREMENT: "user should not see html tag or markdown."
    const text = document.querySelector(".ProseMirror")?.textContent ?? "";
    await vi.waitFor(() => expect(text.length).toBeGreaterThan(0));
    expect(text).not.toContain("**");
    expect(text).not.toContain("<strong>");
    expect(text).toContain("most recent");
    // And it IS emphasis rather than plain text that happens to read the same.
    expect(document.querySelector(".ProseMirror strong")?.textContent).toBe("most recent");
  });

  it("renders a document's guidance as a nested list", () => {
    render(<MessageEditor value={CATALOG_BODY} onChange={vi.fn()} />);

    const nested = document.querySelectorAll(".ProseMirror ul ul li");
    expect(nested.length).toBe(1);
    expect(nested[0]?.textContent).toContain("Where to get it:");
    // The label keeps its emphasis without a `**` in sight — LP-846's shape, in the editor.
    expect(document.querySelector(".ProseMirror ul ul strong")?.textContent).toBe(
      "Where to get it:",
    );
  });

  it("offers bold and bullets, and says whether they are on", () => {
    render(<MessageEditor value="Hello," onChange={vi.fn()} />);

    const bold = screen.getByRole("button", { name: "Bold" });
    const bullets = screen.getByRole("button", { name: "Bulleted list" });
    // `aria-pressed`, because whether bold is ON is state — a colour alone says it only to someone
    // who can see it.
    expect(bold.getAttribute("aria-pressed")).toBe("false");
    expect(bullets.getAttribute("aria-pressed")).toBe("false");
  });

  it("cannot produce a shape the renderer would silently drop", () => {
    // THE SCHEMA IS THE CONTRACT. The extension set is the subset `emailBodyToHtml` supports, so an
    // editor that could make a heading would make one the renderer drops on save — a processor
    // watching their formatting vanish. Asserted on the schema rather than by trying to type one,
    // because the guarantee is structural.
    render(<MessageEditor value="Hello," onChange={vi.fn()} />);
    const editor = document.querySelector(".ProseMirror");
    expect(editor).not.toBeNull();
    expect(document.querySelectorAll(".ProseMirror h1, .ProseMirror h2").length).toBe(0);
  });
});

/**
 * THE SCHEMA IS THE CONTRACT, ENUMERATED (LP-849 review).
 *
 * The ticket's own assertion — that no `h1` or `h2` renders — is the absence of a thing nothing tries
 * to create, and it says so. It passes on a build with headings enabled and nothing that makes one,
 * and it says nothing at all about italics, links, code, ordered lists or strikethrough.
 *
 * So enumerate instead: every `@tiptap/extension-*` the editor pulls in, against the five tags
 * `emailBodyToHtml` owns. An extension producing anything else is markup the renderer silently drops
 * on save, and a processor watching their formatting vanish is the failure the schema exists to
 * prevent. Adding one means teaching the renderer and its inverse first — which is what failing this
 * test is telling you to do.
 */
const RENDERER_TAGS = new Set(["p", "br", "ul", "li", "strong"]);

/** Each enabled extension, and the renderer tag it produces. `null` is structural and emits none. */
const SCHEMA: Record<string, string | null> = {
  document: null,
  text: null,
  paragraph: "p",
  bold: "strong",
  "bullet-list": "ul",
  "list-item": "li",
  "hard-break": "br",
};

describe("the editor's schema and the renderer agree", () => {
  const source = readFileSync(
    join(process.cwd(), "components/file/communication/message-editor.tsx"),
    "utf8",
  );

  it("enables exactly the extensions the renderer can express", () => {
    const enabled = [...source.matchAll(/@tiptap\/extension-([a-z-]+)/g)].map((m) => m[1] ?? "");
    // THE POSITIVE CONTROL. An empty scan — a renamed file, a changed import style — would satisfy
    // the comparison below by finding nothing, which is the failure mode this whole block is about.
    expect(enabled.length).toBeGreaterThan(0);
    expect([...enabled].sort()).toEqual(Object.keys(SCHEMA).sort());
  });

  it("and every one of them produces a tag the renderer owns", () => {
    for (const [extension, tag] of Object.entries(SCHEMA)) {
      if (tag === null) continue;
      expect(
        RENDERER_TAGS,
        `${extension} produces <${tag}>, which the renderer does not emit`,
      ).toContain(tag);
    }
  });

  it("does not pull in StarterKit, which would enable the rest of them silently", () => {
    // The one import that makes this whole check meaningless: StarterKit brings headings, italic,
    // code, blockquote, ordered lists and strike, none of which survive a round trip through a plain
    // body. It is absent from the component AND from the dependency list, because a dependency
    // nobody imports today is one somebody imports tomorrow.
    expect(source).not.toContain("starter-kit");
    const manifest = readFileSync(join(process.cwd(), "package.json"), "utf8");
    expect(manifest).not.toContain("@tiptap/starter-kit");
  });
});

/**
 * THE THIRD PATH (LP-849 review).
 *
 * `round-trip.test.ts` checks `emailBodyToHtml` against `htmlToEmailBody` as a fixed point, which is
 * the right property for those two. But the editor is not those two: the real sequence is stored text
 * → HTML → **Tiptap parses it** → Tiptap re-serialises it → HTML → stored text, and the middle two
 * steps are somebody else's parser normalising entities, whitespace and attributes.
 *
 * The ticket raises the entity question and answers it for the two functions it owns. Nothing ran the
 * hop between them. So this drives the real schema: content in, `getHTML()` out, and the stored body
 * must come back identical — including the entity cases, where a literal `&lt;` a processor typed must
 * not arrive as a `<`.
 */
const THROUGH_THE_EDITOR: [string, string][] = [
  ["a catalog body with nested guidance", CATALOG_BODY],
  ["a paragraph and a list", "Hello,\n\n- Bank statement\n- W-2\n\nThanks"],
  ["emphasis the processor typed", "Please send the **original**, not a copy"],
  ["a label the catalog emits", "- Licence\n    Where to get it: your wallet"],
  ["a literal entity the processor typed", "Type &lt;name&gt; in the form"],
  ["an ampersand", "Smith & Sons, and &amp; too"],
  ["quotes and apostrophes", `She said "it's fine" & left`],
  ["two lines in one paragraph", "Acme Mortgage\n123 Main Street"],
];

describe("a body driven through the real editor schema", () => {
  for (const [name, body] of THROUGH_THE_EDITOR) {
    it(`comes back unchanged: ${name}`, () => {
      const element = document.createElement("div");
      document.body.appendChild(element);
      const editor = new Editor({
        element,
        extensions: EXTENSIONS,
        content: emailBodyToHtml(body),
      });
      try {
        expect(htmlToEmailBody(editor.getHTML())).toBe(body);
      } finally {
        editor.destroy();
        element.remove();
      }
    });
  }
});
