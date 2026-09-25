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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { usePasteConditions } from "@/lib/api/conditions";
import { getErrorMessage } from "@/lib/errors/api-error";
import { notifyError, notifyStarted } from "@/lib/toast";
import { MAX_PASTE_CHARS } from "@/lib/types/conditions";
import type { ConditionRoundCompleteness } from "@/lib/types/conditions";
import { cn } from "@/lib/utils";
import { useId, useState } from "react";

/** Today, as the `YYYY-MM-DD` the API takes. Local date, because it is the processor's "today". */
function today(): string {
  const now = new Date();
  const month = `${now.getMonth() + 1}`.padStart(2, "0");
  const day = `${now.getDate()}`.padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

/**
 * What each answer to "What did you paste?" actually does, in one line each (S1-06).
 *
 * ⚠️ THE WORDING IS THE DESIGN'S, AND THE SECOND ONE IS A PROMISE ABOUT STAGE 2. "anything missing
 * from a full list can be proposed as 'probably cleared' — never cleared automatically" is the
 * distinction ADR-404 turns on, and softening it here would have Stage 1 implying an automatic
 * clear that the system must never do.
 */
const ANSWERS: { value: ConditionRoundCompleteness; label: string; explains: string }[] = [
  {
    value: "partial",
    label: "Just some conditions",
    explains: "Adds or updates what you pasted. Conditions already on the file stay as they are.",
  },
  {
    value: "full",
    label: "The lender's full list",
    explains:
      "Everything the lender still wants. Later, anything missing from a full list can be proposed as “probably cleared” — never cleared automatically.",
  },
];

/**
 * Paste conditions copied from a lender portal or email (screen S1-06, LP-907's door).
 *
 * ⚠️ "JUST SOME" IS THE DEFAULT, AND THAT IS A SAFETY PROPERTY RATHER THAN A PREFERENCE. It is the
 * answer that can never remove anything. The API refuses to guess — `completeness` is required with
 * no server-side default (ADR-404) — so the control defaults and the contract does not, which is
 * what makes this a decision a processor made rather than a fallback they never saw.
 *
 * ⚠️ THE COUNT IS LIVE AND THE LIMIT IS THE SERVER'S. `MAX_PASTE_CHARS` is mirrored from
 * `app/schemas/condition.py` and pinned by `tests/test_condition_type_mirror.py`, so the number
 * shown here and the number enforced cannot drift into disagreeing — the failure the 20 MB upload
 * ceiling still has, where a client that is HIGHER lets a processor wait through an upload the
 * server then refuses.
 *
 * ⚠️ NO HARD BLOCK BELOW THE LIMIT. The design's *May differ* allows a live count only when well
 * under, and the button disables only when the text is empty or genuinely over — refusing to submit
 * at 99% would be inventing a limit the server does not have.
 */
export function PasteConditionsDialog({
  fileId,
  open,
  onOpenChange,
}: {
  fileId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const textId = useId();
  const dateId = useId();
  const answerName = useId();

  const [text, setText] = useState("");
  const [completeness, setCompleteness] = useState<ConditionRoundCompleteness>("partial");
  const [roundDate, setRoundDate] = useState(today());
  const paste = usePasteConditions(fileId);

  function reset() {
    setText("");
    setCompleteness("partial");
    setRoundDate(today());
  }

  const characters = text.length;
  const lines = text ? text.split("\n").length : 0;
  const overLimit = characters > MAX_PASTE_CHARS;

  function submit() {
    paste.mutate(
      { text, completeness, round_date: roundDate || null },
      {
        onSuccess: (round) => {
          // ⚠️ `notifyStarted`, NOT `notifySuccess`. A paste the rules cannot split comes back
          // `parsing` with the AI split queued, so "Conditions added" would be a claim about work
          // that has not finished. The round's own screen reports the outcome.
          notifyStarted({
            title: "Reading the conditions",
            consequence:
              round.status === "parsing"
                ? "The rules could not split this text, so it has gone to the AI. This page updates on its own."
                : "Nothing is saved to the file until you import.",
          });
          reset();
          onOpenChange(false);
        },
        onError: (error) =>
          notifyError({
            title: "Those conditions could not be read",
            whatToDo: getErrorMessage(error),
          }),
      },
    );
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) reset();
      }}
    >
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Paste conditions</DialogTitle>
          <DialogDescription>
            Copy from the lender portal or email. Codes and headings help, but plain text works too.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label htmlFor={textId} className="sr-only">
              The conditions you copied
            </Label>
            {/* Mono, because what is pasted is a lender's fixed-pitch layout — the columns are how
                a processor recognises it, and a proportional font destroys them. */}
            <Textarea
              id={textId}
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder="Paste the lender's conditions here…"
              className="min-h-[14rem] font-mono text-xs"
            />
            <p className={cn("text-xs", overLimit ? "text-destructive" : "text-muted-foreground")}>
              {lines} {lines === 1 ? "line" : "lines"} · {characters.toLocaleString()}{" "}
              {characters === 1 ? "character" : "characters"}
              {overLimit ? ` · over the ${MAX_PASTE_CHARS.toLocaleString()} limit` : null}
            </p>
          </div>

          <fieldset className="space-y-2">
            <legend className="text-sm font-medium text-foreground">What did you paste?</legend>
            {ANSWERS.map((answer) => (
              <label
                key={answer.value}
                className="flex cursor-pointer items-start gap-2 rounded-md border border-input p-2.5 has-[:checked]:border-primary"
              >
                {/* A native radio: there is no RadioGroup primitive in this repo, and each option
                    carries its own explanation, which a `Select` cannot render. */}
                <input
                  type="radio"
                  name={answerName}
                  value={answer.value}
                  checked={completeness === answer.value}
                  onChange={() => setCompleteness(answer.value)}
                  className="mt-1 accent-primary"
                />
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="text-sm font-medium text-foreground">{answer.label}</span>
                  <span className="text-xs text-muted-foreground">{answer.explains}</span>
                </span>
              </label>
            ))}
          </fieldset>

          <div className="space-y-1.5">
            <Label htmlFor={dateId}>Round date</Label>
            <Input
              id={dateId}
              type="date"
              value={roundDate}
              onChange={(event) => setRoundDate(event.target.value)}
              className="w-auto"
            />
            <p className="text-xs text-muted-foreground">
              The date the lender issued these, if you know it. Defaults to today.
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={paste.isPending}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={paste.isPending || !text.trim() || overLimit}>
            {paste.isPending && <Spinner className="mr-2 h-4 w-4" />}
            Read conditions
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
