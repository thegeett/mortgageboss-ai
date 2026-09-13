"use client";

/**
 * The message editor (LP-849) — a rich box, not a notepad.
 *
 * Reported: "We need reach textarea component for message, not like old scholl ***bold***. The
 * message field looks like simple notepad version. Think like how message box in gmail." And:
 * "user should not see html tag or markdown."
 *
 * This reverses LP-844's markdown-in-a-textarea, with the benefit of a processor having used it.
 *
 * LP-853 — IT EMITS HTML NOW, AND THE STORED BODY FOLLOWS.
 *
 * LP-849 kept the stored body as one plain string and had this component convert in and out. That
 * was right for the schema it shipped — paragraphs, bullets, bold — and was chosen precisely so the
 * editor could not produce something the converter silently drops. Underline, links, ordered lists,
 * indent and block quotes cannot round-trip through that string, so LP-854's toolbar is a storage
 * request whether or not it was meant as one.
 *
 * SO THE CONVERSION MOVED TO THE EDGE RATHER THAN DISAPPEARING:
 *
 *   • a `plain` body — every generated draft — is converted ON LOAD by `emailBodyToHtml`, which is
 *     still the single renderer for that path;
 *   • an `html` body is what a processor already wrote, and is loaded as-is;
 *   • what comes OUT is always HTML, which is what the save stores and what the clipboard carries.
 *
 * `htmlToEmailBody` is not gone and is not dead: it derives the plain text `mailto:` and LP-855's
 * compose routes need, which is the one thing that must never be stored twice. Its round trip is
 * still tested as a FIXED POINT in `round-trip.test.ts`, because the `plain` path still runs
 * through both halves on every load.
 *
 * THE SCHEMA IS THE SUBSET THE RENDERER AND THE SANITISER SUPPORT. Paragraphs, bullets, bold —
 * nothing else is enabled, and `app/communications/sanitise.py`'s `ALLOWED` names the same tags. An
 * editor that could produce a heading would produce one the server strips, and a processor would
 * watch their formatting vanish on save. LP-854 extends all three together.
 */

import { Button } from "@/components/ui/button";
import { emailBodyToHtml } from "@/lib/markdown/email-body";
import { ALLOWED_SCHEMES } from "@/lib/markdown/schema";
import { cn } from "@/lib/utils";
import Blockquote from "@tiptap/extension-blockquote";
import Bold from "@tiptap/extension-bold";
import BulletList from "@tiptap/extension-bullet-list";
import Document from "@tiptap/extension-document";
import HardBreak from "@tiptap/extension-hard-break";
import Italic from "@tiptap/extension-italic";
import Link from "@tiptap/extension-link";
import ListItem from "@tiptap/extension-list-item";
import OrderedList from "@tiptap/extension-ordered-list";
import Paragraph from "@tiptap/extension-paragraph";
import Text from "@tiptap/extension-text";
import Underline from "@tiptap/extension-underline";
import { UndoRedo } from "@tiptap/extensions";
import { type Editor, EditorContent, useEditor } from "@tiptap/react";
import {
  Bold as BoldIcon,
  Indent,
  Italic as ItalicIcon,
  Link as LinkIcon,
  List,
  ListOrdered,
  Outdent,
  Quote,
  Redo2,
  RemoveFormatting,
  Underline as UnderlineIcon,
  Undo2,
} from "lucide-react";

/**
 * Exported so a test can drive the REAL schema rather than a copy of it (LP-849 review). Tiptap
 * parses the rendered HTML and re-serialises it, which is a third escape/unescape path beside
 * `escapeHtml` and its inverse — and the only way to check it is to run it.
 */
