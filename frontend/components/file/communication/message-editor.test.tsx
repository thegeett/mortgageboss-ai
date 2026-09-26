// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { emailBodyToHtml } from "@/lib/markdown/email-body";
import { htmlToEmailBody } from "@/lib/markdown/from-html";
import { EMAIL_TAGS } from "@/lib/markdown/schema";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Editor } from "@tiptap/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EXTENSIONS, MessageEditor, isSafeHref } from "./message-editor";

/**
 * LP-849 — a rich box, and the plain body it keeps underneath.
 *
 * The requirements are all about what a processor SEES: a toolbar, no markup anywhere, and a copy
 * that pastes as ordinary formatted text. The storage staying plain is how the templates, the
 * placeholder pass, `mailto:` and the audit record keep working — so what these assert is that both
 * halves are true at once.
 */
afterEach(cleanup);

/**
 * How long to let a real ProseMirror editor mount in jsdom before calling it a failure.
 *
 * ⚠️ `vi.waitFor` DEFAULTS TO 1000ms, AND THAT IS THE ARBITRARY PART. Measured on a Raspberry Pi,
 * the mount cases in this file run 834ms and 930ms IDLE — 83% and 93% of the default budget with no
 * load at all. The sibling `message-dialog.test.tsx` already lost that coin flip under the full
 * suite's parallel workers (LP-909 §5). Waiting longer for an async mount is what `waitFor` is for.
 *
 * Kept below vitest's 5000ms `testTimeout` so a genuinely broken editor reports this wait by name
 * rather than a bare test timeout.
 */
const EDITOR_MOUNT_MS = 4000;

const CATALOG_BODY = [
  "- Driver's licence — front and back",
  "    Where to get it: A photograph or scan of your current licence.",
].join("\n");

