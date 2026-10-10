"use client";

import {
  type AddedStep,
  BLOCK_LABEL,
  type BlockKey,
  addedStepFor,
} from "@/components/file/conditions/plan-add-step";
import { Button } from "@/components/ui/button";
import { useDescribeSteps } from "@/lib/api/conditions";
import { PERFORMER_LABEL } from "@/lib/conditions/plan-words";
import { getErrorMessage } from "@/lib/errors/api-error";
import type { DescribeResult, DescribedStep, PlanOption } from "@/lib/types/conditions";
import { useId, useState } from "react";

/**
 * LP-971 — "Or describe what you want to do · Turn it into steps" (the agreed design, the "The plan as
 * a path" board). She writes a sentence; the AI proposes steps; she sees them and adds them.
 *
 * SHE ADDS THEM, AND THROUGH LP-969'S DOORS. The server's proposal stores nothing
 * (`condition_describe.describe_steps`). "Add these steps" turns each one into the step the same block
 * chosen by hand becomes (`addedStepFor`), so an AI step is drafted, checked and recorded exactly as
 * hers.
 *
 * THE CHECKS ARE THE SERVER'S AND SHE SEES THEM: a step outside the real blocks, an email to someone
 * the screen cannot email, or a step that mentions an amount, date or number in neither her words nor
 * the lender's is left out, and each is listed with its reason. A failure or an empty answer is a
 * sentence, never an empty list.
 *
 * A QUESTION'S WORDS ARE NOT IN ITS NOTE. The underwriter note is drafted by code from the condition
 * (`render_question`); her words cannot be stored on it from here, so the step says to put them in the
 * note rather than claiming they are already there.
 */
export function DescribeSteps({
  conditionId,
  ownStep,
  pending,
  onAddAll,
  onDone,
}: {
  conditionId: string;
  ownStep: PlanOption | null;
  pending: boolean;
  /**
   * LP-971 REVIEW — THE WHOLE PROPOSAL IN ONE CALL, not one call per step. Calling an add handler in a
   * loop fired every add at once: the link dialog then opened on whichever item came back first rather
   * than the step that asked for it, and N concurrent `resync_file` calls raced on one file. The parent
   * chains them, so this hands over the list and lets it.
   */
  onAddAll: (steps: AddedStep[]) => void;
  onDone: () => void;
}) {
  const describe = useDescribeSteps();
  const [words, setWords] = useState("");
  const [result, setResult] = useState<DescribeResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wordsId = useId();

  const turn = () => {
    setError(null);
    setResult(null);
    describe.mutate(
      { conditionId, text: words.trim() },
      { onSuccess: setResult, onError: (err) => setError(getErrorMessage(err)) },
    );
  };
  const addAll = (steps: DescribedStep[]) => {
    onAddAll(steps.map((step) => addedStepFor(step.block, step.text, step.to ?? "borrower")));
    // HER WORDS STAY WHEN A QUESTION TOOK THEM (LP-971 review). A question block sets the condition's
    // own step and keeps no text — `render_question` writes the note from the condition — so the step
    // says to put her words in the note before sending. Clearing the box in the same press took the
    // words she was told to put there off the screen, and nothing else holds them. For every other
    // block her words are the task's name, so they are safely in the plan and the box can clear.
    if (!steps.some((step) => isQuestion(step.block))) setWords("");
    setResult(null);
    onDone();
  };

  return (
    <div className="flex flex-col gap-2 rounded-[var(--radius-container)] border border-border bg-card p-3">
      <label htmlFor={wordsId} className="text-sm font-semibold text-foreground">
        Or describe what you want to do
      </label>
      <textarea
        id={wordsId}
        value={words}
        maxLength={500}
        rows={2}
        placeholder="e.g. Ask the underwriter to move 1228 to closing, it's new construction"
        onChange={(event) => setWords(event.target.value)}
        className="rounded-md border border-input bg-card px-2 py-1.5 text-sm text-foreground"
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={!words.trim() || describe.isPending}
          onClick={turn}
        >
          {describe.isPending ? "Turning it into steps…" : "Turn it into steps"}
        </Button>
        <span className="text-xs text-foreground-2">
          We propose the steps. You check them before anything is added or sent.
        </span>
      </div>
      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      {result?.refusal ? <p className="text-sm text-foreground-2">{result.refusal}</p> : null}
      {result && result.steps.length > 0 ? (
        <div className="flex flex-col gap-2 border-t border-dashed border-border pt-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-foreground-2">
            Proposed steps
          </p>
          <ol aria-label="Proposed steps" className="flex list-decimal flex-col gap-1.5 pl-5">
            {result.steps.map((step, index) => (
              <li key={`${index}-${step.text}`} className="text-sm text-foreground">
                <strong className="font-semibold">{BLOCK_LABEL[step.block]}</strong>
                {step.to ? ` (${PERFORMER_LABEL[step.to]})` : ""}: {step.text}
                {isQuestion(step.block) ? (
                  <span className="block text-xs text-foreground-2">
                    We draft the note from the condition. Put this in it before you send.
                    {ownStep !== null && ownStep !== stepOption(step.block)
                      ? " It replaces this condition’s own step."
                      : ""}
                  </span>
                ) : null}
              </li>
            ))}
          </ol>
          <div className="flex gap-2">
            <Button type="button" size="sm" disabled={pending} onClick={() => addAll(result.steps)}>
              {result.steps.length === 1
                ? "Add this step"
                : `Add these ${result.steps.length} steps`}
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setResult(null)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : null}
      {result && result.left_out.length > 0 ? (
        <ul aria-label="Left out" className="flex flex-col gap-0.5 text-xs text-foreground-2">
          {result.left_out.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function stepOption(block: DescribedStep["block"]): PlanOption {
  return block === "underwriter" ? "ask_underwriter" : "push_back";
}

function isQuestion(block: DescribedStep["block"]): boolean {
  return block === "underwriter" || block === "push_back";
}
