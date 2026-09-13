"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/**
 * "Delete this draft?" — LP-858 §7.
 *
 * IT ONLY APPEARS WHEN THERE IS SOMETHING TO LOSE. An unedited draft is template output: deleting
 * it destroys nothing a person wrote, and a confirm on every delete is the dialog people learn to
 * dismiss without reading — which is what makes the one that matters useless too. So this opens on
 * `body_edited` and on nothing else.
 *
 * AND IT QUOTES THEM BACK TO THEMSELVES, the same pattern LP-851 uses for the append warning. "You
 * have unsaved changes" is a sentence about a category; the processor's own first edited line is
 * the thing they can actually recognise, and recognising it is the whole decision. Rendered as
 * TEXT, never as markup — it is a fragment of a body that may legitimately contain tags.
 */
export function DeleteDraftDialog({
  open,
  firstEditedLine,
  pending = false,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  /** The processor's own words, plain. Empty when the body has no readable line. */
  firstEditedLine: string;
  pending?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onCancel()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-base">Delete this draft?</DialogTitle>
          <DialogDescription className="text-xs">
            You edited it. Your first change was:
          </DialogDescription>
        </DialogHeader>

        {/* THE QUOTE. Serif italic is the Ledger's mark for verbatim quotation of a document, and
            this is the closest thing on this screen: words we are repeating back rather than
            words we wrote. Truncated by CSS rather than by slicing, so a long line is shortened on
            screen and never in the comparison. */}
        <blockquote className="border-l-2 border-border pl-3 font-serif text-sm italic text-foreground">
          {firstEditedLine || "…"}
        </blockquote>

        <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-3">
          <Button variant="ghost" disabled={pending} onClick={onCancel}>
            Keep it
          </Button>
          {/* DANGER TEXT ON A QUIET BUTTON, per §4's row: the destructive action is reachable and
              never the loudest thing on screen. */}
          <Button
            variant="ghost"
            className="text-danger hover:bg-danger/5 hover:text-danger"
            disabled={pending}
            onClick={onConfirm}
          >
            {pending ? "Deleting…" : "Delete"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