export const EXTENSIONS = [
  // Structural — these emit no tag of their own.
  Document,
  Text,
  // LP-854 — UNDO AND REDO. Table stakes anywhere people type paragraphs, and the one thing on
  // Gmail's bar a processor will reach for without looking.
  UndoRedo,

  // Everything below emits exactly one tag from `EMAIL_SCHEMA`, and `schema-drift.test.ts` fails
  // if this list and that one stop agreeing.
  Paragraph, // p
  HardBreak, // br — a single newline inside a paragraph; the identification block is two lines, one
  Bold, // strong
  Italic, // em — NEW, despite LP-854's table saying we had it. We did not.
  Underline, // u
  BulletList, // ul
  OrderedList, // ol
  ListItem, // li
  Blockquote, // blockquote
  Link.configure({
    // LP-854 — THE SCHEME LIST, ENFORCED HERE AND ON THE SERVER. The editor is not a security
    // boundary: a request built by hand never comes through it. This is the half that stops a
    // processor pasting something dangerous by accident; `sanitise.py` is the half that holds.
    protocols: [...ALLOWED_SCHEMES],
    // NO `target`, NO `rel`, NO CLASS. Outlook on the desktop renders with Word's engine and
    // discards most of what it does not recognise, and this output is pasted into a mail client
    // rather than rendered by us. An `<a href>` is the whole element.
    //
    // `target` AND `rel` ARE NULLED HERE, IN `HTMLAttributes`, AND THAT IS THE ONLY PLACE THEY CAN
    // BE. Measured: a bare `HTMLAttributes: {}` emits
    // `<a target="_blank" rel="noopener noreferrer nofollow" href="…">` — Tiptap's Link applies
    // those defaults when it renders the attributes. There are no `target`/`rel` OPTIONS to set
    // instead; `tsc` refuses them, which is the second confirmation.
    //
    // Two attributes the server's allowlist strips. Harmless in themselves, and exactly the drift
    // this ticket exists to prevent: the editor producing something the sanitiser does not keep IS
    // the shape of "formatting vanished on save". Caught by `emits no class and no inline style`.
    HTMLAttributes: { target: null, rel: null },
    // A link whose text is a DIFFERENT url is the classic deception, and it is left alone rather
    // than cleverly rewritten: a processor who typed it meant it, and rewriting somebody's words is
    // not this editor's job. What is refused is the scheme, above.
    autolink: false,
    openOnClick: false,
  }), // a
];

