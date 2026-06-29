"use client";

/**
 * Delete-loan-file confirmation (LP-79.5). A deliberate, named confirmation before a
 * destructive-looking action — never a silent one-click destroy. The delete is a
 * **soft delete**: the backend sets `deleted_at`, so the file (and its documents,
 * extracted data, and findings) leaves the dashboard but is preserved and recoverable
 * by an admin. Confirm fires the DELETE; cancel does nothing.
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
import { Spinner } from "@/components/ui/spinner";
import { useDeleteLoanFile } from "@/lib/api/loan-files";
import { getErrorMessage } from "@/lib/errors/api-error";
import { Trash2 } from "lucide-react";
import { toast } from "sonner";

/** The minimal file shape the dialog needs to name what's affected. */
export interface DeletableFile {
  id: string;
  display_id: string;
  primary_borrower_name: string | null;
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

  function confirmDelete() {
    if (!file) return;
    del.mutate(file.id, {
      onSuccess: () => {
        toast.success("Loan file deleted", {
          description: "It no longer appears in your dashboard. An admin can restore it.",
        });
        onOpenChange(false);
        onDeleted?.();
      },
      onError: (error) => toast.error(getErrorMessage(error)),
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
            Delete this loan file?
          </DialogTitle>
          <DialogDescription className="pt-1 text-sm leading-relaxed">
            This removes <span className="font-medium text-gray-900">{who}</span>
            {file ? <span className="text-gray-500"> ({file.display_id})</span> : null} and all its
            documents, extracted data, and findings from your dashboard. The file is preserved —
            this can be undone by an admin.
          </DialogDescription>
        </DialogHeader>
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
            disabled={del.isPending || !file}
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
