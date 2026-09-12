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
 * THE STORED BODY IS STILL ONE PLAIN STRING. That is what the templates emit, what
 * `finalise_draft_body` resolves placeholders in, what `mailto:` can carry, and what the send record
 * means when it says "this is what went out". Storing HTML would cost every template a new ADR-401
 * version and the placeholder pass would run over markup — to buy nothing a processor can see, since
 * every requirement here is about what they LOOK at.
 *
 * So the component converts on the way in and on the way out, and the round trip is tested as a
 * FIXED POINT in `round-trip.test.ts`: a lossy inverse eats formatting gradually, surviving one
 * reopen and degrading on the fourth.
 *
 * THE SCHEMA IS THE SUBSET THE RENDERER SUPPORTS. Paragraphs, bullets, bold — nothing else is
 * enabled, which is how the editor and `emailBodyToHtml` stay in agreement. An editor that could
 * produce a heading would produce one the renderer silently drops, and a processor would watch their
 * formatting vanish on save.
 */

import { Button } from "@/components/ui/button";
import { emailBodyToHtml } from "@/lib/markdown/email-body";
import { htmlToEmailBody } from "@/lib/markdown/from-html";
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
  onChange,
  label = "Message",
}: {
  /** The stored plain body. */
  value: string;
  /** Called with the new stored plain body, never with HTML. */
  onChange: (body: string) => void;
  label?: string;
}) {
  const editor = useEditor({
    extensions: EXTENSIONS,
    content: emailBodyToHtml(value),
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
      // BACK TO PLAIN TEXT ON EVERY KEYSTROKE, so the value a caller holds is always the thing that
      // will be stored and sent. Converting only on save would let the editor and the record
      // disagree for the whole time a processor is typing, which is exactly when they look at it.
      onChange(htmlToEmailBody(instance.getHTML()));
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
