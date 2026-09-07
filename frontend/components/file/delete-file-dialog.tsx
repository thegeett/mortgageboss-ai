"use client";

/**
 * Delete-loan-file confirmation (LP-79.5, rewritten to the mockup in LP-UI-035).
 *
 * TWO THINGS MAKE A DESTRUCTIVE CONFIRMATION WORTH SHOWING, and a dialog with
 * neither is a speed bump that teaches people to click through:
 *
 *   1. It NAMES WHAT GOES WITH IT. "Twelve documents" is what makes a processor
 *      stop; "this file and its data" is what they have already agreed to by
 *      clicking Delete. The document count is fetched while the dialog is open —
 *      one request, on a deliberate and rare action.
 *   2. It ASKS THEM TO TYPE THE ID. A muscle-memory click cannot produce
 *      "LF-AWBB", which is exactly the accident this is guarding against.
 *
 * The delete is a **soft delete**: the backend sets `deleted_at`, so the file
 * leaves the dashboard but is preserved and recoverable by an admin. That is said
 * on the dialog, because a confirmation that hides how reversible it is makes the
 * decision harder than it needs to be.
 */

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { useLoanFileDocuments } from "@/lib/api/documents";
import { useDeleteLoanFile } from "@/lib/api/loan-files";
import { getErrorMessage } from "@/lib/errors/api-error";
import { currentDocuments } from "@/lib/loan-files/documents";
import { notifyError, notifySuccess } from "@/lib/toast";
import { Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

/** The minimal file shape the dialog needs to name what's affected. */
export interface DeletableFile {
  id: string;
  display_id: string;
  primary_borrower_name: string | null;
  /** Shown beside the borrower so the dialog names the right file, not just an id. */
  property_address?: string | null;
}

export function DeleteFileDialog({
  file,
  open,
  onOpenChange,
  onDeleted,
}: {
  file: DeletableFile | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called after a successful delete (e.g. redirect away from the file's page). */
  onDeleted?: () => void;
}) {
  const del = useDeleteLoanFile();
  // The human-readable name; falls back to the display id when the borrower is unknown.
  const who = file?.primary_borrower_name?.trim() || "this file";

  // The typed confirmation. Compared case-insensitively and trimmed: the point is
  // to defeat a muscle-memory click, not to test typing accuracy, and a processor
  // who types the id in lower case has demonstrated everything this asks for.
  const [typed, setTyped] = useState("");
  const confirmed = Boolean(file) && typed.trim().toUpperCase() === file?.display_id.toUpperCase();

  // Only while the dialog is open — the count is worth one request on a
  // deliberate, rare, destructive action, and worth none the rest of the time.
  const { data: documents } = useLoanFileDocuments(file?.id ?? "", { enabled: open && !!file });
  const documentCount = documents ? currentDocuments(documents).length : null;

  // Reset between openings: a half-typed id left over from a cancelled delete
  // would carry into the next file's dialog, which is the one place a stale
  // value could pre-arm a destructive button.
  useEffect(() => {
    if (!open) setTyped("");
  }, [open]);

  function confirmDelete() {
    if (!file) return;
    del.mutate(file.id, {
      onSuccess: () => {
        notifySuccess({
          title: `${file.display_id} deleted`,
          consequence: "It has left your dashboard. An administrator can restore it.",
        });
        onOpenChange(false);
        onDeleted?.();
      },
      onError: (error) =>
        notifyError({
          title: `${file.display_id} wasn’t deleted`,
          whatToDo: getErrorMessage(error),
        }),
    });
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !del.isPending && onOpenChange(next)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-md bg-destructive/10 text-destructive">
              <Trash2 className="h-4 w-4" />
            </span>
            {/* The ID in the title, as the mockup has it: the dialog is about
                ONE file, and a processor with two tabs open needs to see which
                without reading the body. */}
            {file ? `Delete ${file.display_id}?` : "Delete this loan file?"}
          </DialogTitle>
          <DialogDescription className="pt-1 text-sm leading-relaxed">
            <span className="font-medium text-foreground">{who}</span>
            {file?.property_address ? ` · ${file.property_address}` : ""}.{" "}
            {/* NAMES WHAT GOES WITH IT. "Twelve documents" is what makes a
                processor stop; "its data" is what they already agreed to by
                clicking Delete. The count is omitted rather than guessed while it
                loads — a wrong number here is worse than none. */}
            {documentCount === null
              ? "Its documents, extracted data and findings"
              : `${documentCount} ${documentCount === 1 ? "document" : "documents"}, its extracted data and findings`}{" "}
            go with it, along with the whole activity trail. The file is preserved — an
            administrator can restore it.
          </DialogDescription>
        </DialogHeader>
        {file ? (
          <div className="space-y-1.5">
            <Label htmlFor="delete-confirm" className="text-xs text-muted-foreground">
              Type <span className="font-mono text-foreground">{file.display_id}</span> to confirm
            </Label>
            <Input
              id="delete-confirm"
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              placeholder={file.display_id}
              autoComplete="off"
              spellCheck={false}
              className="font-mono"
            />
          </div>
        ) : null}

        <DialogFooter className="gap-2 sm:gap-2">
          <Button
            type="button"
            variant="ghost"
            disabled={del.isPending}
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            className="gap-1.5"
            disabled={del.isPending || !file || !confirmed}
            onClick={confirmDelete}
          >
            {del.isPending ? (
              <Spinner className="h-3.5 w-3.5" />
            ) : (
              <Trash2 className="h-3.5 w-3.5" />
            )}
            {del.isPending ? "Deleting…" : "Delete file"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