export function MessageEditor({
  value,
  format = "plain",
  onChange,
  label = "Message",
}: {
  /**
   * The stored body. Plain text when `format` is `"plain"`, the processor's own HTML when it is
   * `"html"`.
   *
   * READ ONCE, AT MOUNT. Tiptap owns the document from then on, and re-seeding from a prop would
   * throw away an edit mid-sentence every time the draft's row changed underneath — the same reason
   * `message-dialog` keys its own seeding on message identity rather than on the body.
   */
  value: string;
  format?: "plain" | "html";
  /** Called with HTML, always — see the file header. */
  onChange: (html: string) => void;
  label?: string;
}) {
  const editor = useEditor({
    extensions: EXTENSIONS,
    // LP-853 — CONVERTED ONLY ON THE PLAIN PATH. An `html` body is what a person already wrote and
    // has already been through the server's allowlist; running it through `emailBodyToHtml` would
    // escape their own tags into view.
    content: format === "html" ? value : emailBodyToHtml(value),
    // Next renders this on the server first, and Tiptap warns that its DOM-dependent parse can
    // mismatch. The editor is a client interaction with nothing to show a crawler.
    immediatelyRender: false,
    editorProps: {
      attributes: {
        class: cn(
          "min-h-[16rem] rounded-b-md border border-t-0 border-input bg-background px-3 py-2",
          "text-sm text-foreground focus:outline-none",
          "[&_p]:mb-3 [&_p:last-child]:mb-0 [&_ul]:mb-3 [&_ul]:ml-5 [&_ul]:list-disc [&_li]:mb-1.5",
          "[&_strong]:font-semibold [&_em]:italic [&_u]:underline",
          // LP-854 — THE NEW BLOCKS, styled for the EDITOR only. `emailBodyToHtml` emits no classes
          // and an authored body carries none either: a mail client keeps the semantic tags and
          // discards our stylesheet, which is why the output survives Word's engine at all.
          "[&_ol]:mb-3 [&_ol]:ml-5 [&_ol]:list-decimal",
          "[&_blockquote]:my-3 [&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-3 [&_blockquote]:text-foreground-2",
          "[&_a]:underline [&_a]:underline-offset-2",
        ),
        "aria-label": label,
        // EXPLICIT, because `contenteditable` alone does not give every environment a textbox in
        // the accessibility tree — jsdom does not, and neither do some screen readers on a plain
        // editable div. The dialog's own tests find the message field by role, which is how a
        // processor using a screen reader finds it too.
        role: "textbox",
        "aria-multiline": "true",
      },
    },
    onUpdate: ({ editor: instance }) => {
      // HTML ON EVERY KEYSTROKE, so the value a caller holds is always the thing that will be
      // stored and copied. Converting only on save would let the editor and the record disagree for
      // the whole time a processor is typing, which is exactly when they look at it.
      onChange(instance.getHTML());
    },
  });

  if (!editor) return null;

  return (
    <div className="flex flex-col">
      {/* SCREEN 2's BAR: `↶ ↷ | B I U | bullets ordered outdent indent | quote link | clear`.
          One row, wrapping at narrow widths, sunk background, rounded at the top only.

          THREE OF GMAIL'S CONTROLS ARE DECLINED, and the reasons are here rather than in somebody's
          memory. Font family: a document request in Comic Sans is a real outcome, and the font does
          not survive `mailto:` or a paste into a themed client anyway. Text colour and highlight:
          COLOUR MEANS STATUS IN THE LEDGER, so a sentence coloured red inside a compliance record is
          a claim nobody intended, and it is the one addition that could contradict a status glyph
          two inches away. Alignment: centred body text in a letter is a formatting accident, and
          keeping the button out is cheaper than repairing the output. */}
      <div className="flex flex-wrap items-center gap-1 rounded-t-md border border-input bg-muted px-2 py-1">
        <ToolbarButton
          active={false}
          disabled={!editor.can().undo()}
          onClick={() => editor.chain().focus().undo().run()}
          title="Undo"
        >
          <Undo2 className="h-3.5 w-3.5" />
        </ToolbarButton>
        <ToolbarButton
          active={false}
          disabled={!editor.can().redo()}
          onClick={() => editor.chain().focus().redo().run()}
          title="Redo"
        >
          <Redo2 className="h-3.5 w-3.5" />
        </ToolbarButton>

        <Divider />

        <ToolbarButton
          active={editor.isActive("bold")}
          onClick={() => editor.chain().focus().toggleBold().run()}
          title="Bold"
        >
          <BoldIcon className="h-3.5 w-3.5" />
        </ToolbarButton>
        <ToolbarButton
          active={editor.isActive("italic")}
          onClick={() => editor.chain().focus().toggleItalic().run()}
          title="Italic"
        >
          <ItalicIcon className="h-3.5 w-3.5" />
        </ToolbarButton>
        <ToolbarButton
          active={editor.isActive("underline")}
          onClick={() => editor.chain().focus().toggleUnderline().run()}
          title="Underline"
        >
          <UnderlineIcon className="h-3.5 w-3.5" />
        </ToolbarButton>

        <Divider />

        <ToolbarButton
          active={editor.isActive("bulletList")}
          onClick={() => editor.chain().focus().toggleBulletList().run()}
          title="Bulleted list"
        >
          <List className="h-3.5 w-3.5" />
        </ToolbarButton>
        <ToolbarButton
          active={editor.isActive("orderedList")}
          onClick={() => editor.chain().focus().toggleOrderedList().run()}
          title="Numbered list"
        >
          <ListOrdered className="h-3.5 w-3.5" />
        </ToolbarButton>
        {/* INDENT IS LIST NESTING, which is how LP-846's detail block is built — the structure is
            already in the output and this gives it a button. It is also the only indentation that
            survives a paste, because it comes from a tag rather than from a margin. */}
        <ToolbarButton
          active={false}
          disabled={!editor.can().liftListItem("listItem")}
          onClick={() => editor.chain().focus().liftListItem("listItem").run()}
          title="Outdent"
        >
          <Outdent className="h-3.5 w-3.5" />
        </ToolbarButton>
        <ToolbarButton
          active={false}
          disabled={!editor.can().sinkListItem("listItem")}
          onClick={() => editor.chain().focus().sinkListItem("listItem").run()}
          title="Indent"
        >
          <Indent className="h-3.5 w-3.5" />
        </ToolbarButton>

        <Divider />

        <ToolbarButton
          active={editor.isActive("blockquote")}
          onClick={() => editor.chain().focus().toggleBlockquote().run()}
          title="Quote"
        >
          <Quote className="h-3.5 w-3.5" />
        </ToolbarButton>
        <ToolbarButton
          active={editor.isActive("link")}
          onClick={() => promptForLink(editor)}
          title="Link"
        >
          <LinkIcon className="h-3.5 w-3.5" />
        </ToolbarButton>

        <Divider />

        {/* THE REPAIR TOOL FOR EVERYTHING PASTED IN FROM ELSEWHERE. Without it a bad paste is
            unfixable and the processor retypes the message. `unsetAllMarks` takes the inline marks
            and `clearNodes` takes the blocks, because a pasted quote or list is a NODE and would
            survive the first alone. */}
        <ToolbarButton
          active={false}
          onClick={() => editor.chain().focus().unsetAllMarks().clearNodes().run()}
          title="Remove formatting"
        >
          <RemoveFormatting className="h-3.5 w-3.5" />
        </ToolbarButton>
      </div>
      <EditorContent editor={editor} />
    </div>
  );
}

