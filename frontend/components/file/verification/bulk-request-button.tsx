"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useState } from "react";

/**
 * "Request all", with a look at what that means first (LP-839).
 *
 * THE ONLY ACTION ON THIS TAB WHOSE BLAST RADIUS IS INVISIBLE. It requests every document across a
 * group of findings in one click. The button carried the count; the list was nowhere, and the only
 * thing that followed was a toast — by which point every request had been made.
 *
 * NAMES THE DOCUMENTS AND WHERE THEY GO. LP-832 makes each request create a new draft carrying
 * everything outstanding, so "the draft" is ambiguous and "the latest" is the true phrase.
 */
export function BulkRequestButton({
  documents,
  onConfirm,
}: {
  documents: string[];
  onConfirm: () => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <Button
        size="sm"
        className="px-2 text-[11px]"
        title="This will be added to the latest communication draft."
        onClick={() => setOpen(true)}
      >
        Request all {documents.length}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-base">
              Request {documents.length} document{documents.length === 1 ? "" : "s"}?
            </DialogTitle>
            <DialogDescription className="text-xs">
              These are added to this file&apos;s needs list, and whatever the borrower can send
              joins the latest communication draft.
            </DialogDescription>
          </DialogHeader>

          <ul className="max-h-60 list-inside list-disc overflow-y-auto text-sm text-foreground-2">
            {documents.map((document) => (
              <li key={document}>{document}</li>
            ))}
          </ul>

          <div className="flex justify-end gap-2 border-t border-border pt-3">
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                setOpen(false);
                onConfirm();
              }}
            >
              Looks good
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
