"use client";

import { Button } from "@/components/ui/button";
import { type AddedPlace, askedWho } from "@/lib/conditions/plan-path";
import { OPTION_LABEL, PERFORMER_LABEL } from "@/lib/conditions/plan-words";
import type { ConditionItem, PlanOption } from "@/lib/types/conditions";
import { Check } from "lucide-react";

/**
 * LP-971 follow-up — WHAT WAS ADDED, WHERE SHE CLICKED (the owner on 0006, 2026-10-11: "when I click add
 * to plan I am not sure whether it was added"). "Add these steps" closed the proposal and the new steps
 * appeared far up the path, marked only "added by you". This note sits right above "Add a step" and says
 * what each step became, which numbers of the path it is, and what was not added and why; the steps
 * themselves are marked New in the timeline until she presses Done.
 *
 * NOTHING IS SENT, AND IT SAYS SO: an email step only drafts; she reviews and sends it herself.
 */
export function PlanAdded({
  code,
  places,
  ownStep,
  leftOut,
  onDone,
}: {
  code: string;
  places: AddedPlace[];
  /** The condition's own step, when a question was among what she added. */
  ownStep: PlanOption | null;
  /** "Describe it"'s steps left out, each with its reason. */
  leftOut: string[];
  onDone: () => void;
}) {
  const asks = places.some((place) => isAsk(place.item));
  return (
    <output className="flex flex-col gap-2.5 rounded-[var(--radius-container)] border border-success/40 bg-success/5 p-3">
      <p className="flex items-center gap-2 text-sm font-semibold text-foreground">
        <Check aria-hidden className="h-4 w-4 text-success" />
        Added to {code}’s plan
      </p>
      {places.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {places.map((place) => (
            <li key={place.item.id} className="flex flex-col gap-0.5 text-sm">
              <span>
                <strong className="font-semibold">{kindOf(place.item)}:</strong> {place.item.name}
              </span>
              <span className="text-[13px] text-foreground-2">
                {place.first === place.last
                  ? `Step ${place.first} of the path.`
                  : `Steps ${place.first} to ${place.last} of the path.`}{" "}
                <a
                  href={`#${planStepAnchor(place.item.id)}`}
                  className="font-semibold text-primary hover:underline"
                >
                  Show it
                </a>
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {ownStep !== null ? (
        <p className="text-sm">
          <strong className="font-semibold">The condition’s own step:</strong>{" "}
          {OPTION_LABEL[ownStep]}
        </p>
      ) : null}
      {leftOut.length > 0 ? (
        <div className="flex flex-col gap-0.5 text-[13px] text-foreground-2">
          <span className="font-semibold">Not added:</span>
          <ul className="flex flex-col gap-0.5">
            {leftOut.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {asks ? (
        <p className="text-[13px] text-foreground-2">
          Nothing is sent: you review the email and send it yourself.
        </p>
      ) : null}
      <Button type="button" size="sm" variant="outline" className="self-start" onClick={onDone}>
        Done
      </Button>
    </output>
  );
}

/** The id of a task's first step in the timeline, which "Show it" scrolls to. */
export function planStepAnchor(itemId: string): string {
  return `plan-step-${itemId}`;
}

function isAsk(item: ConditionItem): boolean {
  return item.option === "ask_borrower" || item.option === "ask_third_party";
}

function kindOf(item: ConditionItem): string {
  if (isAsk(item)) return `Email to ${askedWho(item)}`;
  if (item.waiting) return `Wait for ${PERFORMER_LABEL[item.performer]}`;
  return "Your task";
}
