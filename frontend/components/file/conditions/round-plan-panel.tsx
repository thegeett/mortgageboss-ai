"use client";

import { ItemLinkActions } from "@/components/file/conditions/item-links";
import { LinkDocumentDialog } from "@/components/file/conditions/link-document-dialog";
import { AddStep, type AddedStep } from "@/components/file/conditions/plan-add-step";
import { PlanAdded, planStepAnchor } from "@/components/file/conditions/plan-added";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  useAddItem,
  useChooseRoute,
  useConfirmPlan,
  useFileLender,
  useLogCall,
  useOwnWay,
  useRemoveItem,
  useRevertPlan,
  useRoundPlan,
  useSetNextStep,
  useUpdateItem,
} from "@/lib/api/conditions";
import {
  type PathWho,
  type PlanEntry,
  addedPlaces,
  conditionPath,
  firstMoves,
  nextOf,
  willBeReady,
} from "@/lib/conditions/plan-path";
import { OPTION_LABEL } from "@/lib/conditions/plan-words";
import {
  BUCKET_KIND_MEANING,
  ITEM_OPTION_ORDER,
  OPTION_EXAMPLE,
  OPTION_MEANING,
  OPTION_ORDER,
  actionFor,
  meaningFor,
} from "@/lib/conditions/step-meaning";
import { getErrorMessage } from "@/lib/errors/api-error";
import { notifySuccess } from "@/lib/toast";
import { BUCKET_KIND_CHIP } from "@/lib/types/conditions";
import type { Condition, ConditionItem, ConditionRound, PlanOption } from "@/lib/types/conditions";
import { cn } from "@/lib/utils";
import { Check, ChevronDown, ChevronUp, Info, TriangleAlert } from "lucide-react";
import { useId, useState } from "react";

