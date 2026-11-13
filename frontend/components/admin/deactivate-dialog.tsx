"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/**
 * Confirm a deactivation (LP-MB-Admin-03, mockup 06 without its file section).
 *
 * The file section (move this person's files to someone else) arrives with teams in LP-MB-Admin-05;
 * until then the dialog is the paragraph and two buttons. The mockup's copy says "he"; this says
 * "they", because the dialog does not know anyone's pronouns.
 */
export function DeactivateDialog({
  name,
  open,
  pending,
  onOpenChange,
  onConfirm,
}: {
  name: string;
  open: boolean;
  pending: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Deactivate {name}?</DialogTitle>
          <DialogDescription>
            They are signed out on their next click and cannot sign in again. Everything they did
            stays in each file&rsquo;s history under their name. You can reactivate them later from
            their row.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="button" variant="destructive" disabled={pending} onClick={onConfirm}>
            {pending ? "Deactivating…" : "Deactivate"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
