"use client";

import { StatusToken } from "@/components/status-token";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { CONDITION_LENDER_STATUS, CONDITION_PREP_STATUS, resolveStatus } from "@/lib/status";
import type {
  Condition,
  ConditionLenderStatus,
  ConditionPrepStatus,
  ManualVerdictSourceKind,
} from "@/lib/types/conditions";
import { ArrowRight } from "lucide-react";
import { useEffect, useState } from "react";

/**
 * S2-04 (Record the lender's answer) and S2-05 (Move back / Reopen), which both open FROM the detail
 * sheet and from the list's bulk bar.
 *
 * ONE FILE BECAUSE THEY ARE ONE CONVERSATION. Both ask a processor to say what happened before a
 * status moves, both render the condition's own wording so the answer is about the right line, and
 * both show the server's refusal sentence rather than inventing one. S2-05 serves *two* titles —
 * "Move 0006 back to To do?" and "Reopen 0006?" — because the design says in as many words that it is
 * the same dialog retitled.
 *
 * THE SERVER'S SENTENCE IS SHOWN AS-IS (spec §6 rule 5). Neither dialog composes its own wording for
 * a refusal: the backend's eight refusal codes each carry one plain sentence written for a processor,
 * and a client that paraphrased them would be the third copy of words a test pins byte-for-byte
 * against the tickets file.
 *
 * THE THREE CHOICES ARE THE ONLY ONES A PERSON MAY RECORD. `round_comparison` and `underwriter_note`
 * are produced by the app from a sheet, and the server refuses them from a client (LP-912 review R2:
 * a client could otherwise post `{not_cleared, underwriter_note, <any uuid>}` and paint S2-08's amber
 * "Came back" on a note that never existed). That is why the source field is typed
 * `ManualVerdictSourceKind` here and not `VerdictSourceKind`.
 */

/** The three answers S2-04 offers, with the one-line meanings the design writes beside each. */
const ANSWERS: { status: ConditionLenderStatus; meaning: string }[] = [
  { status: "cleared", meaning: "Lender signed it off" },
  { status: "waived", meaning: "Lender dropped it" },
  { status: "not_cleared", meaning: "Lender says not satisfied" },
];

const WHERE: ManualVerdictSourceKind[] = ["portal", "email", "phone"];

/** A clamped serif line per affected condition, so the answer is visibly about the right rows. */
function AffectedRows({ conditions }: { conditions: Condition[] }) {
  return (
    <ul className="flex flex-col">
      {conditions.map((condition) => (
        <li
          key={condition.id}
          className="flex items-baseline gap-2 border-b border-dashed border-input py-1 last:border-b-0"
        >
          <span className="shrink-0 font-mono text-xs">{condition.lender_code ?? "—"}</span>
          <span className="line-clamp-1 font-serif text-xs text-foreground-2">
            {condition.verbatim_text}
          </span>
        </li>
      ))}
    </ul>
  );
}

export interface VerdictSubmission {
  status: ConditionLenderStatus;
  source_kind: ManualVerdictSourceKind;
  source_date: string;
  note: string | null;
}

/**
 * S2-04 — "Record the lender's answer", for one condition or for a selection.
 *
 * `source_date` HAS NO DEFAULT AND THE FIELD STARTS EMPTY. It is the date the LENDER said it, and the
 * server refuses to assume today — so pre-filling it here would put a date in front of a processor
 * that nobody was told, and the most likely outcome is that it is accepted unread. The submit button
 * stays disabled until it is filled.
 */