/**
 * "Plan for round 1" (S3-02, LP-920): every step is a proposal until she confirms it.
 *
 * LP-974 — LAID OUT AS THE AGREED MOCKUP (the "Plan screen explained" artifact, board "The plan as a
 * path"). The owner: "current design and mock design is different". LP-966 to LP-968 had layered the
 * path onto LP-966's per-task cards; this puts the screen in the mockup's shape:
 * - "Here's how we'll get these N conditions cleared", then first moves and the legend;
 * - each condition collapsed to "Route:" and "Next:", opened with "See the plan";
 * - opened: on the left what the lender wants, when, "How it gets done" and the lender's words; on the
 *   right ONE numbered timeline for the whole condition, with her edits on each task's first step.
 *
 * LP-970 — "HOW IT GETS DONE" OFFERS THE CONDITION'S ROUTES where its type has them (a final
 * inspection, a business check, title and insurance), the suggested one marked with its reason, as in
 * the mockup; choosing one rebuilds the path on the server. Each task's Next step select stays under
 * "Change each task's step yourself", and is all there is for a type with no routes; "Route:" names the
 * chosen route when there is one, else what the selects say.
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
  onOpenDraft,
  confirmedRoundIds,
}: {
  fileId: string;
  round: ConditionRound;
  conditions: Condition[];
  onOpenCondition: (conditionId: string) => void;
  onConfirmReading: (conditionId: string) => void;
  /** LP-968 — open a prepared draft from its step ("Review draft"). */
  onOpenDraft?: (draftId: string) => void;
  /**
   * LP-976 — the file's rounds whose plan is confirmed. A condition with no stamp on one of them was
   * added after confirm (a PDF merged in, an attachment forwarded into the round, one typed in by hand),
   * and its plan waits for her here.
   *
   * REQUIRED, NOT OPTIONAL (LP-976 review): with a `?? false` default, a call site that forgot it would
   * hide every late condition, and with the round fallback gone their emails would wait for ever, all
   * with the suite green. Required, the compiler holds the link.
   */
  confirmedRoundIds: ReadonlySet<string>;
}) {
  const plan = useRoundPlan(round.id);
  const confirm = useConfirmPlan(fileId);
  const setNextStep = useSetNextStep(fileId);
  const updateItem = useUpdateItem(fileId);
  const revert = useRevertPlan(fileId);
  const addItem = useAddItem(fileId);
  const logCall = useLogCall(fileId);
  // LP-979 — the file's lender, so each plan's ending names who clears it.
  const fileLender = useFileLender(fileId);
  const chooseRoute = useChooseRoute(fileId);
  const ownWay = useOwnWay(fileId);
  const removeItem = useRemoveItem(fileId);
  // LP-969 — "Check a document on the file" opens the link dialog on the task it just added.
  const [linking, setLinking] = useState<{ condition: Condition; item: ConditionItem } | null>(
    null,
  );
  const [refusal, setRefusal] = useState<string | null>(null);
  // LP-971 follow-up — what the last add put on one condition's plan, until she presses Done.
  const [justAdded, setJustAdded] = useState<JustAdded | null>(null);
  // LP-978 REVIEW — A REFUSED CONFIRM BELONGS BESIDE THE BUTTON, and the button moved. There is one
  // refusal line and it is under the conditions, which was right while Confirm was down there too; now
  // a 409 from `confirm_round_plan` (the blocking codes this screen holds can be stale) renders below
  // every row, off the screen on a file with more than a handful. Two slots rather than one moved
  // line, because a step edit's refusal belongs beside the row it came from, which is still down there.
  const [confirmRefusal, setConfirmRefusal] = useState<string | null>(null);
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const [help, setHelp] = useState<{ title: string; current: PlanOption } | null>(null);

  const data = plan.data;
  if (!data) return null;
  // LP-976 — ONCE THE ROUND IS CONFIRMED, THE PANEL STAYS FOR WHAT WAS ADDED SINCE. A condition added
  // after confirm used to be in force at once, with a plan the reading proposed and no screen showed
  // (the LP-975 review's finding 3). Now its plan waits for her, so it must be on a screen she can
  // confirm it on: this one, showing only those conditions. A late one on an OLDER round appears here
  // once the newest round is confirmed; until then it waits, and so do its emails.
  const late = data.confirmed_at !== null;
  if (!late && data.planned === 0) return null;

  // EVERY CONDITION ON THE ROUND (the owner, 2026-10-08: "show every condition in the plan"). Rows with
  // no task and no step used to be filtered out, so a failed reading left the table short of its own
  // count, and "Confirm 1947's reading first" named a condition that was not on the screen to click.
  //
  // LP-973 — ONLY WHAT IS NEW ON THIS SHEET (the owner, 2026-10-09: "new only"). A condition seen again
  // keeps the plan it already had (`build_plan`'s carry-over), confirmed on its own round and often
  // with its email already out, so listing it here asked her to check and confirm last week's work
  // beside what is new. It is counted in one line instead, and is in the list once she confirms.
  // A CARRIED CONDITION THAT BLOCKS CONFIRM STAYS: "Confirm 0132's reading first" must name a row she
  // can click, the same reason every condition is shown above.
  // LP-975 — SO DOES ONE WHOSE PLAN SHE NEVER CONFIRMED (round 2 imported while round 1's plan waited).
  // Confirming this round puts its plan in force (`confirm_round_plan` stamps every condition on the
  // round), so it must be on the screen she confirms; and "keep their plan" would say she had approved
  // a plan she never saw.
  const blocking = new Set(data.blocking_codes);
  const onRound = late
    ? conditions.filter(
        (condition) =>
          !condition.plan_confirmed_at && confirmedRoundIds.has(condition.last_seen_round_id),
      )
    : conditions.filter((condition) => condition.last_seen_round_id === round.id);
  const shown = (condition: Condition) =>
    late ||
    condition.first_round_id === round.id ||
    !condition.plan_confirmed_at ||
    blocking.has(condition.lender_code ?? "");
  const rows = onRound.filter(shown).sort((a, b) => a.sequence - b.sequence);
  if (late && rows.length === 0) return null;
  // The rounds a late condition is on: confirming its plan is a confirm of each.
  const lateRoundIds = late ? [...new Set(rows.map((row) => row.last_seen_round_id))] : [];
  const notShown = onRound.filter((condition) => !shown(condition));
  const carried = notShown.length;
  // LP-973 REVIEW — the codes the drafts may name that have NO row on this screen. "Unlock the 2
  // drafted emails: to Title/attorney (1947, 0132)" is true of the server, which is what the ticket
  // judged, but 0132 is carried and not listed above, so she cannot click it or see what it asks. The
  // LP-966 review already settled that a code in a sentence should name a row she can reach, which is
  // why a BLOCKING carried condition stays; the drafts case was left, so it says so instead.
  const carriedCodes = new Set(
    notShown.map((condition) => condition.lender_code).filter((code): code is string => !!code),
  );
  const blocked = data.blocking_codes.length > 0;
  // WHICH BLOCKER THE SENTENCE NAMES (LP-976 review). `blocking_codes` carries an em dash for a
  // condition with no lender code, and "Confirm —'s reading first" is not a sentence she can act on —
  // the hand-added condition LP-976 is about has no code, so this is now a normal case rather than a
  // corner. A coded blocker is named wherever it sits in the list, which is unordered; only when none
  // has a code is the condition described instead. This is deliberately the same rule as the server's
  // `_refuse_for`, and the second copy of it: one is the refusal she gets if she presses confirm
  // anyway, the other is this line, and they must not say different things.
  const namedBlocker = data.blocking_codes.find((code) => code !== "—") ?? null;
  // LP-976 — after confirm, only the emails the added conditions are in: the round's other drafts were
  // unlocked by the first confirm.
  const rowCodes = new Set(rows.map((row) => row.lender_code).filter((code) => !!code));
  const drafts = late
    ? data.drafts.filter((draft) => draft.codes.some((code) => rowCodes.has(code)))
    : data.drafts;
  const emails = drafts.length;

  const onError = (error: unknown) => setRefusal(getErrorMessage(error));
  const changeItem = (condition: Condition, item: ConditionItem, to: PlanOption) => {
    setRefusal(null);
    updateItem.mutate({ conditionId: condition.id, itemId: item.id, option: to }, { onError });
  };
  // LP-968 — her edits to a task: Already done, Not needed, I'll do this myself (each with her words).
  const markItem = (
    condition: Condition,
    item: ConditionItem,
    change: { status?: "done" | "not_needed" | "open"; option?: PlanOption; note?: string },
  ) => {
    setRefusal(null);
    updateItem.mutate({ conditionId: condition.id, itemId: item.id, ...change }, { onError });
  };
  const changeStep = (condition: Condition, to: PlanOption) => {
    setRefusal(null);
    setNextStep.mutate({ conditionId: condition.id, next_step: to }, { onError });
  };
  // LP-969 — a step she adds: a task (`add_item`) or the condition's own question (`set_next_step`).
  // LP-971 REVIEW — ONE AT A TIME, AND EACH KNOWS WHAT WAS THERE BEFORE IT.
  // "Add these steps" presses this once per step. The dialog is opened by finding the item that was
  // not there before, and `before` came from the prop — so every add in a batch compared against the
  // SAME set and the first new item won, whichever step had asked for the dialog. A "Check a document"
  // step that was not first opened the link dialog on another step's task, and the document she picked
  // would have been linked to it (reproduced in "opens the link dialog on the step that asked for
  // it"). Firing them together was also N concurrent `resync_file` calls on one file, which nothing
  // serialises: two of them can each see no open draft for a recipient and make one.
  //
  // So the batch is a chain: the next add starts from the previous response, and the ids known after
  // it are threaded in as the next comparison. Exactly one item in each response is new, and it is
  // the one that step added. An error stops the chain — the refusal is shown and nothing after it is
  // added blindly.
  //
  // LP-971 follow-up — AND WHEN IT ENDS, SHE IS TOLD WHAT WENT IN (`PlanAdded`). The chain collects the
  // ids it added and the own step it set; at its end (or where an error stops it, so what DID go in is
  // still said) they become `justAdded`, which the row shows above "Add a step" and marks New in the
  // timeline until she presses Done. A logged call is not in it: it adds nothing to the plan and says
  // "Call logged" itself.
  const addSteps = (condition: Condition, steps: AddedStep[], leftOut: string[] = []) => {
    setRefusal(null);
    setJustAdded(null);
    const addedIds: string[] = [];
    let ownStep: PlanOption | null = null;
    const finish = () => {
      if (addedIds.length > 0 || ownStep !== null) {
        setJustAdded({ conditionId: condition.id, itemIds: addedIds, ownStep, leftOut });
      }
    };
    const stop = (error: unknown) => {
      onError(error);
      finish();
    };
    const run = (rest: AddedStep[], known: ReadonlySet<string>) => {
      const [step, ...tail] = rest;
      if (!step) {
        finish();
        return;
      }
      if (step.kind === "own_step") {
        ownStep = step.option;
        changeStep(condition, step.option);
        run(tail, known);
        return;
      }
      // LP-972 — A CALL IS A RECORD, NOT A TASK: it goes to the condition's history and adds nothing to
      // the plan, so she is told where it went rather than seeing nothing change.
      if (step.kind === "call") {
        logCall.mutate(
          { conditionId: condition.id, with_whom: step.with, on: step.on, agreed: step.agreed },
          {
            onError,
            onSuccess: () => {
              notifySuccess({
                title: "Call logged",
                consequence: `It’s in ${condition.lender_code ?? "the condition"}’s history.`,
              });
              run(tail, known);
            },
          },
        );
        return;
      }
      addItem.mutate(
        {
          conditionId: condition.id,
          name: step.name,
          performers: step.performers,
          option: step.option,
          ...(step.waiting ? { waiting: true, due_date: step.dueDate } : {}),
          ...(step.bringsDocument ? { brings_document: true } : {}),
        },
        {
          onError: stop,
          onSuccess: (updated) => {
            const added = updated.items.find((each) => !known.has(each.id));
            if (added) addedIds.push(added.id);
            if (step.link && added) setLinking({ condition: updated, item: added });
            run(tail, new Set(updated.items.map((each) => each.id)));
          },
        },
      );
    };
    run(steps, new Set(condition.items.map((each) => each.id)));
  };
  const addStep = (condition: Condition, step: AddedStep) => addSteps(condition, [step]);
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
            <span>
              {late ? "Added after you confirmed" : `Plan for round ${data.round_number ?? ""}`}
            </span>
            <span aria-hidden>·</span>
            <span>
              {rows.length} {carried > 0 ? "new " : ""}
              {rows.length === 1 ? "condition" : "conditions"}
              {late
                ? ""
                : ` · sheet dated ${usDate(data.round_date)} · ${data.nothing_sent ? "nothing sent yet" : "some emails were sent"}`}
            </span>
          </p>
          <h2 className="text-xl font-semibold text-foreground">
            {late
              ? `${rows.length} ${rows.length === 1 ? "condition was" : "conditions were"} added after you confirmed the plan`
              : rows.length === 0
                ? "Nothing new to plan on this sheet"
                : `Here’s how we’ll get ${rows.length === 1 ? "this condition" : `these ${rows.length} ${carried > 0 ? "new " : ""}conditions`} cleared`}
          </h2>
          {late ? (
            <p className="max-w-prose text-sm text-foreground-2">
              From a PDF you attached, an email you filed into the round, or one you added by hand.
              Check {rows.length === 1 ? "its" : "their"} plan, then confirm it. Until you do,{" "}
              {rows.length === 1 ? "its" : "their"} steps wait, and an email that includes{" "}
              {rows.length === 1 ? "it" : "them"} is not sent.
            </p>
          ) : rows.length > 0 ? (
            <p className="max-w-prose text-sm text-foreground-2">
              For each condition we worked out what it needs, prepared the emails we could, and laid
              out every step until the lender clears it. Check the plan, change a step if it’s
              wrong, then confirm. Nothing is sent until you do.
            </p>
          ) : null}
          {carried > 0 ? (
            <p className="max-w-prose text-sm text-foreground-2">
              <strong className="font-semibold text-foreground">
                {carried} {carried === 1 ? "condition" : "conditions"} from earlier rounds{" "}
                {carried === 1 ? "keeps its" : "keep their"} plan.
              </strong>{" "}
              You’ll see {carried === 1 ? "it" : "them"} in the list after you confirm.
            </p>
          ) : null}
        </div>
      </div>

      {/* THE CONFIRM BLOCK IS AT THE TOP (the owner, 2026-10-10: "put Plan confirmation button section on
          top"). What Confirm will do and the button sit under the heading, so she does not scroll past
          every condition to reach them; the conditions below are what she checks before pressing it. */}
      <div className="flex flex-col gap-3 rounded-[var(--radius-container)] bg-muted/50 p-4">
        <ConfirmSummary rows={rows} drafts={drafts} carriedCodes={carriedCodes} />
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            disabled={blocked || confirm.isPending}
            onClick={() => {
              setRefusal(null);
              setConfirmRefusal(null);
              // LP-976 — a confirm on a confirmed round confirms the plan of what was added to it.
              for (const roundId of late ? lateRoundIds : [round.id]) {
                confirm.mutate(
                  { roundId },
                  { onError: (error) => setConfirmRefusal(getErrorMessage(error)) },
                );
              }
            }}
          >
            <Check className="h-4 w-4" aria-hidden />
            {late ? `Confirm ${rows.length === 1 ? "its" : "their"} plan` : "Confirm the plan"}
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
              {namedBlocker !== null
                ? `Confirm ${namedBlocker}’s reading first — `
                : `Check how we read ${data.blocking_codes.length === 1 ? "it" : "them"} first — `}
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
        {confirmRefusal ? <p className="text-sm text-destructive">{confirmRefusal}</p> : null}
      </div>

      <FirstMovesBox rows={rows} drafts={drafts} />

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-foreground-2">
        <span className="font-semibold text-foreground">Who does each step:</span>
        {LEGEND.map(([who, label]) => (
          <span key={who} className="inline-flex items-center gap-1.5">
            <span aria-hidden className={cn("h-2.5 w-2.5 rounded-full", WHO_DOT[who])} />
            {label}
          </span>
        ))}
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
            onMarkItem={(item, change) => markItem(condition, item, change)}
            onRevert={() => {
              setRefusal(null);
              revert.mutate(condition.id, { onError });
            }}
            onOpenDraft={onOpenDraft}
            fileId={fileId}
            adding={addItem.isPending || setNextStep.isPending}
            onAddStep={(step) => addStep(condition, step)}
            onAddSteps={(steps, leftOut) => addSteps(condition, steps, leftOut)}
            justAdded={justAdded?.conditionId === condition.id ? justAdded : null}
            onDoneAdded={() => setJustAdded(null)}
            onOwnWay={() => {
              setRefusal(null);
              ownWay.mutate(condition.id, { onError });
            }}
            onRemoveItem={(item) => {
              setRefusal(null);
              removeItem.mutate({ conditionId: condition.id, itemId: item.id }, { onError });
            }}
            onChangeStep={(to) => changeStep(condition, to)}
            onHelp={(title, current) => setHelp({ title, current })}
            lenderName={fileLender.data?.lender?.name ?? null}
            onChooseRoute={(routeKey) => {
              setRefusal(null);
              chooseRoute.mutate({ conditionId: condition.id, route: routeKey }, { onError });
            }}
          />
        ))}
      </div>

      {refusal ? <p className="text-sm text-destructive">{refusal}</p> : null}

      <StepGuide help={help} onClose={() => setHelp(null)} />
      {linking ? (
        <LinkDocumentDialog
          open
          onOpenChange={(next) => {
            if (!next) setLinking(null);
          }}
          fileId={fileId}
          condition={linking.condition}
          item={linking.item}
          onDone={() => setLinking(null)}
        />
      ) : null}
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

