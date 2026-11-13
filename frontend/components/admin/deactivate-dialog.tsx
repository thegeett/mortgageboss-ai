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
import { Select } from "@/components/ui/select";
import { useAssignable } from "@/lib/api/loan-teams";
import { useState } from "react";

/**
 * Confirm a deactivation (LP-MB-Admin-03, mockup 06; the file section is LP-MB-Admin-05).
 *
 * When the person works files, the dialog offers to move them all to someone else first (one
 * `reassign-loans` call, then the deactivation) or to leave them where they are. With no files it is
 * the paragraph and two buttons. The mockup's copy says "he"; this says "they", because the dialog
 * does not know anyone's pronouns.
 */
export function DeactivateDialog({
  personId,
  name,
  fileCount,
  slots,
  open,
  pending,
  onOpenChange,
  onConfirm,
}: {
  personId: string;
  name: string;
  /** Live files this person works (`file_count` on the People row). */
  fileCount: number;
  /** The slots their files need (review finding 2): a candidate must be eligible for every one. */
  slots: ("loan_officer" | "processor" | "assistant")[];
  open: boolean;
  pending: boolean;
  onOpenChange: (open: boolean) => void;
  /** `moveTo`: the person to hand every file to first, or null to leave them. */
  onConfirm: (moveTo: string | null) => void;
}) {
  const [choice, setChoice] = useState<"move" | "leave">("move");
  const [moveTo, setMoveTo] = useState("");
  // Asked only while open (every person's sheet renders this dialog, closed), and only for the
  // slots their files need.
  const needsLo = slots.includes("loan_officer");
  const needsProcessor = slots.includes("processor");
  const officers = useAssignable("loan_officer", { enabled: open && needsLo });
  const processors = useAssignable("processor", { enabled: open && needsProcessor });
  // Eligible for EVERY slot their files need: the server refuses anyone who is not.
  const pools = [needsLo ? officers.data : null, needsProcessor ? processors.data : null].filter(
    (pool) => pool !== null,
  );
  const others = (pools[0] ?? []).filter(
    (person) =>
      person.id !== personId && pools.every((pool) => pool?.some((p) => p.id === person.id)),
  );
  const moving = fileCount > 0 && choice === "move" && moveTo !== "";

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

        {fileCount > 0 ? (
          <fieldset className="space-y-3">
            <legend className="text-label uppercase text-muted-foreground">
              They are on {fileCount} loan {fileCount === 1 ? "file" : "files"}
            </legend>
            <label className="flex items-start gap-3">
              <input
                type="radio"
                name="files"
                className="mt-1 accent-primary"
                checked={choice === "move"}
                onChange={() => setChoice("move")}
              />
              <span className="space-y-2">
                <span className="block text-sm text-foreground">
                  Move their files to someone else
                </span>
                <span className="block text-xs text-muted-foreground">
                  Every file they are on gets the person you pick in their place.
                </span>
                {choice === "move" ? (
                  <Select
                    aria-label="Move their files to"
                    value={moveTo}
                    onChange={(event) => setMoveTo(event.target.value)}
                  >
                    <option value="">Choose a person…</option>
                    {others.map((person) => (
                      <option key={person.id} value={person.id}>
                        {person.name} · {person.file_count} files now,{" "}
                        {person.file_count + fileCount} after
                      </option>
                    ))}
                  </Select>
                ) : null}
              </span>
            </label>
            <label className="flex items-start gap-3">
              <input
                type="radio"
                name="files"
                className="mt-1 accent-primary"
                checked={choice === "leave"}
                onChange={() => setChoice("leave")}
              />
              <span>
                <span className="block text-sm text-foreground">Leave their files as they are</span>
                <span className="block text-xs text-muted-foreground">
                  They stay listed on each team with no access. Reassign file by file later.
                </span>
              </span>
            </label>
          </fieldset>
        ) : null}

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={pending || (fileCount > 0 && choice === "move" && moveTo === "")}
            onClick={() => onConfirm(moving ? moveTo : null)}
          >
            {pending
              ? "Deactivating…"
              : moving
                ? `Deactivate and move ${fileCount} ${fileCount === 1 ? "file" : "files"}`
                : "Deactivate"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
