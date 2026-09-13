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
import { cn } from "@/lib/utils";
import Bold from "@tiptap/extension-bold";
import BulletList from "@tiptap/extension-bullet-list";
import Document from "@tiptap/extension-document";
import HardBreak from "@tiptap/extension-hard-break";
import ListItem from "@tiptap/extension-list-item";
import Paragraph from "@tiptap/extension-paragraph";
import Text from "@tiptap/extension-text";
import { EditorContent, useEditor } from "@tiptap/react";
import { Bold as BoldIcon, List } from "lucide-react";

/**
 * Exported so a test can drive the REAL schema rather than a copy of it (LP-849 review). Tiptap
 * parses the rendered HTML and re-serialises it, which is a third escape/unescape path beside
 * `escapeHtml` and its inverse — and the only way to check it is to run it.
 */
export const EXTENSIONS = [
  Document,
  Paragraph,
  Text,
  Bold,
  BulletList,
  ListItem,
  // A single newline inside a paragraph — the identification block is two lines, one paragraph.
  HardBreak,
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
          "[&_strong]:font-semibold",
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
      <div className="flex items-center gap-1 rounded-t-md border border-input bg-muted px-2 py-1">
        <ToolbarButton
          active={editor.isActive("bold")}
          onClick={() => editor.chain().focus().toggleBold().run()}
          title="Bold"
        >
          <BoldIcon className="h-3.5 w-3.5" />
        </ToolbarButton>
        <ToolbarButton
          active={editor.isActive("bulletList")}
          onClick={() => editor.chain().focus().toggleBulletList().run()}
          title="Bulleted list"
        >
          <List className="h-3.5 w-3.5" />
        </ToolbarButton>
      </div>
      <EditorContent editor={editor} />
    </div>
  );
}

function ToolbarButton({
  active,
  onClick,
  title,
  children,
}: {
  active: boolean;
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
      className={cn("h-7 px-2", active && "bg-background text-foreground")}
      onClick={onClick}
    >
      {children}
    </Button>
  );
}