/** A hairline between groups of controls — the Ledger's rule 1, at toolbar scale. */
function Divider() {
  return <span aria-hidden className="mx-0.5 h-4 w-px shrink-0 bg-border" />;
}

/**
 * Ask for a link's address, and refuse a scheme the allowlist does not carry.
 *
 * `window.prompt` RATHER THAN A POPOVER, and it is a deliberate floor rather than a shortcut:
 * Screen 2 specifies a toolbar button and says nothing about the shape of the asking, and a custom
 * popover is a second focus trap inside a dialog — which is the kind of thing LP-UI-008's review
 * found announcing itself wrongly to a screen reader. When somebody designs one, this is the
 * function it replaces.
 *
 * THE REFUSAL IS HERE AND ON THE SERVER. `Link.configure({ protocols })` already refuses at the
 * schema level; this says so out loud, because a control that silently does nothing reads as broken
 * rather than as refusing.
 */
function promptForLink(editor: Editor): void {
  if (editor.isActive("link")) {
    editor.chain().focus().unsetLink().run();
    return;
  }
  const typed = window.prompt("Link address")?.trim();
  if (!typed) return;
  if (!isSafeHref(typed)) {
    window.alert(
      `A link can only go to ${ALLOWED_SCHEMES.join(", ")} — that address was not added.`,
    );
    return;
  }
  editor.chain().focus().setLink({ href: typed }).run();
}

/**
 * Whether this address may be linked to.
 *
 * NORMALISED BEFORE IT IS READ, matching `href_is_safe` in `sanitise.py`: a scheme can carry
 * leading whitespace, a NUL or mixed case and still be honoured — `java\tscript:` and
 * `JaVaScRiPt:` both run in a browser — so the comparison is against what a client would resolve
 * rather than against what the string looks like.
 */
export function isSafeHref(value: string): boolean {
  // EXACTLY WHAT A BROWSER STRIPS, AND NOTHING MORE — the same rule as `href_is_safe` in
  // `sanitise.py`, because two rules that merely agree on the cases somebody tried are two rules.
  //
  // THIS OVER-STRIPPED, AND IN THE DIRECTION THAT MATTERS. It removed every character below 0x21
  // and DEL from ANYWHERE in the string, which is wider than WHATWG's rule: `htt\x0bp://x.com`
  // cleaned to `http` and was called safe, while the server — correctly — refused it. Measured
  // across a shared corpus: four hrefs where the editor said yes and the sanitiser said no, so the
  // editor would accept a link the server then strips. A link vanishing on save is the precise
  // failure LP-854 exists to prevent, arrived at from the security check rather than the schema.
  //
  // WHATWG's URL parser strips leading and trailing C0 controls and space, and removes tab, CR and
  // LF anywhere. That is the whole list, and it is what makes `java<TAB>script:` run.
  // Written by code point rather than as a regex literal: Biome forbids control characters in one,
  // reasonably, and this is one of the few places they are the subject rather than a mistake.
  const isC0OrSpace = (character: string) => (character.codePointAt(0) ?? 0) <= 0x20;
  const characters = [...value];
  let start = 0;
  let end = characters.length;
  while (start < end && isC0OrSpace(characters[start] ?? "")) start += 1;
  while (end > start && isC0OrSpace(characters[end - 1] ?? "")) end -= 1;
  const cleaned = characters
    .slice(start, end)
    .filter((character) => character !== "\t" && character !== "\n" && character !== "\r")
    .join("")
    .toLowerCase();
  if (!cleaned.includes(":")) return false;
  return ALLOWED_SCHEMES.includes(cleaned.split(":", 1)[0] ?? "");
}

function ToolbarButton({
  active,
  disabled = false,
  onClick,
  title,
  children,
}: {
  active: boolean;
  /** Undo with no history, or indent with nothing to indent. Offering it would be a lie. */
  disabled?: boolean;
  onClick: () => void;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      // `aria-pressed` rather than a colour alone: whether bold is ON is state, and a processor
      // using a screen reader needs it said rather than shown.
      aria-pressed={active}
      aria-label={title}
      title={title}
      disabled={disabled}
      className={cn("h-7 px-2", active && "bg-background text-foreground")}
      onClick={onClick}
    >
      {children}
    </Button>
  );
}
