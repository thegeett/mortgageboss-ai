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
import { useConfirmPlan, useRoundPlan, useSetNextStep, useUpdateItem } from "@/lib/api/conditions";
import { OPTION_LABEL } from "@/lib/conditions/plan-words";
import {
  BUCKET_KIND_MEANING,
  OPTION_EXAMPLE,
  OPTION_MEANING,
  OPTION_ORDER,
  actionFor,
  meaningFor,
} from "@/lib/conditions/step-meaning";
import { getErrorMessage } from "@/lib/errors/api-error";
import { BUCKET_KIND_CHIP } from "@/lib/types/conditions";
import type { Condition, ConditionItem, ConditionRound, PlanOption } from "@/lib/types/conditions";
import { cn } from "@/lib/utils";
import { Check, ChevronDown, ChevronUp, Info, TriangleAlert } from "lucide-react";
import { useId, useState } from "react";

/**
 * "Plan for round 1" (S3-02, LP-920): every step is a proposal until she confirms it.
 *
 * LP-966 — IT EXPLAINS ITSELF (the owner, 2026-10-08: "I dont understand what is going on after
 * import"; "we need better explaination, and some where detail explaination so the processor can
 * understand what they has to do"). The design was agreed as a mockup first (the "Plan screen
 * explained" artifact):
 * - a heading that says what to do on this screen, and three numbered steps;
 * - each condition collapsed to its tasks and who does each, and opened to "What you need to do": what
 *   the lender wants, when it is due, the lender's words, each task's step, what it is done with, and
 *   the library's "Good to know";
 * - a one-line meaning under every step select, and an ⓘ beside it opening all eight steps' meanings
 *   with the current one marked;
 * - "When you confirm, we will:" spelling out the emails, the ready conditions and her tasks.
 *
 * ONE SELECT PER TASK. The panel used to show one select per DISTINCT step and change every task
 * sharing it; each task now has its own, through the same `useUpdateItem`, so a step sits beside the
 * task it belongs to. The condition's own step (push back, lender is doing it…) has a select of its own.
 *
 * NO HIDE (the owner, 2026-10-08: "there should not be hide button plan section"). The plan is the step
 * she is on until she confirms it; the list appears after (LP-964).
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
  const [refusal, setRefusal] = useState<string | null>(null);
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const [help, setHelp] = useState<{ title: string; current: PlanOption } | null>(null);

  const data = plan.data;
  if (!data || data.confirmed_at !== null || data.planned === 0) return null;

  // EVERY CONDITION ON THE ROUND (the owner, 2026-10-08: "show every condition in the plan"). Rows with
  // no task and no step used to be filtered out, so a failed reading left the table short of its own
  // count, and "Confirm 1947's reading first" named a condition that was not on the screen to click.
  const rows = conditions
    .filter((condition) => condition.last_seen_round_id === round.id)
    .sort((a, b) => a.sequence - b.sequence);
  const blocked = data.blocking_codes.length > 0;
  const emails = data.drafts.length;

  const onError = (error: unknown) => setRefusal(getErrorMessage(error));
  const changeItem = (condition: Condition, item: ConditionItem, to: PlanOption) => {
    setRefusal(null);
    updateItem.mutate({ conditionId: condition.id, itemId: item.id, option: to }, { onError });
  };
  const changeStep = (condition: Condition, to: PlanOption) => {
    setRefusal(null);
    setNextStep.mutate({ conditionId: condition.id, next_step: to }, { onError });
  };
  const toggle = (id: string) =>
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <section className="flex flex-col gap-4 rounded-[var(--radius-container)] border border-primary/35 bg-card p-4 sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <p className="flex flex-wrap gap-x-1.5 text-xs font-semibold uppercase tracking-wide text-primary">
            <span>Plan for round {data.round_number ?? ""}</span>
            <span aria-hidden>·</span>
            <span>
              {data.planned} {data.planned === 1 ? "condition" : "conditions"} · sheet dated{" "}
              {usDate(data.round_date)} ·{" "}
              {data.nothing_sent ? "nothing sent yet" : "some emails were sent"}
            </span>
          </p>
          <h2 className="text-xl font-semibold text-foreground">Check the plan, then confirm it</h2>
          <p className="max-w-prose text-sm text-foreground-2">
            We read each condition on the lender’s sheet and worked out what it asks for, who has to
            do it, and what should happen next. Look it over before anything goes out.
          </p>
        </div>
      </div>

      <ol className="grid gap-2 sm:grid-cols-3">
        <HowStep n={1}>
          <strong className="font-semibold text-foreground">Open each condition</strong> to see what
          the lender wants, when it’s due, and exactly what you’ll need.
        </HowStep>
        <HowStep n={2}>
          <strong className="font-semibold text-foreground">Change a next step</strong> if it’s
          wrong. Not sure what one means? Click{" "}
          <Info className="inline h-3.5 w-3.5 align-[-2px] text-primary" aria-label="the i icon" />{" "}
          beside it.
        </HowStep>
        <HowStep n={3}>
          <strong className="font-semibold text-foreground">Confirm the plan.</strong> Nothing is
          emailed or changed on the file until you do.
        </HowStep>
      </ol>

      <div className="flex flex-wrap gap-2">
        <Pill>
          <b className="font-semibold text-foreground">
            {emails} {emails === 1 ? "email" : "emails"}
          </b>{" "}
          to draft
          {emails > 0 ? ` — ${data.drafts.map((draft) => draft.label).join(", ")}` : ""}
        </Pill>
        <Pill>
          <b className="font-semibold text-foreground">
            {data.your_tasks} {data.your_tasks === 1 ? "task" : "tasks"}
          </b>{" "}
          for you
        </Pill>
        <Pill>
          <b className="font-semibold text-foreground">{data.already_in_file}</b> already in the
          file
        </Pill>
        {data.push_back > 0 ? (
          <Pill>
            <b className="font-semibold text-foreground">{data.push_back}</b> to push back
          </Pill>
        ) : null}
        {data.lender_doing_it > 0 ? (
          <Pill>
            <b className="font-semibold text-foreground">{data.lender_doing_it}</b> the lender does
          </Pill>
        ) : null}
        {data.needs_confirmation > 0 ? (
          <Pill tone="warning">
            <TriangleAlert className="h-3.5 w-3.5" aria-hidden />
            <b className="font-semibold">{data.needs_confirmation}</b> need you to check how we read
            {data.needs_confirmation === 1 ? " it" : " them"}
          </Pill>
        ) : null}
      </div>

      <div className="overflow-hidden rounded-[var(--radius-container)] border border-border">
        {rows.map((condition) => (
          <PlanRow
            key={condition.id}
            condition={condition}
            open={open.has(condition.id)}
            onToggle={() => toggle(condition.id)}
            onOpenCondition={() => onOpenCondition(condition.id)}
            onConfirmReading={() => onConfirmReading(condition.id)}
            onChangeItem={(item, to) => changeItem(condition, item, to)}
            onChangeStep={(to) => changeStep(condition, to)}
            onHelp={(title, current) => setHelp({ title, current })}
          />
        ))}
      </div>

      {refusal ? <p className="text-sm text-destructive">{refusal}</p> : null}

      <div className="flex flex-col gap-3 rounded-[var(--radius-container)] bg-muted/50 p-4">
        <ConfirmSummary rows={rows} drafts={data.drafts} />
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            disabled={blocked || confirm.isPending}
            onClick={() => confirm.mutate({ roundId: round.id }, { onError })}
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
          ) : (
            <p className="text-xs text-muted-foreground">
              Nothing is sent until you press confirm, and every email waits for your review.
            </p>
          )}
        </div>
      </div>

      <StepGuide help={help} onClose={() => setHelp(null)} />
    </section>
  );
}

function HowStep({ n, children }: { n: number; children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2.5 rounded-[var(--radius-container)] bg-muted/50 px-3 py-2.5 text-sm text-foreground-2">
      <span
        aria-hidden
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground"
      >
        {n}
      </span>
      <span>{children}</span>
    </li>
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

/** The items still on the plan. */
function live(condition: Condition): ConditionItem[] {
  return condition.items.filter((item) => item.status !== "not_needed");
}