describe("MessageEditor", () => {
  it("shows the body as formatted text, with no markup visible", async () => {
    render(<MessageEditor value="Send the **most recent** statement" onChange={vi.fn()} />);

    // THE REPORTED REQUIREMENT: "user should not see html tag or markdown."
    //
    // ⚠️ THE WAIT USED TO POLL A SNAPSHOT, WHICH MEANS IT NEVER WAITED FOR ANYTHING. `text` was read
    // into a const BEFORE the `waitFor`, and the callback then asserted on that frozen string — so it
    // could only pass on the first tick or spin the full timeout and fail. A `waitFor` over a value
    // captured outside it cannot observe the change it is waiting for, and every assertion below ran
    // against whatever the very first tick happened to hold.
    //
    // It survived because the editor usually mounts before the first poll. That makes it a race that
    // was being won rather than a wait, and raising its timeout would have made it strictly worse:
    // a longer spin on a condition that cannot change.
    await vi.waitFor(
      () => expect(document.querySelector(".ProseMirror")?.textContent).toBeTruthy(),
      EDITOR_MOUNT_MS,
    );
    const text = document.querySelector(".ProseMirror")?.textContent ?? "";
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
/**
 * LP-854 — THE LIST MOVED. `EMAIL_SCHEMA` is the one place the tag set is written down now, and
 * `schema-drift.test.ts` is what holds the Tiptap extensions, the server allowlist and the
 * renderer's output to it. What stays here is the half that is about THIS component: which
 * `@tiptap/extension-*` packages it pulls in, and that it does not reach for StarterKit.
 */
const SCHEMA: Record<string, string | null> = {
  document: null,
  text: null,
  extensions: null, // `UndoRedo` — a history stack, not a tag
  paragraph: "p",
  bold: "strong",
  italic: "em",
  underline: "u",
  "bullet-list": "ul",
  "ordered-list": "ol",
  "list-item": "li",
  blockquote: "blockquote",
  link: "a",
  "hard-break": "br",
};

describe("the editor's schema and the renderer agree", () => {
  const source = readFileSync(
    join(process.cwd(), "components/file/communication/message-editor.tsx"),
    "utf8",
  );

  it("enables exactly the extensions the renderer can express", () => {
    // LP-854 — `@tiptap/extensions` IS MATCHED TOO. The pattern was `extension-([a-z-]+)`, which
    // does not match the bundle package `@tiptap/extensions` — so `UndoRedo` was imported from a
    // package this scan could not see. That is the same shape as every other narrow-guard finding
    // in this epic: a scan that does not look somewhere looks exactly like a clean scan.
    const enabled = [...source.matchAll(/@tiptap\/(extensions|extension-[a-z-]+)/g)].map((m) =>
      (m[1] ?? "").replace(/^extension-/, ""),
    );
    // THE POSITIVE CONTROL. An empty scan — a renamed file, a changed import style — would satisfy
    // the comparison below by finding nothing, which is the failure mode this whole block is about.
    expect(enabled.length).toBeGreaterThan(0);
    expect([...enabled].sort()).toEqual(Object.keys(SCHEMA).sort());
  });

  it("and every one of them produces a tag the schema owns", () => {
    // LP-854 — AGAINST `EMAIL_TAGS`, not against the renderer's output. The renderer emits a SUBSET
    // now: the plain body format has no syntax for underline, links, ordered lists or quotes, so
    // requiring `emailBodyToHtml` to emit them would be requiring it to parse something no template
    // writes. `schema-drift.test.ts` holds the subset relation.
    for (const [extension, tag] of Object.entries(SCHEMA)) {
      if (tag === null) continue;
      expect(
        EMAIL_TAGS,
        `${extension} produces <${tag}>, which the schema does not allow`,
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

/**
 * LP-853 — what the editor emits, and when.
 *
 * ACCEPTANCE 2 LIVES HERE, not in the dialog. "Opening a generated draft and not typing leaves it
 * `plain`" rests on one fact: Tiptap reports a change when the DOCUMENT changes and at no other
 * time. The dialog's own guard cannot be the primary one — React bails out of a state update that
 * sets an identical string, so a test of it there passes with the guard deleted.
 */
describe("what the editor reports, and when", () => {
  it("reports nothing on mount, or on focus", async () => {
    const onChange = vi.fn();
    render(
      <MessageEditor value="Hello Sarah,\n\nPlease send the statements." onChange={onChange} />,
    );

    // Wait for the editor to actually exist, or this asserts about an empty tree.
    await vi.waitFor(
      () => expect(document.querySelector(".ProseMirror")).not.toBeNull(),
      EDITOR_MOUNT_MS,
    );
    const surface = document.querySelector(".ProseMirror") as HTMLElement;
    surface.focus();
    surface.dispatchEvent(new Event("focus", { bubbles: true }));
    surface.click();

    expect(onChange).not.toHaveBeenCalled();
  });

  it("reports HTML — not a plain body — when the document changes", async () => {
    // THE POSITIVE CONTROL for the case above, and the LP-853 storage change in one assertion.
    //
    // DRIVEN THROUGH THE COMPONENT'S OWN TOOLBAR, not through a hand-built `Editor`. A test that
    // constructed its own editor with its own `onUpdate` would assert that Tiptap works — it
    // passes with `MessageEditor` still serialising to plain text, which is LP-849's behaviour and
    // would quietly undo this whole ticket. Clicking "Bulleted list" changes the document, which
    // is the one thing that makes the component report at all.
    const onChange = vi.fn();
    render(<MessageEditor value="Bank statement" onChange={onChange} />);
    await vi.waitFor(
      () => expect(document.querySelector(".ProseMirror")).not.toBeNull(),
      EDITOR_MOUNT_MS,
    );

    fireEvent.click(screen.getByRole("button", { name: "Bulleted list" }));

    expect(onChange).toHaveBeenCalled();
    const reported = onChange.mock.calls.at(-1)?.[0] as string;
    // HTML, and specifically the tag the click produced.
    expect(reported).toContain("<ul>");
    expect(reported).toContain("<li>");
    expect(reported).toContain("Bank statement");
    // And NOT the plain form, which is what LP-849 emitted here.
    expect(reported).not.toMatch(/^- /);
  });
});

/**
 * LP-854 — the seven marks, driven through the REAL schema.
 *
 * ACCEPTANCE 1 is "apply → save → reopen → still there, and the stored HTML contains only
 * allowlisted tags". The save and the reopen are `getHTML()` and `content:` — that is exactly what
 * the dialog does — and "only allowlisted tags" is checked against `EMAIL_TAGS`, the same list the
 * server's allowlist is held to.
 */
describe("the seven marks round-trip", () => {
  /** Apply a command, read the HTML back, and load it again — the save and the reopen. */
  function through(apply: (editor: Editor) => void): string {
    const element = document.createElement("div");
    document.body.appendChild(element);
    const editor = new Editor({
      element,
      extensions: EXTENSIONS,
      content: "<p>Please send the March statement</p>",
    });
    try {
      editor.commands.selectAll();
      apply(editor);
      const saved = editor.getHTML();

      const second = document.createElement("div");
      document.body.appendChild(second);
      const reopened = new Editor({ element: second, extensions: EXTENSIONS, content: saved });
      try {
        return reopened.getHTML();
      } finally {
        reopened.destroy();
        second.remove();
      }
    } finally {
      editor.destroy();
      element.remove();
    }
  }

  const CASES: [string, (editor: Editor) => void, string][] = [
    ["bold", (e) => e.commands.toggleBold(), "strong"],
    ["italic", (e) => e.commands.toggleItalic(), "em"],
    ["underline", (e) => e.commands.toggleUnderline(), "u"],
    ["bulleted list", (e) => e.commands.toggleBulletList(), "ul"],
    ["numbered list", (e) => e.commands.toggleOrderedList(), "ol"],
    ["quote", (e) => e.commands.toggleBlockquote(), "blockquote"],
    ["link", (e) => e.commands.setLink({ href: "https://example.com/docs" }), "a"],
  ];

  for (const [name, apply, tag] of CASES) {
    it(`${name} survives a save and a reopen`, () => {
      const html = through(apply);
      expect(html).toContain(`<${tag}`);
      expect(html).toContain("March statement");
    });
  }

  it("indent nests a list, which is where the indentation comes from", () => {
    // It is the only indentation that survives a paste, because it comes from a TAG rather than
    // from a margin — and it is how LP-846's nested detail block is built.
    const element = document.createElement("div");
    document.body.appendChild(element);
    const editor = new Editor({
      element,
      extensions: EXTENSIONS,
      content: "<ul><li><p>one</p></li><li><p>two</p></li></ul>",
    });
    try {
      // Put the cursor in the SECOND item, which is the only one that can sink.
      editor.commands.setTextSelection(editor.state.doc.content.size - 4);
      editor.commands.sinkListItem("listItem");
      expect(editor.getHTML()).toMatch(/<ul>[\s\S]*<ul>/);
    } finally {
      editor.destroy();
      element.remove();
    }
  });

  it("produces ONLY tags the schema allows", () => {
    // The other half of acceptance 1, and the one that catches a mark the server would strip: a tag
    // the editor can make and `sanitise.py` does not keep is formatting that vanishes on save.
    const everything = CASES.map(([, apply]) => through(apply)).join("");
    const produced = new Set(
      [...everything.matchAll(/<\/?([a-z0-9]+)/g)].map((match) => match[1] ?? ""),
    );
    expect(produced.size).toBeGreaterThan(0);
    for (const tag of produced) {
      expect(EMAIL_TAGS, `the editor produced <${tag}>`).toContain(tag);
    }
  });

  it("emits no class and no inline style", () => {
    // OUTLOOK ON THE DESKTOP RENDERS WITH WORD'S ENGINE and discards most CSS, so anything that
    // leaned on a stylesheet would arrive unformatted. The editor's own styling is on the
    // contenteditable container, never in the content.
    const everything = CASES.map(([, apply]) => through(apply)).join("");
    expect(everything).not.toContain("class=");
    expect(everything).not.toContain("style=");
    expect(everything).not.toContain("target=");
    expect(everything).not.toContain("rel=");
  });
});

describe("a link's address", () => {
  it("ACCEPTANCE 3 — the editor refuses a javascript: href", () => {
    // The editor is NOT the security boundary — `sanitise.py` is, and refuses it there too
    // (`test_a_refused_link_loses_the_TAG_not_just_the_href`). This is the half that stops a
    // processor pasting something dangerous by accident, and it has to SAY it refused: a control
    // that silently does nothing reads as broken rather than as declining.
    expect(isSafeHref("javascript:alert(1)")).toBe(false);
    expect(isSafeHref("JaVaScRiPt:alert(1)")).toBe(false);
    expect(isSafeHref("java\tscript:alert(1)")).toBe(false);
    expect(isSafeHref("  javascript:alert(1)")).toBe(false);
    expect(isSafeHref("data:text/html,<script>x</script>")).toBe(false);
    expect(isSafeHref("vbscript:msgbox(1)")).toBe(false);
    expect(isSafeHref("/relative")).toBe(false);
    expect(isSafeHref("#anchor")).toBe(false);
  });

  it("keeps the three schemes a request legitimately uses", () => {
    // THE CONTROL. A rule that refused everything would satisfy every assertion above and make the
    // Link button useless.
    expect(isSafeHref("https://example.com/docs")).toBe(true);
    expect(isSafeHref("http://example.com")).toBe(true);
    expect(isSafeHref("HTTPS://EXAMPLE.COM")).toBe(true);
    expect(isSafeHref("mailto:closings@acmetitle.example")).toBe(true);
  });

  it("the schema itself refuses it, not just the prompt", () => {
    // `Link.configure({ protocols })` is the second half: a paste carries an href that never goes
    // near `promptForLink`.
    const element = document.createElement("div");
    document.body.appendChild(element);
    const editor = new Editor({
      element,
      extensions: EXTENSIONS,
      content: '<p><a href="javascript:alert(1)">click</a></p>',
    });
    try {
      expect(editor.getHTML()).not.toContain("javascript:");
    } finally {
      editor.destroy();
      element.remove();
    }
  });
});

describe("no markup is visible to the processor", () => {
  it("ACCEPTANCE 5 — the new marks render as formatting, not as tags", () => {
    // LP-849's requirement, extended to the seven. A `**` on screen is a failure and so is a raw
    // `<a href>`.
    render(
      <MessageEditor
        format="html"
        value={
          "<p><em>italic</em> <u>under</u></p><ol><li>one</li></ol>" +
          '<blockquote>quoted</blockquote><p><a href="https://example.com">link text</a></p>'
        }
        onChange={vi.fn()}
      />,
    );

    const text = document.querySelector(".ProseMirror")?.textContent ?? "";
    expect(text).not.toContain("<");
    expect(text).not.toContain("href");
    expect(text).toContain("italic");
    expect(text).toContain("link text");
    // And they ARE the elements, not text that happens to read the same.
    expect(document.querySelector(".ProseMirror em")).not.toBeNull();
    expect(document.querySelector(".ProseMirror u")).not.toBeNull();
    expect(document.querySelector(".ProseMirror ol")).not.toBeNull();
    expect(document.querySelector(".ProseMirror blockquote")).not.toBeNull();
    expect(document.querySelector(".ProseMirror a")).not.toBeNull();
  });
});

describe("Remove formatting", () => {
  /**
   * ACCEPTANCE 2 — a styled block pasted from Word or a web page, returned to plain paragraphs.
   *
   * WITHOUT IT A BAD PASTE IS UNFIXABLE and the processor retypes the message, which is the whole
   * argument for the button. The paste is simulated by loading the markup Tiptap would have parsed
   * it into: what the button has to undo is the DOCUMENT, and driving a real clipboard through
   * jsdom would test the simulation.
   */
  function cleared(content: string): string {
    const element = document.createElement("div");
    document.body.appendChild(element);
    const editor = new Editor({ element, extensions: EXTENSIONS, content });
    try {
      editor.commands.selectAll();
      // BOTH COMMANDS. `unsetAllMarks` takes the inline marks and `clearNodes` takes the blocks —
      // a pasted quote or list is a NODE and survives the first alone.
      editor.commands.unsetAllMarks();
      editor.commands.clearNodes();
      return editor.getHTML();
    } finally {
      editor.destroy();
      element.remove();
    }
  }

  it("returns a styled paste to plain paragraphs with no residue", () => {
    const pasted =
      "<p><strong>Bold</strong> and <em>italic</em> and <u>under</u></p>" +
      "<blockquote><p>quoted</p></blockquote>" +
      "<ol><li><p>one</p></li><li><p>two</p></li></ol>" +
      "<ul><li><p>bullet</p></li></ul>" +
      '<p><a href="https://example.com">link</a></p>';

    const out = cleared(pasted);

    for (const tag of ["strong", "em", "u", "blockquote", "ol", "ul", "li", "a"]) {
      expect(out, `<${tag}> survived Remove formatting`).not.toContain(`<${tag}`);
    }
    // AND THE WORDS ARE ALL STILL THERE. A "clear" that deleted the content would satisfy every
    // assertion above, and would be the worst possible reading of the button.
    for (const word of ["Bold", "italic", "under", "quoted", "one", "two", "bullet", "link"]) {
      expect(out, `"${word}" was deleted rather than unformatted`).toContain(word);
    }
    expect(out).toContain("<p>");
  });

  it("leaves an already-plain body alone", () => {
    // THE CONTROL: a command that rewrote everything would pass the case above.
    expect(cleared("<p>Please send the March statement</p>")).toBe(
      "<p>Please send the March statement</p>",
    );
  });
});