/** The items still on the plan. */
function live(condition: Condition): ConditionItem[] {
  return condition.items.filter((item) => item.status !== "not_needed");
}

/**
 * LP-974 — the collapsed row's "Route:", until LP-970 brings real routes: what the condition's own
 * step, or else each live task's step, says will happen. Read through `actionFor`, the same phrase the
 * select's change produces, so it cannot disagree with the selects below it.
 */
function routeOf(condition: Condition): string | null {
  // LP-970 — the chosen route by name, "(suggested)" when it is the one the lender's settings point to.
  const chosen = condition.routes?.find((route) => route.key === condition.chosen_route);
  if (chosen) return `${chosen.label}${chosen.suggested ? " (suggested)" : ""}`;
  if (condition.next_step) return actionFor(condition.next_step, null);
  const phrases: string[] = [];
  for (const item of live(condition)) {
    const phrase = actionFor(item.option, item);
    if (!phrases.includes(phrase)) phrases.push(phrase);
  }
  if (phrases.length > 0) return phrases.join(" · ");
  // Every task dropped: say so, or the collapsed row reads as though nothing was ever worked out.
  return condition.items.length > 0 ? "Nothing left: you marked every task not needed" : null;
}

function PlanRow({
  condition,
  lenderName,
  onChooseRoute,
  open,
  onToggle,
  onOpenCondition,
  onConfirmReading,
  onChangeItem,
  onMarkItem,
  onRevert,
  onOpenDraft,
  fileId,
  adding,
  onAddStep,
  onAddSteps,
  justAdded,
  onDoneAdded,
  onOwnWay,
  onRemoveItem,
  onChangeStep,
  onHelp,
}: {
  condition: Condition;
  open: boolean;
  onToggle: () => void;
  onOpenCondition: () => void;
  onConfirmReading: () => void;
  onChangeItem: (item: ConditionItem, to: PlanOption) => void;
  onMarkItem: (item: ConditionItem, change: ItemMark) => void;
  onRevert: () => void;
  onOpenDraft?: (draftId: string) => void;
  fileId: string;
  adding: boolean;
  onAddStep: (step: AddedStep) => void;
  /** LP-971 review — a whole proposal, so the adds can be chained rather than fired together. */
  onAddSteps: (steps: AddedStep[], leftOut?: string[]) => void;
  /** LP-971 follow-up — what she just added to this condition, until she presses Done. */
  justAdded: JustAdded | null;
  onDoneAdded: () => void;
  onOwnWay: () => void;
  onRemoveItem: (item: ConditionItem) => void;
  onChangeStep: (to: PlanOption) => void;
  onHelp: (title: string, current: PlanOption) => void;
  /** LP-979 — the file's lender by name, so the plan's ending says who clears it ("UWM clears 1228"). */
  lenderName: string | null;
  /** LP-970 — she picks one of the condition's routes; the server rebuilds the path. */
  onChooseRoute: (routeKey: string) => void;
}) {
  const detailsId = useId();
  const items = live(condition);
  const needsHer = condition.reading_status === "needs_confirmation";
  const code = condition.lender_code ?? "—";
  const title = condition.reading?.summary ?? condition.verbatim_text;
  const ownStep = condition.next_step;
  // Nothing worked out: no task and no step of its own (the reading failed or found nothing to ask).
  // ANY task counts, a dropped one too (LP-974): a condition whose only task she marked not needed was
  // worked out, and calling it unread hid the crossed-out task with her reason and its Undo.
  const unworked = condition.items.length === 0 && ownStep === null;
  const entries = conditionPath(condition, { needsConfirmation: needsHer, lenderName });
  const route = routeOf(condition);
  const next = nextOf(entries);
  // A task's name over its first step only when there is more than one thing on the timeline to tell
  // apart; on a one-task condition the name would repeat the condition's title.
  const named = condition.items.length + (ownStep ? 1 : 0) > 1;

  return (
    <div className={cn("border-b border-border last:border-b-0", needsHer && "bg-warning/5")}>
      <div className="flex flex-wrap items-start gap-x-5 gap-y-3 px-4 py-4">
        <div className="flex min-w-0 flex-[999_1_32rem] flex-col gap-1.5">
          <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
            <button
              type="button"
              onClick={onOpenCondition}
              className="font-mono text-sm font-medium text-foreground hover:underline"
            >
              {code}
            </button>
            <span className="text-base font-semibold text-foreground">{title}</span>
            <span className="rounded-md border border-border px-1.5 py-0.5 text-xs text-foreground-2">
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
          {route ? (
            <p className="text-sm text-foreground-2">
              <strong className="font-semibold text-primary">Route:</strong> {route}
            </p>
          ) : null}
          {next ? (
            <p className="text-sm text-foreground-2">
              <strong className="font-semibold text-foreground">Next:</strong> {next.text}
            </p>
          ) : null}
          {unworked ? (
            <Unworked
              canCheckReading={condition.reading !== null}
              onConfirmReading={onConfirmReading}
            />
          ) : null}
        </div>
        <div className="flex flex-[1_1_10rem] justify-end">
          <Button
            type="button"
            variant="outline"
            aria-expanded={open}
            aria-controls={detailsId}
            onClick={onToggle}
          >
            {open ? (
              <ChevronUp className="h-4 w-4" aria-hidden />
            ) : (
              <ChevronDown className="h-4 w-4" aria-hidden />
            )}
            {open ? "Hide the plan" : "See the plan"}
          </Button>
        </div>
      </div>

      {open ? (
        <div id={detailsId} className="mx-4 mb-4 grid items-start gap-x-6 gap-y-5 md:grid-cols-2">
          <div className="flex flex-col gap-4 rounded-[var(--radius-container)] border border-border bg-muted/40 p-4">
            <Detail heading="What the lender wants">
              {condition.reading?.explanation ?? title}
            </Detail>
            <Detail heading="When it’s needed">
              <strong className="font-semibold">{BUCKET_KIND_CHIP[condition.bucket_kind]}</strong> —{" "}
              {BUCKET_KIND_MEANING[condition.bucket_kind]}
            </Detail>
            {unworked ? null : (
              <div className="flex flex-col gap-2">
                <p className="text-xs font-semibold uppercase tracking-wide text-foreground-2">
                  How it gets done
                </p>
                {condition.routes && condition.routes.length > 0 ? (
                  <RouteChoices condition={condition} onChoose={onChooseRoute} />
                ) : null}
                {condition.routes && condition.routes.length > 0 ? (
                  <details className="text-sm">
                    <summary className="cursor-pointer text-xs font-medium text-primary">
                      Change each task’s step yourself
                    </summary>
                    <div className="mt-2 flex flex-col gap-2">
                      {ownStep ? (
                        <HowRow
                          name="The whole condition"
                          option={ownStep}
                          item={null}
                          onChange={onChangeStep}
                          onHelp={() => onHelp(`the whole condition (${code})`, ownStep)}
                        />
                      ) : null}
                      {items.map((item) => (
                        <HowRow
                          key={item.id}
                          name={item.name}
                          option={item.option}
                          item={item}
                          onChange={(to) => onChangeItem(item, to)}
                          onHelp={() => onHelp(`${item.name} (${code})`, item.option)}
                        />
                      ))}
                    </div>
                  </details>
                ) : (
                  <>
                    {ownStep ? (
                      <HowRow
                        name="The whole condition"
                        option={ownStep}
                        item={null}
                        onChange={onChangeStep}
                        onHelp={() => onHelp(`the whole condition (${code})`, ownStep)}
                      />
                    ) : null}
                    {items.map((item) => (
                      <HowRow
                        key={item.id}
                        name={item.name}
                        option={item.option}
                        item={item}
                        onChange={(to) => onChangeItem(item, to)}
                        onHelp={() => onHelp(`${item.name} (${code})`, item.option)}
                      />
                    ))}
                  </>
                )}
                {condition.plan_reason ? (
                  <p className="text-sm text-foreground-2">
                    <strong className="font-semibold text-foreground">Why we suggest this:</strong>{" "}
                    {condition.plan_reason}
                  </p>
                ) : null}
                {/* LP-969 — the last route on every condition. Only while there is a suggestion left
                    to clear: an OPEN task or a step of its own. */}
                {ownStep !== null || condition.items.some((each) => each.status === "open") ? (
                  <div className="flex flex-col gap-1 rounded-[var(--radius-container)] border border-dashed border-border px-3 py-2.5">
                    <button
                      type="button"
                      onClick={onOwnWay}
                      className="self-start text-sm font-semibold text-primary underline-offset-2 hover:underline"
                    >
                      I’ll handle it my own way
                    </button>
                    <span className="text-xs text-foreground-2">
                      We take the suggested steps off, and you add your own. “Go back to the
                      suggested plan” puts them back.
                    </span>
                  </div>
                ) : null}
              </div>
            )}
            <Detail heading="The lender’s exact words">
              <span className="font-serif text-foreground-2">{condition.verbatim_text}</span>
            </Detail>
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

          <div className="flex flex-col">
            <div className="mb-2.5 flex flex-wrap items-baseline justify-between gap-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-foreground-2">
                The plan, step by step
              </p>
              {/* LP-968 — her changes undone, replayed from the history (`revert_to_suggested`).
                  LP-979 — ONLY ONCE SHE HAS CHANGED SOMETHING, as in the agreed mockup ("Changed by you ·
                  Go back to the suggested plan"). On a plan as suggested the link had nothing to undo. */}
              {condition.plan_changed ? (
                <span className="text-xs text-foreground-2">
                  Changed by you ·{" "}
                  <button
                    type="button"
                    onClick={onRevert}
                    className="font-medium text-primary underline-offset-2 hover:underline"
                  >
                    Go back to the suggested plan
                  </button>
                </span>
              ) : null}
            </div>
            {unworked ? (
              <div className="mb-3">
                <Unworked
                  canCheckReading={condition.reading !== null}
                  onConfirmReading={onConfirmReading}
                />
              </div>
            ) : null}
            {ownStep === null && items.length === 0 ? (
              <div className="mb-3 flex flex-col gap-1 rounded-[var(--radius-container)] border border-dashed border-primary/40 px-3.5 py-3">
                <span className="text-sm font-semibold text-foreground">Build your own path</span>
                <span className="text-sm text-foreground-2">
                  Add the steps you’ll take with “Add a step”. We still put each ask in that
                  person’s email, and check the documents you upload or link.
                </span>
              </div>
            ) : null}
            {entries.length > 0 ? (
              <Timeline
                fileId={fileId}
                condition={condition}
                entries={entries}
                fresh={justAdded?.itemIds ?? []}
                named={named}
                onOpenDraft={onOpenDraft}
                onMarkItem={onMarkItem}
                onRemoveItem={onRemoveItem}
              />
            ) : null}
            {justAdded ? (
              <PlanAdded
                code={code}
                places={addedPlaces(entries, justAdded.itemIds)}
                ownStep={justAdded.ownStep}
                leftOut={justAdded.leftOut}
                onDone={onDoneAdded}
              />
            ) : null}
            <AddStep
              conditionId={condition.id}
              ownStep={ownStep}
              pending={adding}
              onAdd={onAddStep}
              onAddAll={onAddSteps}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}

/**
 * A row the reading worked nothing out for. LP-966 stopped filtering these away, which is right — a
 * condition nobody can see is worse than one that says it is stuck.
 *
 * THE BUTTON IS ONLY THERE WHEN THERE IS A READING TO CHECK (LP-966 review). `ConfirmReadingDialog`
 * opens on `condition.reading` and returns null without one, so on a condition that was never read —
 * the likeliest reason a row has no items and no step at all — "Check how we read it" opened nothing.
 * A dead control on the one row whose purpose is to say what to do next is worse than no control.
 */
function Unworked({
  canCheckReading,
  onConfirmReading,
}: {
  canCheckReading: boolean;
  onConfirmReading: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm text-foreground-2">
      <span>
        {canCheckReading
          ? "We couldn’t work out what this one needs."
          : "We haven’t read this one yet, so there is nothing to plan for it."}
      </span>
      {canCheckReading ? (
        <Button type="button" variant="outline" size="sm" onClick={onConfirmReading}>
          Check how we read it
        </Button>
      ) : null}
    </div>
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

/**
 * LP-970 — "How it gets done": the condition's routes as choices, the suggested one marked with its
 * reason, as in the agreed mockup. The chosen one is the server's (`chosen_route`, read from the
 * condition's step and tasks), so a choice shows as made only once the rebuilt path has come back.
 */
function RouteChoices({
  condition,
  onChoose,
}: {
  condition: Condition;
  onChoose: (routeKey: string) => void;
}) {
  const name = useId();
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="sr-only">How {condition.lender_code ?? "this condition"} gets done</legend>
      {(condition.routes ?? []).map((route) => {
        const chosen = condition.chosen_route === route.key;
        return (
          <label
            key={route.key}
            className={cn(
              "flex cursor-pointer gap-2.5 rounded-[var(--radius-container)] border bg-card px-3 py-2.5",
              chosen ? "border-primary" : "border-border",
            )}
          >
            <input
              type="radio"
              name={name}
              checked={chosen}
              onChange={() => onChoose(route.key)}
              className="mt-1 accent-primary"
            />
            <span className="flex flex-col gap-0.5">
              <span className="flex flex-wrap items-baseline gap-2">
                <span className="text-sm font-semibold text-foreground">{route.label}</span>
                {route.suggested ? (
                  <span className="rounded-md bg-ai px-1.5 py-px text-[11px] font-semibold text-ai-foreground">
                    Suggested
                  </span>
                ) : null}
              </span>
              <span className="text-xs text-foreground-2">{route.hint}</span>
              {route.suggested && route.why ? (
                <span className="text-xs text-foreground-2">{route.why}</span>
              ) : null}
            </span>
          </label>
        );
      })}
    </fieldset>
  );
}

/**
 * One line of "How it gets done": a task's Next step select, its ⓘ, and what the step means. Until
 * LP-970's routes, this is how she changes how a task gets done, and the timeline follows at once.
 */
function HowRow({
  name,
  option,
  item,
  onChange,
  onHelp,
}: {
  name: string;
  option: PlanOption;
  item: ConditionItem | null;
  onChange: (to: PlanOption) => void;
  onHelp: () => void;
}) {
  const selectId = useId();
  const nameId = useId();
  const labelId = useId();
  return (
    <div className="flex flex-col gap-1.5 rounded-[var(--radius-container)] border border-border bg-card px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span id={nameId} className="text-sm font-semibold text-foreground">
          {name}
        </span>
        <label id={labelId} htmlFor={selectId} className="text-xs text-foreground-2">
          Next step
        </label>
        {/* THE TASK'S NAME IS PART OF THE SELECT'S NAME (LP-974 review). The visible label is "Next
            step" on every row, so a screen reader announced four identical combo boxes with the task
            name in an unassociated span beside each — nothing tied them. `aria-labelledby` over both
            makes the name "Credit report invoice Next step" while the visible label and its `htmlFor`
            stay as they are. */}
        <select
          id={selectId}
          aria-labelledby={`${nameId} ${labelId}`}
          value={option}
          onChange={(event) => onChange(event.target.value as PlanOption)}
          className="h-8 w-auto rounded-md border border-primary/40 bg-card px-1.5 text-sm font-medium text-primary"
        >
          {/* A TASK IS OFFERED FEWER (LP-966 review): the two questions are the whole
              condition's, and an item set to one belongs to no email. See `ITEM_OPTION_ORDER`.
              A TASK ALREADY HOLDING ONE STILL LISTS IT, or the select would render blank against a
              value not in its options and hide what the item actually is — she can move it off,
              but nothing new lands on it. */}
          {(item === null
            ? OPTION_ORDER
            : ITEM_OPTION_ORDER.includes(option)
              ? ITEM_OPTION_ORDER
              : [option, ...ITEM_OPTION_ORDER]
          ).map((each) => (
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
      <p className="text-xs text-foreground-2">{meaningFor(option, item)}</p>
    </div>
  );
}

/** LP-968 — what she can change on a task, and what each change asks her for. */
export type ItemMark = {
  status?: "done" | "not_needed" | "open";
  option?: PlanOption;
  note?: string;
};

const ASK_OPTIONS: readonly PlanOption[] = ["ask_borrower", "ask_third_party"];

/**
 * LP-968 — Already done / Not needed / I'll do this myself, each opening one line for her words.
 *
 * WHAT EACH ASKS FOR IS THE SERVER'S RULE (`condition_plan.update_item`): "Not needed" needs a reason;
 * "Already done" on someone else's task needs a note (or a linked document); "I'll do this myself" takes
 * an optional note on how. The button stays disabled until a required reason is typed, so the refusal
 * is the server's backstop rather than her first sight of the rule.
 */
function TaskEdits({ item, onMark }: { item: ConditionItem; onMark: (change: ItemMark) => void }) {
  const [mode, setMode] = useState<"done" | "not_needed" | "myself" | null>(null);
  const [words, setWords] = useState("");
  const inputId = useId();
  if (item.status === "done") {
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-foreground-2">
        <span>
          <strong className="font-semibold text-foreground">Already done</strong>
          {item.plan_note ? `: ${item.plan_note}` : ""}
        </span>
        <button
          type="button"
          onClick={() => onMark({ status: "open" })}
          className="font-medium text-primary underline-offset-2 hover:underline"
        >
          Undo
        </button>
      </div>
    );
  }
  if (item.status === "not_needed") {
    return (
      <button
        type="button"
        onClick={() => onMark({ status: "open" })}
        className="self-start text-xs font-medium text-primary underline-offset-2 hover:underline"
      >
        Undo
      </button>
    );
  }
  if (item.status !== "open") return null; // asked or answered: its record stands
  const theirs = item.option !== "i_will_do_it";
  const required = mode === "not_needed" || (mode === "done" && theirs);
  const prompt =
    mode === "not_needed"
      ? "Why isn’t it needed?"
      : mode === "done"
        ? theirs
          ? "How do you know it’s done?"
          : "Note (optional)"
        : "How are you doing it? (optional)";
  const placeholder =
    mode === "not_needed"
      ? "e.g. no new fee was charged"
      : mode === "done"
        ? "e.g. received on 09/12 by email"
        : "e.g. calling the LO this afternoon";
  const save = () => {
    const note = words.trim() || undefined;
    if (mode === "myself") onMark({ option: "i_will_do_it", note });
    else if (mode) onMark({ status: mode, note });
    setMode(null);
    setWords("");
  };
  if (mode === null) {
    return (
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {ASK_OPTIONS.includes(item.option) ? (
          <button
            type="button"
            onClick={() => setMode("myself")}
            className="text-xs font-medium text-primary underline-offset-2 hover:underline"
          >
            I’ll do this step myself
          </button>
        ) : null}
        <button
          type="button"
          onClick={() => setMode("done")}
          className="text-xs font-medium text-primary underline-offset-2 hover:underline"
        >
          Already done
        </button>
        <button
          type="button"
          onClick={() => setMode("not_needed")}
          className="text-xs font-medium text-primary underline-offset-2 hover:underline"
        >
          Not needed
        </button>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1.5 rounded-md border border-border bg-muted/40 p-2.5">
      <label htmlFor={inputId} className="text-xs font-medium text-foreground-2">
        {prompt}
      </label>
      <input
        id={inputId}
        type="text"
        value={words}
        maxLength={300}
        placeholder={placeholder}
        onChange={(event) => setWords(event.target.value)}
        className="h-8 rounded-md border border-input bg-card px-2 text-sm text-foreground"
      />
      <div className="flex gap-2">
        <Button type="button" size="sm" disabled={required && !words.trim()} onClick={save}>
          {mode === "myself" ? "I’ll do it" : mode === "done" ? "Mark done" : "Mark not needed"}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => {
            setMode(null);
            setWords("");
          }}
        >
          Cancel
        </Button>
      </div>
    </div>
  );
}

/** LP-967 — the colour of each kind of step, and the legend that names them. */
const WHO_DOT: Record<PathWho, string> = {
  we: "bg-ai text-ai-foreground",
  you: "bg-primary text-primary-foreground",
  them: "bg-warning text-warning-foreground",
  lender: "bg-muted-foreground text-card",
};
const WHO_TEXT: Record<PathWho, string> = {
  we: "text-ai",
  you: "text-primary",
  them: "text-warning",
  lender: "text-muted-foreground",
};
const LEGEND: [PathWho, string][] = [
  ["we", "We prepare or check it"],
  ["you", "You"],
  ["them", "Someone else, we wait"],
  ["lender", "The lender"],
];

/** The badge beside a task's first step: what has happened to it, else its name (`named`). */
function badgeFor(entry: PlanEntry, named: boolean): string | null {
  const item = entry.item;
  if (!item || !entry.leads) return null;
  if (item.status === "not_needed") return "Not needed";
  if (item.status === "done" && item.option !== "already_in_file") return "Done";
  if (item.origin === "manual") return named ? `${item.name} · added by you` : "Added by you";
  return named ? item.name : null;
}

/**
 * LP-974 — the condition's plan as ONE numbered timeline (the mockup): a numbered dot per step,
 * coloured by who does it, joined by a line; the who-label over each step, never the colour alone.
 * Her edits sit on each task's first step — the server keeps them per task, so a step deeper in the
 * same task offers nothing a different button could do.
 */
function Timeline({
  fileId,
  condition,
  entries,
  fresh,
  named,
  onOpenDraft,
  onMarkItem,
  onRemoveItem,
}: {
  fileId: string;
  condition: Condition;
  entries: PlanEntry[];
  /** LP-971 follow-up — the tasks she just added: their steps are marked New. */
  fresh: readonly string[];
  named: boolean;
  onOpenDraft?: (draftId: string) => void;
  onMarkItem: (item: ConditionItem, change: ItemMark) => void;
  onRemoveItem: (item: ConditionItem) => void;
}) {
  return (
    <ol aria-label="The plan, step by step" className="flex flex-col">
      {entries.map((entry, index) => {
        const { step, item } = entry;
        const dropped = item?.status === "not_needed";
        const finished = item?.status === "done" && item.option !== "already_in_file";
        const badge = badgeFor(entry, named);
        const isNew = item !== null && fresh.includes(item.id);
        return (
          <li
            key={`${index}-${item?.id ?? "c"}-${step.text}`}
            id={item && entry.leads ? planStepAnchor(item.id) : undefined}
            className={cn(
              "flex scroll-mt-4 gap-3",
              isNew && "-mx-2 rounded-[var(--radius-container)] bg-primary/5 px-2 pt-1.5",
            )}
          >
            <div className="flex w-7 shrink-0 flex-col items-center">
              <span
                aria-hidden
                className={cn(
                  "flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full text-xs font-semibold",
                  dropped || finished ? "bg-muted-foreground/60 text-card" : WHO_DOT[step.who],
                )}
              >
                {index + 1}
              </span>
              {index < entries.length - 1 ? (
                <span aria-hidden className="min-h-3.5 w-0.5 flex-1 bg-border" />
              ) : null}
            </div>
            <div className="flex min-w-0 flex-1 flex-col gap-1 pb-3.5">
              <div className="flex flex-wrap items-baseline gap-2">
                <span
                  className={cn(
                    "text-xs font-semibold uppercase tracking-wide",
                    dropped ? "text-muted-foreground" : WHO_TEXT[step.who],
                  )}
                >
                  {dropped ? "You" : step.whoLabel}
                </span>
                {isNew ? (
                  <span className="rounded-full bg-primary px-1.5 py-px text-[11px] font-semibold text-primary-foreground">
                    New
                  </span>
                ) : null}
                {badge ? (
                  <span className="rounded-md bg-muted px-1.5 py-px text-[11px] font-semibold text-foreground-2">
                    {badge}
                  </span>
                ) : null}
              </div>
              <span
                className={cn(
                  "text-[15px] font-medium leading-snug",
                  dropped ? "text-muted-foreground line-through" : "text-foreground",
                )}
              >
                {step.text}
              </span>
              {step.detail ? (
                <span className="text-[13px] leading-normal text-foreground-2">
                  {dropped ? `Why: ${step.detail}` : step.detail}
                </span>
              ) : null}
              {step.draftId && onOpenDraft ? (
                <Button
                  type="button"
                  size="sm"
                  className="mt-1 self-start"
                  onClick={() => onOpenDraft(step.draftId as string)}
                >
                  Review draft
                </Button>
              ) : null}
              {item && entry.leads && item.plan_note && item.status !== "done" && !dropped ? (
                <span className="text-xs text-foreground-2">
                  <strong className="font-semibold text-foreground">Your note:</strong>{" "}
                  {item.plan_note}
                </span>
              ) : null}
              {/* LP-969 — HER OWN TASK, OPEN: upload to it or link a document here, which is what
                  its "Upload what you get to this task" step asks; the checks run on either. */}
              {item && entry.leads && item.option === "i_will_do_it" && item.status === "open" ? (
                <div className="mt-1">
                  <ItemLinkActions fileId={fileId} condition={condition} item={item} />
                </div>
              ) : null}
              {item && entry.leads ? (
                <div className="flex flex-wrap items-start gap-x-4 gap-y-1">
                  <TaskEdits item={item} onMark={(change) => onMarkItem(item, change)} />
                  {/* A STEP SHE ADDED CAN GO (S3-01's remove, a soft delete). One the reading
                      suggested cannot: Not needed keeps it, with her reason (LP-968). */}
                  {item.origin === "manual" && item.status === "open" ? (
                    <button
                      type="button"
                      onClick={() => onRemoveItem(item)}
                      className="text-xs font-medium text-destructive underline-offset-2 hover:underline"
                    >
                      Remove step
                    </button>
                  ) : null}
                </div>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** LP-967 — "Your first moves": what she does first across the round, then who it waits on. */
function FirstMovesBox({ rows, drafts }: { rows: Condition[]; drafts: { codes: string[] }[] }) {
  const moves = firstMoves(rows, drafts);
  const doNow: string[] = [];
  if (moves.emails > 0) {
    // LP-968 — they are drafted already: review them now, send each once the plan is confirmed.
    doNow.push(`review the ${moves.emails} drafted ${moves.emails === 1 ? "email" : "emails"}`);
  }
  if (moves.tasksNow > 0) {
    doNow.push(`do ${moves.tasksNow} ${moves.tasksNow === 1 ? "task" : "tasks"} yourself`);
  }
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <div className="flex flex-col gap-1 rounded-[var(--radius-container)] bg-primary px-4 py-3 text-primary-foreground">
        <span className="text-xs font-semibold uppercase tracking-wide opacity-85">
          Your first moves
        </span>
        <span className="text-sm">
          {doNow.length > 0
            ? `${capitalise(doNow.join(", then "))}${moves.tasksLater > 0 ? `. ${moves.tasksLater} more ${moves.tasksLater === 1 ? "task waits" : "tasks wait"} on another condition.` : "."}`
            : "Nothing to send or do yet."}
        </span>
      </div>
      <div className="flex flex-col gap-1 rounded-[var(--radius-container)] bg-muted/50 px-4 py-3">
        <span className="text-xs font-semibold uppercase tracking-wide text-foreground-2">
          Then we wait on
        </span>
        <span className="text-sm text-foreground">
          {moves.waitingOn.length > 0
            ? `${capitalise(moves.waitingOn.join(", "))}.`
            : "Nobody yet."}
        </span>
      </div>
      <div className="flex flex-col gap-1 rounded-[var(--radius-container)] bg-muted/50 px-4 py-3">
        <span className="text-xs font-semibold uppercase tracking-wide text-foreground-2">
          Already handled
        </span>
        <span className="text-sm text-foreground">
          {moves.handled.length > 0 ? `${moves.handled.join(", ")}.` : "Nothing yet."}
        </span>
      </div>
    </div>
  );
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** "When you confirm, we will:", from the plan's own drafts and the rows' steps. */
function ConfirmSummary({
  rows,
  drafts,
  carriedCodes,
}: {
  rows: Condition[];
  drafts: { label: string; codes: string[] }[];
  /** Codes on this round that have no row above: named in a draft, they would be unfindable. */
  carriedCodes?: Set<string>;
}) {
  const ready: string[] = [];
  const tasks: string[] = [];
  const questions: string[] = [];
  const lenders: string[] = [];
  for (const condition of rows) {
    const code = condition.lender_code ?? "—";
    const items = live(condition);
    if (willBeReady(condition, items)) ready.push(code);
    if (condition.next_step === "ask_underwriter" || condition.next_step === "push_back") {
      questions.push(code);
    }
    if (condition.next_step === "lender_doing_it") lenders.push(code);
    for (const item of items) {
      // LP-972 REVIEW — AND NOT A WAIT. "Add 3 tasks to your list" counted a wait as one of them, so
      // the sentence promised to give her work that is someone else's; the ticket's own first moves
      // name who is waited on instead of counting a task. Excluded rather than re-worded here,
      // because what this line says is what Confirm will do.
      if (item.option !== "i_will_do_it" || item.waiting) continue;
      const what = item.task ?? item.name.toLowerCase();
      tasks.push(`${what} (${code}${item.waits_on_code ? `, after ${item.waits_on_code}` : ""})`);
    }
  }
  const lines: React.ReactNode[] = [];
  if (drafts.length > 0) {
    const named = [...new Set(drafts.flatMap((draft) => draft.codes))].filter((code) =>
      carriedCodes?.has(code),
    );
    lines.push(
      <li key="emails">
        <strong className="font-semibold">
          Unlock the {drafts.length} drafted {drafts.length === 1 ? "email" : "emails"} for sending
        </strong>
        : {drafts.map((draft) => `to ${draft.label} (${draft.codes.join(", ")})`).join("; ")}. Until
        then nothing can be sent; you can review and edit each one now.
        {named.length > 0
          ? ` ${named.join(", ")} ${named.length === 1 ? "is" : "are"} from an earlier round, so ${named.length === 1 ? "it is" : "they are"} not listed above.`
          : ""}
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

/** LP-971 follow-up — what one add (or one proposal's adds) put on a condition's plan. */
interface JustAdded {
  conditionId: string;
  itemIds: string[];
  ownStep: PlanOption | null;
  leftOut: string[];
}
