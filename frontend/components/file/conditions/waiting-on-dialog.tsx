"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { OWNER_LABEL } from "@/lib/conditions/owners";
import type { Condition, OwnerHint } from "@/lib/types/conditions";
import { useEffect, useState } from "react";

/**
 * LP-956 — who a condition waits on, when its owner cannot be: the processor.
 *
 * The staging trial's 0006 sat at "Waiting on Processor": a move to Waiting sends the condition's owner,
 * and its owner (from UWM's code map) was the processor herself. The processor stays a valid OWNER (her
 * task); she is never someone she waits on, and the server refuses it (`waiting_on_self`). So this asks,
 * offering every owner but her.
 */
export const WAITING_ON_CHOICES: OwnerHint[] = (Object.keys(OWNER_LABEL) as OwnerHint[]).filter(
  (owner) => owner !== "processor",
);

/** The owner a move to Waiting sends, or null when it must ask (the owner is the processor). */
export function waitingOnFor(condition: Condition): OwnerHint | null {
  return condition.effective_owner === "processor" ? null : condition.effective_owner;
}

export function WaitingOnDialog({
  condition,
  open,
  onOpenChange,
  onChoose,
  refusal,
  pending,
}: {
  condition: Condition | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onChoose: (owner: OwnerHint) => void;
  refusal: string | null;
  pending: boolean;
}) {
  const [owner, setOwner] = useState<OwnerHint | "">("");
  useEffect(() => {
    if (open) setOwner("");
  }, [open]);
  const code = condition?.lender_code ?? "this condition";
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Who is {code} waiting on?</DialogTitle>
          <p className="text-xs text-muted-foreground">
            It is your task, so it can't wait on you. Choose who has it now.
          </p>
        </DialogHeader>
        <select
          aria-label="Waiting on"
          value={owner}
          onChange={(event) => setOwner(event.target.value as OwnerHint)}
          className="h-9 rounded-md border border-input bg-background px-2 text-sm"
        >
          <option value="">Choose…</option>
          {WAITING_ON_CHOICES.map((choice) => (
            <option key={choice} value={choice}>
              {OWNER_LABEL[choice]}
            </option>
          ))}
        </select>
        {refusal ? <p className="text-xs text-destructive">{refusal}</p> : null}
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={!owner || pending} onClick={() => owner && onChoose(owner)}>
            Move to Waiting
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
