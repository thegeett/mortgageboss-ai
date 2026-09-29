"use client";

import { Button } from "@/components/ui/button";
import { useConfirmPlan, useRoundPlan, useSetNextStep, useUpdateItem } from "@/lib/api/conditions";
import { stepOptions } from "@/lib/conditions/next-step";
import { OPTION_LABEL, PERFORMER_LABEL, performersLabel } from "@/lib/conditions/plan-words";
import { getErrorMessage } from "@/lib/errors/api-error";
import type { Condition, ConditionItem, ConditionRound, PlanOption } from "@/lib/types/conditions";
import { cn } from "@/lib/utils";
import { Check, Sparkles, TriangleAlert } from "lucide-react";
import { useState } from "react";

const OPTIONS: PlanOption[] = [
  "ask_borrower",
  "ask_third_party",
  "i_will_do_it",
  "already_in_file",
  "ask_underwriter",
  "push_back",
  "lender_doing_it",
  "information_only",
];

/**
 * "Plan for round 1" (S3-02, LP-920): every step is a proposal until she confirms it.
 *
 * Under the round strip, above the summary bar, while the newest round's plan is unconfirmed. One row
 * per condition in sheet order: code, the lender's ask in a line, the items and who acts, the next
 * step(s) as selects with the reason under them, and the reading's confidence.
 *
 * NOTHING IS DRAFTED PAST A READING THAT NEEDS HER (README rule 3): the confirm button stays disabled,
 * and says which condition to confirm, until every reading on the round is ready or confirmed.
 */
export function RoundPlanPanel({
  fileId,
  round,
  conditions,
  onOpenCondition,
  onConfirmReading,
}: {
  fileId: string;
  round: ConditionRound;
  conditions: Condition[];
  onOpenCondition: (conditionId: string) => void;
  onConfirmReading: (conditionId: string) => void;
}) {
  const plan = useRoundPlan(round.id);
  const confirm = useConfirmPlan(fileId);
  const setNextStep = useSetNextStep(fileId);
  const updateItem = useUpdateItem(fileId);
  const [hidden, setHidden] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);

  const data = plan.data;
  if (!data || hidden || data.confirmed_at !== null || data.planned === 0) return null;

  const rows = conditions
    .filter((condition) => condition.last_seen_round_id === round.id)
    .filter((condition) => condition.next_step !== null || condition.items.length > 0)
    .sort((a, b) => a.sequence - b.sequence);
  const blocked = data.blocking_codes.length > 0;
  const emails = data.drafts.length;

  const changeOption = (condition: Condition, from: PlanOption, to: PlanOption) => {
    setRefusal(null);
    if (from === condition.next_step) {
      setNextStep.mutate(
        { conditionId: condition.id, next_step: to },
        { onError: (error) => setRefusal(getErrorMessage(error)) },
      );
      return;
    }
    for (const item of condition.items.filter((each) => each.option === from)) {
      updateItem.mutate(
        { conditionId: condition.id, itemId: item.id, option: to },
        { onError: (error) => setRefusal(getErrorMessage(error)) },
      );
    }
  };

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-primary/35 bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-foreground-2">
            Plan for round {data.round_number ?? ""}
          </p>
          <p className="mt-0.5 text-base font-semibold text-foreground">
            {data.planned} conditions · {usDate(data.round_date)} ·{" "}
            {data.nothing_sent ? "nothing has been sent" : "some emails were sent"}
          </p>
          <p className="text-xs text-muted-foreground">
            Read by AI with the condition library. Every step below is a proposal — change any of
            them before confirming.
          </p>
        </div>
        <Button type="button" variant="ghost" size="sm" onClick={() => setHidden(true)}>
          Hide
        </Button>
      </div>

      <div className="flex flex-wrap gap-2">
        <Pill>
          {emails} {emails === 1 ? "email" : "emails"} to draft{" "}
          <span className="font-semibold text-foreground">
            {data.drafts.map((draft) => draft.label).join(" · ")}
          </span>
        </Pill>
        <Pill>
          Your tasks <b>{data.your_tasks}</b>
        </Pill>
        <Pill>
          Already in the file <b>{data.already_in_file}</b>
        </Pill>
        <Pill>
          Push back <b>{data.push_back}</b>
        </Pill>
        <Pill>
          Lender is doing it <b>{data.lender_doing_it}</b>
        </Pill>
        {data.needs_confirmation > 0 ? (
          <Pill tone="warning">
            <TriangleAlert className="h-3.5 w-3.5" aria-hidden />
            Please confirm <b>{data.needs_confirmation}</b>
          </Pill>
        ) : null}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-foreground-2">
              <th className="w-14 py-2 pr-2 font-semibold">Code</th>
              <th className="py-2 pr-2 font-semibold">What the lender wants · items → who</th>
              <th className="w-80 py-2 pr-2 font-semibold">Next step</th>
              <th className="w-28 py-2 font-semibold">Reading</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((condition) => {
              const needsHer = condition.reading_status === "needs_confirmation";
              const options = stepOptions(condition);
              return (
                <tr
                  key={condition.id}
                  className={cn("border-b border-border align-top", needsHer && "bg-warning/5")}
                >
                  <td className="py-2.5 pr-2">
                    <button
                      type="button"
                      onClick={() => onOpenCondition(condition.id)}
                      className="font-mono text-sm text-foreground hover:underline"
                    >
                      {condition.lender_code ?? "—"}
                    </button>
                  </td>
                  <td className="py-2.5 pr-2">
                    <p className="text-foreground">
                      {condition.reading?.summary ?? condition.verbatim_text}
                    </p>
                    <p className="text-xs text-muted-foreground">{itemsLine(condition)}</p>
                  </td>
                  <td className="py-2.5 pr-2">
                    <div className="flex flex-wrap gap-1.5">
                      {options.map((option) => (
                        <select
                          key={option}
                          aria-label={`Next step for ${condition.lender_code ?? "this condition"}`}
                          value={option}
                          onChange={(event) =>
                            changeOption(condition, option, event.target.value as PlanOption)
                          }
                          className="h-7 w-auto rounded-md border border-primary/40 bg-primary/5 px-1.5 text-sm font-medium text-primary"
                        >
                          {OPTIONS.map((each) => (
                            <option key={each} value={each}>
                              {OPTION_LABEL[each]}
                            </option>
                          ))}
                        </select>
                      ))}
                    </div>
                    {condition.plan_reason ? (
                      <p className="mt-1 text-xs text-muted-foreground">{condition.plan_reason}</p>
                    ) : null}
                  </td>
                  <td className="py-2.5">
                    <ReadingCell
                      condition={condition}
                      onConfirm={() => onConfirmReading(condition.id)}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {refusal ? <p className="text-sm text-destructive">{refusal}</p> : null}

      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          disabled={blocked || confirm.isPending}
          onClick={() =>
            confirm.mutate(
              { roundId: round.id },
              { onError: (error) => setRefusal(getErrorMessage(error)) },
            )
          }
        >
          <Check className="h-4 w-4" aria-hidden />
          Confirm plan and draft {emails} {emails === 1 ? "email" : "emails"}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            const first = rows[0];
            if (first) onOpenCondition(first.id);
          }}
        >
          Review one by one
        </Button>
        {blocked ? (
          <p className="text-xs text-muted-foreground">
            Confirm {data.blocking_codes[0]}’s reading first —{" "}
            {data.blocking_codes.length === 1
              ? "one condition still needs you."
              : `${data.blocking_codes.length} conditions still need you.`}
          </p>
        ) : null}
      </div>
    </section>
  );
}

