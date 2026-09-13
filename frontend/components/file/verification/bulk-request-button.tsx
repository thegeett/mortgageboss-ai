"use client";

import {
  ConflictBlocks,
  isEdited,
  isMultiParty,
} from "@/components/file/communication/open-draft-dialog";
import { useDraftConflict } from "@/components/file/communication/use-draft-conflict";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { ConflictChoice } from "@/lib/api/draft-conflict";
import { useState } from "react";

/**
 * "Request all", with a look at what that means first (LP-839).
 *
 * THE ONLY ACTION ON THIS TAB WHOSE BLAST RADIUS IS INVISIBLE. It requests every document across a
 * group of findings in one click. The button carried the count; the list was nowhere, and the only
 * thing that followed was a toast — by which point every request had been made.
 *
 * LP-851 — AND IT NEVER BECOMES TWO DIALOGS. When a draft is already open the request is refused,
 * and this confirm GAINS the party blocks and the extra button rather than handing off to a second
 * dialog: a processor who has just confirmed five documents and is then asked another question
 * clicks the primary without reading it, which is exactly how the wrong draft gets chosen. One
 * dialog, two states — the title and the document list stay put while the question underneath them
 * changes.
 *
 * UNCHANGED WHEN NOTHING IS OPEN, which is the common case and the one this component was built for.
 */
export function BulkRequestButton({
  documents,
  onConfirm,
}: {
  documents: string[];
  /**
   * Fire the request. Called with no choice first; called again with the processor's answer if the
   * server refuses.
   *
   * THE CALLER KEEPS ITS OWN PAYLOAD. A shape that could carry every door's arguments would be a
   * second definition of "a request" for this button to get wrong.
   */
  onConfirm: (onConflict: ConflictChoice | undefined, onError: (error: unknown) => void) => void;
}) {
  const [open, setOpen] = useState(false);
  const conflict = useDraftConflict();

  function fire(choice?: ConflictChoice) {
    onConfirm(choice, (error) => {
      // Held HERE rather than in a dialog of its own — see the header.
      if (conflict.capture(error, (next) => fire(next))) return;
      // An ordinary failure closes the confirm; the caller's toast says what went wrong.
      setOpen(false);
    });
  }

  const found = conflict.conflict;
  const multiple = found !== null && isMultiParty(found);
  const edited = found !== null && isEdited(found);

  return (
    <>
      <Button
        size="sm"
        className="px-2 text-[11px]"
        title="This will be added to the open communication draft."
        onClick={() => setOpen(true)}
      >
        Request all {documents.length}
      </Button>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!next) {
            conflict.cancel();
            setOpen(false);
          }
        }}
      >
        <DialogContent className={found && multiple ? "sm:max-w-[34rem]" : "sm:max-w-md"}>
          <DialogHeader>
            {/* THE TITLE AND THE LIST DO NOT MOVE when the blocks appear. What a processor
                confirmed is still on screen while they answer the second question, which is the
                difference between one dialog that grew and two that replaced each other. */}
            <DialogTitle className="text-base">
              Request {documents.length} document{documents.length === 1 ? "" : "s"}?
            </DialogTitle>
            <DialogDescription className="text-xs">
              These are added to this file&apos;s needs list, and whatever the borrower can send
              joins the open communication draft.
            </DialogDescription>
          </DialogHeader>

          <ul className="max-h-60 list-inside list-disc overflow-y-auto text-sm text-foreground-2">
            {documents.map((document) => (
              <li key={document}>{document}</li>
            ))}
          </ul>

          {found ? (
            <ConflictBlocks
              conflict={found}
              multiple={multiple}
              pending={conflict.pending}
              onChoose={conflict.choose}
            />
          ) : null}

          <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-3">
            <Button
              variant="outline"
              onClick={() => {
                conflict.cancel();
                setOpen(false);
              }}
            >
              Cancel
            </Button>
            {found ? (
              multiple ? (
                <Button disabled={conflict.pending} onClick={() => conflict.choose("append")}>
                  Do both
                </Button>
              ) : (
                <>
                  <Button
                    variant="outline"
                    disabled={conflict.pending}
                    onClick={() => conflict.choose("mark_sent_and_new")}
                  >
                    Mark sent, start new
                  </Button>
                  <Button disabled={conflict.pending} onClick={() => conflict.choose("append")}>
                    {edited ? "Add anyway" : "Add to the open draft"}
                  </Button>
                </>
              )
            ) : (
              <Button onClick={() => fire()}>Looks good</Button>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