export function RecordAnswerDialog({
  conditions,
  open,
  onOpenChange,
  onSubmit,
  refusal,
  pending,
}: {
  conditions: Condition[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (values: VerdictSubmission) => void;
  /** The server's sentence, shown exactly as sent. */
  refusal: string | null;
  pending: boolean;
}) {
  const [status, setStatus] = useState<ConditionLenderStatus>("cleared");
  const [sourceKind, setSourceKind] = useState<ManualVerdictSourceKind>("portal");
  const [sourceDate, setSourceDate] = useState("");
  const [note, setNote] = useState("");

  // Reopening the dialog must not inherit the last answer — a date especially, which would carry a
  // previous lender's date onto a different condition.
  useEffect(() => {
    if (open) {
      setStatus("cleared");
      setSourceKind("portal");
      setSourceDate("");
      setNote("");
    }
  }, [open]);

  const count = conditions.length;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Record the lender’s answer</DialogTitle>
          <p className="text-xs text-muted-foreground">
            For {count} condition{count === 1 ? "" : "s"}. Only record what the lender said — this
            is what “Cleared” will show and where it came from.
          </p>
        </DialogHeader>

        <AffectedRows conditions={conditions} />

        <fieldset className="mt-1">
          <legend className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            The lender’s answer
          </legend>
          <div className="mt-1.5 grid gap-2 sm:grid-cols-3">
            {ANSWERS.map((answer) => {
              const meta = resolveStatus(CONDITION_LENDER_STATUS, answer.status);
              const chosen = status === answer.status;
              return (
                <label
                  key={answer.status}
                  className={`flex cursor-pointer items-start gap-2 rounded-md border p-2 ${
                    chosen
                      ? "border-primary shadow-[inset_0_0_0_1px_hsl(var(--primary)/.2)]"
                      : "border-input"
                  }`}
                >
                  <input
                    type="radio"
                    name="lender-answer"
                    className="mt-1"
                    checked={chosen}
                    onChange={() => setStatus(answer.status)}
                  />
                  <span className="min-w-0">
                    <StatusToken meta={meta} />
                    <span className="mt-0.5 block text-xs text-muted-foreground">
                      {answer.meaning}
                    </span>
                  </span>
                </label>
              );
            })}
          </div>
        </fieldset>

        <div className="grid gap-3 sm:grid-cols-[1.3fr_1fr]">
          <fieldset>
            <legend className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Where the lender said it
            </legend>
            <div className="mt-1.5 inline-flex overflow-hidden rounded-md border border-input">
              {WHERE.map((where) => (
                <button
                  key={where}
                  type="button"
                  onClick={() => setSourceKind(where)}
                  className={`px-3 py-1 text-xs font-medium capitalize ${
                    sourceKind === where
                      ? "bg-primary text-primary-foreground"
                      : "text-foreground-2"
                  }`}
                >
                  {where}
                </button>
              ))}
            </div>
          </fieldset>

          <div className="flex flex-col gap-1">
            <label
              htmlFor="verdict-date"
              className="text-xs font-medium uppercase tracking-wide text-muted-foreground"
            >
              Date the lender said it
            </label>
            <Input
              id="verdict-date"
              type="date"
              required
              value={sourceDate}
              onChange={(event) => setSourceDate(event.target.value)}
            />
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <label
            htmlFor="verdict-note"
            className="text-xs font-medium uppercase tracking-wide text-muted-foreground"
          >
            Note (optional)
          </label>
          <Textarea
            id="verdict-note"
            rows={2}
            placeholder="e.g. “Cleared in EASE, condition status screen”"
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        </div>

        {refusal ? (
          <p className="rounded-md border border-destructive/30 bg-destructive/5 p-2 text-xs text-foreground-2">
            {refusal}
          </p>
        ) : null}

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            // THE COUNT IS LIVE AND IT IS IN THE BUTTON (S2-04 Must-match). A processor who deselected
            // a row should see the number they are about to act on, on the control that acts.
            disabled={pending || sourceDate === ""}
            onClick={() =>
              onSubmit({
                status,
                source_kind: sourceKind,
                source_date: sourceDate,
                note: note.trim() === "" ? null : note.trim(),
              })
            }
          >
            Record for {count} condition{count === 1 ? "" : "s"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * S2-05 — "Move 0006 back to To do?", and the same dialog retitled as "Reopen 0006?".
 *
 * THE REASON IS REQUIRED AND THE HINT SAYS WHY (the design's own words): "Moving back keeps the
 * history. Moving forward never needs a reason." A backward move is the one place our track loses
 * work that was recorded, so the history is where it survives.
 */
export function MoveBackDialog({
  condition,
  to,
  mode,
  open,
  onOpenChange,
  onSubmit,
  refusal,
  pending,
}: {
  condition: Condition | null;
  /** The target of a backward move. Null when reopening, which has no prep target. */
  to: ConditionPrepStatus | null;
  mode: "move-back" | "reopen";
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (reason: string) => void;
  refusal: string | null;
  pending: boolean;
}) {
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (open) setReason("");
  }, [open]);

  if (!condition) return null;

  const code = condition.lender_code ?? "this condition";
  const fromMeta = resolveStatus(CONDITION_PREP_STATUS, condition.prep_status);
  const toMeta = to ? CONDITION_PREP_STATUS[to] : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {mode === "reopen"
              ? `Reopen ${code}?`
              : `Move ${code} back to ${toMeta?.label ?? "an earlier step"}?`}
          </DialogTitle>
        </DialogHeader>

        {mode === "move-back" && toMeta ? (
          <div className="flex items-center gap-2">
            <StatusToken meta={fromMeta} />
            <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
            <StatusToken meta={toMeta} />
          </div>
        ) : null}

        <p className="max-w-prose font-serif text-xs text-foreground-2">
          {condition.verbatim_text}
        </p>

        <div className="flex flex-col gap-1">
          <label
            htmlFor="move-reason"
            className="text-xs font-medium uppercase tracking-wide text-muted-foreground"
          >
            Why? (required)
          </label>
          <Textarea
            id="move-reason"
            rows={3}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
          <span className="text-xs text-muted-foreground">
            Moving back keeps the history. Moving forward never needs a reason.
          </span>
        </div>

        {refusal ? (
          <p className="rounded-md border border-destructive/30 bg-destructive/5 p-2 text-xs text-foreground-2">
            {refusal}
          </p>
        ) : null}

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={pending || reason.trim() === ""}
            onClick={() => onSubmit(reason.trim())}
          >
            {mode === "reopen" ? "Reopen" : "Move back"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