function PlanRow({
  condition,
  open,
  onToggle,
  onOpenCondition,
  onConfirmReading,
  onChangeItem,
  onChangeStep,
  onHelp,
}: {
  condition: Condition;
  open: boolean;
  onToggle: () => void;
  onOpenCondition: () => void;
  onConfirmReading: () => void;
  onChangeItem: (item: ConditionItem, to: PlanOption) => void;
  onChangeStep: (to: PlanOption) => void;
  onHelp: (title: string, current: PlanOption) => void;
}) {
  const detailsId = useId();
  const items = live(condition);
  const needsHer = condition.reading_status === "needs_confirmation";
  const code = condition.lender_code ?? "—";
  const title = condition.reading?.summary ?? condition.verbatim_text;
  const ownStep = condition.next_step;
  // Nothing worked out: no task and no step of its own (the reading failed or found nothing to ask).
  const unworked = items.length === 0 && ownStep === null;

  return (
    <div className={cn("border-b border-border last:border-b-0", needsHer && "bg-warning/5")}>
      <div className="flex flex-wrap items-start gap-x-5 gap-y-3 px-4 py-3.5">
        <div className="flex min-w-0 flex-[999_1_32rem] flex-col gap-2">
          <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
            <button
              type="button"
              onClick={onOpenCondition}
              className="font-mono text-sm font-medium text-foreground hover:underline"
            >
              {code}
            </button>
            <span className="text-base font-semibold text-foreground">{title}</span>
            <span className="rounded-md border border-input px-1.5 py-0.5 text-xs text-foreground-2">
              {BUCKET_KIND_CHIP[condition.bucket_kind]}
            </span>
            {needsHer && !unworked ? (
              <button
                type="button"
                onClick={onConfirmReading}
                className="inline-flex items-center gap-1 rounded-md border border-warning/50 bg-warning/10 px-1.5 py-0.5 text-xs font-medium text-warning"
              >
                <TriangleAlert className="h-3 w-3" aria-hidden />
                Check how we read it
              </button>
            ) : null}
          </div>
          {ownStep ? (
            <TaskLine name="The whole condition" action={actionFor(ownStep, null)} />
          ) : null}
          {items.map((item) => (
            <TaskLine
              key={item.id}
              name={item.name}
              action={actionFor(item.option, item)}
              extra={extraFor(item)}
            />
          ))}
          {unworked ? <Unworked onConfirmReading={onConfirmReading} /> : null}
        </div>
        <div className="flex flex-[1_1_10rem] justify-end">
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-expanded={open}
            aria-controls={detailsId}
            onClick={onToggle}
          >
            {open ? (
              <ChevronUp className="h-4 w-4" aria-hidden />
            ) : (
              <ChevronDown className="h-4 w-4" aria-hidden />
            )}
            {open ? "Hide details" : "What you need to do"}
          </Button>
        </div>
      </div>

      {open ? (
        <div
          id={detailsId}
          className="mx-4 mb-4 grid gap-x-7 gap-y-5 rounded-[var(--radius-container)] border border-border bg-muted/40 p-4 md:grid-cols-2"
        >
          <div className="flex flex-col gap-4">
            <Detail heading="What the lender wants">
              {condition.reading?.explanation ?? title}
            </Detail>
            <Detail heading="When it’s needed">
              <strong className="font-semibold">{BUCKET_KIND_CHIP[condition.bucket_kind]}</strong> —{" "}
              {BUCKET_KIND_MEANING[condition.bucket_kind]}
            </Detail>
            {condition.plan_reason ? (
              <Detail heading="Why we suggest this">{condition.plan_reason}</Detail>
            ) : null}
            <Detail heading="The lender’s exact words">
              <span className="font-serif text-foreground-2">{condition.verbatim_text}</span>
            </Detail>
          </div>

          <div className="flex flex-col gap-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-foreground-2">
              What you need to do
            </p>
            {ownStep ? (
              <StepCard
                n={null}
                name="The whole condition"
                doneWhen={null}
                option={ownStep}
                item={null}
                onChange={onChangeStep}
                onHelp={() => onHelp(`the whole condition (${code})`, ownStep)}
              />
            ) : null}
            {unworked ? <Unworked onConfirmReading={onConfirmReading} /> : null}
            {items.map((item, index) => (
              <StepCard
                key={item.id}
                n={index + 1}
                name={item.name}
                doneWhen={item.generic ? null : item.acceptable}
                extra={extraFor(item)}
                option={item.option}
                item={item}
                onChange={(to) => onChangeItem(item, to)}
                onHelp={() => onHelp(`${item.name} (${code})`, item.option)}
              />
            ))}
            {condition.library_type?.playbook ? (
              <p className="flex items-start gap-2 border-t border-dashed border-border pt-3 text-sm text-foreground-2">
                <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
                <span>
                  <strong className="font-semibold text-foreground">Good to know:</strong>{" "}
                  {condition.library_type.playbook}
                </span>
              </p>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** A condition with nothing worked out: say so, and offer the way to fix it. */
function Unworked({ onConfirmReading }: { onConfirmReading: () => void }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm text-foreground-2">
      <span>We couldn’t work out what this one needs.</span>
      <Button type="button" variant="outline" size="sm" onClick={onConfirmReading}>
        Check how we read it
      </Button>
    </div>
  );
}

/** "Waits on 1228", "Found: HR Loan Processing invoice, page 1": what the step line also needs. */
function extraFor(item: ConditionItem): string | null {
  if (item.waits_on_code) return `Waits on ${item.waits_on_code}`;
  if (item.option === "already_in_file" && item.document_name) {
    return `Found: ${item.document_name}${item.document_page ? `, page ${item.document_page}` : ""}`;
  }
  return null;
}

function TaskLine({
  name,
  action,
  extra,
}: {
  name: string;
  action: string;
  extra?: string | null;
}) {
  return (
    <p className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-sm">
      <span className="text-foreground">{name}</span>
      <span aria-hidden className="text-muted-foreground">
        →
      </span>
      <span className="rounded-md bg-primary/10 px-2 py-0.5 font-medium text-primary">
        {action}
      </span>
      {extra ? <span className="text-xs text-muted-foreground">{extra}</span> : null}
    </p>
  );
}

function Detail({ heading, children }: { heading: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <p className="text-xs font-semibold uppercase tracking-wide text-foreground-2">{heading}</p>
      <p className="text-sm leading-relaxed text-foreground">{children}</p>
    </div>
  );
}

function StepCard({
  n,
  name,
  doneWhen,
  extra,
  option,
  item,
  onChange,
  onHelp,
}: {
  n: number | null;
  name: string;
  doneWhen: string | null;
  extra?: string | null;
  option: PlanOption;
  item: ConditionItem | null;
  onChange: (to: PlanOption) => void;
  onHelp: () => void;
}) {
  const selectId = useId();
  return (
    <div className="flex items-start gap-3 rounded-[var(--radius-container)] border border-border bg-card px-3.5 py-3">
      {n !== null ? (
        <span
          aria-hidden
          className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-primary text-xs font-semibold text-primary"
        >
          {n}
        </span>
      ) : null}
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <p className="text-sm font-semibold text-foreground">{name}</p>
        {doneWhen ? (
          <p className="text-sm text-foreground-2">
            <strong className="font-semibold text-foreground">Done when you have:</strong>{" "}
            {doneWhen}
          </p>
        ) : null}
        {extra ? <p className="text-xs text-muted-foreground">{extra}</p> : null}
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor={selectId} className="text-xs text-foreground-2">
            Next step
          </label>
          <select
            id={selectId}
            value={option}
            onChange={(event) => onChange(event.target.value as PlanOption)}
            className="h-8 w-auto rounded-md border border-primary/40 bg-card px-1.5 text-sm font-medium text-primary"
          >
            {OPTION_ORDER.map((each) => (
              <option key={each} value={each}>
                {OPTION_LABEL[each]}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={onHelp}
            aria-label="What the next steps mean"
            title="What the next steps mean"
            className="flex h-7 w-7 items-center justify-center rounded-md text-primary hover:bg-primary/10"
          >
            <Info className="h-4 w-4" aria-hidden />
          </button>
        </div>
        <p className="rounded-md bg-muted/60 px-2.5 py-1.5 text-xs text-foreground-2">
          <strong className="font-semibold text-primary">{OPTION_LABEL[option]}:</strong>{" "}
          {meaningFor(option, item)}
        </p>
      </div>
    </div>
  );
}

/** "When you confirm, we will:", from the plan's own drafts and the rows' steps. */
function ConfirmSummary({
  rows,
  drafts,
}: {
  rows: Condition[];
  drafts: { label: string; codes: string[] }[];
}) {
  const ready: string[] = [];
  const tasks: string[] = [];
  const questions: string[] = [];
  const lenders: string[] = [];
  for (const condition of rows) {
    const code = condition.lender_code ?? "—";
    const items = live(condition);
    if (
      condition.next_step === "already_in_file" ||
      (items.length > 0 && items.every((item) => item.option === "already_in_file"))
    ) {
      ready.push(code);
    }
    if (condition.next_step === "ask_underwriter" || condition.next_step === "push_back") {
      questions.push(code);
    }
    if (condition.next_step === "lender_doing_it") lenders.push(code);
    for (const item of items) {
      if (item.option !== "i_will_do_it") continue;
      const what = item.task ?? item.name.toLowerCase();
      tasks.push(`${what} (${code}${item.waits_on_code ? `, after ${item.waits_on_code}` : ""})`);
    }
  }
  const lines: React.ReactNode[] = [];
  if (drafts.length > 0) {
    lines.push(
      <li key="emails">
        <strong className="font-semibold">
          Draft {drafts.length} {drafts.length === 1 ? "email" : "emails"}
        </strong>
        : {drafts.map((draft) => `to ${draft.label} (${draft.codes.join(", ")})`).join("; ")}. You
        review each one before it is sent.
      </li>,
    );
  }
  if (questions.length > 0) {
    lines.push(
      <li key="questions">
        <strong className="font-semibold">Draft a note to the underwriter</strong> on{" "}
        {questions.join(", ")}.
      </li>,
    );
  }
  if (ready.length > 0) {
    lines.push(
      <li key="ready">
        <strong className="font-semibold">Mark {ready.join(", ")} ready</strong>: the document is
        already in the file.
      </li>,
    );
  }
  if (tasks.length > 0) {
    lines.push(
      <li key="tasks">
        <strong className="font-semibold">
          Add {tasks.length} {tasks.length === 1 ? "task" : "tasks"} to your list
        </strong>
        : {tasks.join("; ")}.
      </li>,
    );
  }
  if (lenders.length > 0) {
    lines.push(
      <li key="lender">
        <strong className="font-semibold">Leave {lenders.join(", ")} to the lender</strong>; you
        watch for it to clear.
      </li>,
    );
  }
  if (lines.length === 0) return null;
  return (
    <div className="flex flex-col gap-2">
      <p className="text-sm font-semibold text-foreground">When you confirm, we will:</p>
      <ul className="flex list-disc flex-col gap-1 pl-5 text-sm text-foreground">{lines}</ul>
    </div>
  );
}

/** The ⓘ dialog: all eight steps, what each does, the current one marked. */
function StepGuide({
  help,
  onClose,
}: {
  help: { title: string; current: PlanOption } | null;
  onClose: () => void;
}) {
  return (
    <Dialog
      open={help !== null}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <DialogContent className="max-h-[88vh] max-w-xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>What the next steps mean</DialogTitle>
          <DialogDescription>
            {help ? `For ${help.title}. ` : ""}The next step decides what happens when you confirm
            the plan: a task on your list, a line in an email, or nothing to do.
          </DialogDescription>
        </DialogHeader>
        <ul className="flex flex-col gap-2">
          {OPTION_ORDER.map((option) => {
            const current = help?.current === option;
            return (
              <li
                key={option}
                className={cn(
                  "flex flex-col gap-1 rounded-[var(--radius-container)] border px-3 py-2.5",
                  current ? "border-primary bg-primary/5" : "border-border",
                )}
              >
                <p className="flex items-baseline justify-between gap-2">
                  <span className="text-sm font-semibold text-primary">{OPTION_LABEL[option]}</span>
                  {current ? (
                    <span className="rounded-md bg-primary px-1.5 py-0.5 text-xs font-semibold text-primary-foreground">
                      Selected
                    </span>
                  ) : null}
                </p>
                <p className="text-sm text-foreground-2">{OPTION_MEANING[option]}</p>
                <p className="text-xs text-muted-foreground">
                  <strong className="font-semibold">Example:</strong> {OPTION_EXAMPLE[option]}
                </p>
              </li>
            );
          })}
        </ul>
        <DialogFooter>
          <Button type="button" onClick={onClose}>
            Got it
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function usDate(iso: string): string {
  const [year, month, day] = iso.slice(0, 10).split("-");
  return `${month}/${day}/${year}`;
}
