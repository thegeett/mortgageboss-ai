"use client";

import { Button } from "@/components/ui/button";
import {
  useRestoreCondition,
  useWithdrawCondition,
  useWithdrawnConditions,
} from "@/lib/api/conditions";
import { getErrorMessage } from "@/lib/errors/api-error";
import type { Condition } from "@/lib/types/conditions";
import { cn } from "@/lib/utils";
import { ChevronRight, Undo2, XCircle } from "lucide-react";
import { useState } from "react";

/**
 * LP-940 — "Withdraw" on a condition SHE ADDED BY HAND, entered in error (ADR-404 as amended).
 *
 * Only offered for `origin = manual`: a condition from the lender's sheet stays until the lender clears
 * or waives it. The server also refuses one the lender answered on, or one sent in a submitted package,
 * and its sentence is shown as it is. Nothing is deleted: the condition moves to the list's collapsed
 * "Withdrawn (n)" section, with Undo.
 */
export function WithdrawControl({ fileId, condition }: { fileId: string; condition: Condition }) {
  const withdraw = useWithdrawCondition(fileId);
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState<string | null>(null);
  if (condition.origin !== "manual") return null;

  if (!asking) {
    return (
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>You added this condition by hand.</span>
        <Button type="button" variant="ghost" size="sm" onClick={() => setAsking(true)}>
          <XCircle className="h-3.5 w-3.5" aria-hidden />
          Withdraw…
        </Button>
      </div>
    );
  }
  return (
    <form
      className="flex flex-col gap-2 rounded-lg border border-input bg-muted/40 p-3 text-sm"
      onSubmit={(event) => {
        event.preventDefault();
        setNote(null);
        withdraw.mutate(
          { conditionId: condition.id, reason: reason.trim() },
          { onError: (error) => setNote(getErrorMessage(error)) },
        );
      }}
    >
      <p className="text-foreground">
        Withdraw {condition.lender_code ?? "this condition"} as entered in error. It leaves the
        list, the counts, the plan, the drafts and the package; nothing is deleted, and you can undo
        it.
      </p>
      <input
        aria-label="Why you are withdrawing it"
        value={reason}
        maxLength={500}
        onChange={(event) => setReason(event.target.value)}
        placeholder="Why — for example, added twice by mistake"
        className="h-8 min-w-0 rounded-md border border-input bg-background px-2 text-sm"
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" size="sm" disabled={!reason.trim() || withdraw.isPending}>
          Withdraw
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={() => setAsking(false)}>
          Keep it
        </Button>
      </div>
      {note ? <p className="text-xs text-destructive">{note}</p> : null}
    </form>
  );
}

/** The list's collapsed "Withdrawn (n) · codes" section, each row with its reason and Undo. */
export function WithdrawnSection({ fileId }: { fileId: string }) {
  const { data } = useWithdrawnConditions(fileId);
  const restore = useRestoreCondition(fileId);
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  if (!data || data.length === 0) return null;
  return (
    <div className="overflow-hidden rounded-lg border border-input bg-card">
      <button
        type="button"
        onClick={() => setOpen((was) => !was)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary"
      >
        <ChevronRight
          className={cn(
            "h-3.5 w-3.5 text-muted-foreground transition-transform",
            open && "rotate-90",
          )}
          aria-hidden
        />
        <span className="text-sm font-semibold text-foreground">Withdrawn</span>
        <span className="text-xs text-muted-foreground">
          {data.length} · {data.map((row) => row.lender_code ?? "—").join(", ")}
        </span>
        <span className="ml-auto text-xs text-muted-foreground">
          Added by hand in error — kept for the record
        </span>
      </button>
      {open
        ? data.map((row) => (
            <div
              key={row.id}
              className="grid grid-cols-[3.5rem_minmax(0,1fr)_auto] items-start gap-3 border-t border-input px-3 py-2"
            >
              <span className="font-mono text-xs font-medium text-foreground-2">
                {row.lender_code ?? "—"}
              </span>
              <span className="min-w-0">
                <span className="line-clamp-1 font-serif text-sm text-foreground-2">
                  {row.verbatim_text}
                </span>
                <span className="text-xs text-muted-foreground">
                  Withdrawn {shortDate(row.withdrawn_at)} — {row.reason}
                </span>
              </span>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={restore.isPending}
                onClick={() =>
                  restore.mutate(
                    { conditionId: row.id },
                    { onError: (error) => setNote(getErrorMessage(error)) },
                  )
                }
              >
                <Undo2 className="h-3 w-3" aria-hidden />
                Undo
              </Button>
            </div>
          ))
        : null}
      {note ? (
        <p className="border-t border-input px-3 py-2 text-xs text-destructive">{note}</p>
      ) : null}
    </div>
  );
}

function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "2-digit",
    day: "2-digit",
    timeZone: "America/New_York",
  });
}