function Pill({ children, tone }: { children: React.ReactNode; tone?: "warning" }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs text-foreground-2",
        tone === "warning" ? "border-warning/50 text-warning" : "border-input",
      )}
    >
      {children}
    </span>
  );
}

function ReadingCell({ condition, onConfirm }: { condition: Condition; onConfirm: () => void }) {
  const confidence = condition.reading_confidence;
  if (condition.reading_status === "needs_confirmation") {
    return (
      <button
        type="button"
        onClick={onConfirm}
        title={confidence === null ? "Read without the AI" : `Confidence ${confidence.toFixed(2)}`}
        className="inline-flex items-center gap-1 whitespace-nowrap rounded-md border border-warning/50 bg-warning/10 px-1.5 py-0.5 text-xs text-warning"
      >
        <TriangleAlert className="h-3 w-3" aria-hidden />
        {confidence === null ? "confirm" : `${confidence.toFixed(2)} · confirm`}
      </button>
    );
  }
  if (condition.reading_status === "confirmed") {
    return <span className="text-xs text-muted-foreground">Confirmed</span>;
  }
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md border border-ai/30 bg-ai/10 px-1.5 py-0.5 text-xs text-ai"
      title={confidence === null ? undefined : `Read by AI · ${confidence.toFixed(2)}`}
    >
      <Sparkles className="h-3 w-3" aria-hidden />
      {confidence === null ? "Library" : confidence.toFixed(2)}
    </span>
  );
}

/** "Source, clearance → Borrower · receipt → Title / escrow", or the push-back's reason. */
function itemsLine(condition: Condition): string {
  const pushBack = condition.reading?.push_back;
  if (condition.next_step === "push_back" && pushBack) {
    return `Nothing — the letter says must not close before ${usDate(pushBack.must_not_close_before)}`;
  }
  const groups = new Map<string, string[]>();
  for (const item of condition.items) {
    if (item.status === "not_needed") continue;
    const who = whoFor(item);
    groups.set(who, [...(groups.get(who) ?? []), item.name]);
  }
  const waits = condition.items.find((item) => item.waits_on_code)?.waits_on_code;
  const parts = [...groups.entries()].map(([who, names]) => `${names.join(", ")} → ${who}`);
  const line = parts.join(" · ");
  return waits ? `${line}, after ${waits}` : line;
}

function whoFor(item: ConditionItem): string {
  if (item.option === "lender_doing_it") return "Lender";
  return item.performers.length > 1
    ? performersLabel(item.performers)
    : PERFORMER_LABEL[item.performer];
}

function usDate(iso: string): string {
  const [year, month, day] = iso.slice(0, 10).split("-");
  return `${month}/${day}/${year}`;
}
