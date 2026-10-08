/**
 * LP-967 — a condition's plan as a PATH: every step from now until the lender clears it, and who does
 * each one. The owner, 2026-10-08: "we will create a draft you send it to whoever (we suggest) and all
 * steps after wards. This is called a plan." The design is the "The plan as a path" board of the
 * "Plan screen explained" artifact.
 *
 * BUILT ONLY FROM WHAT THE SERVER DOES TODAY. LP-967 adds no behaviour, so every step here must
 * already be true. The facts each step leans on:
 * - an ask becomes a draft to its recipient WHEN THE PLAN IS CONFIRMED (`condition_drafts.
 *   sync_round_drafts`, from `confirm_round_plan`), grouped by recipient (`recipient_for`);
 * - marking a draft sent moves the condition to Waiting on that person (LP-922, `mark_sent`);
 * - a reply's attachment is accepted onto the file by her (`inbound_triage`, LP-806); nothing is
 *   filed by itself;
 * - she links a document to a task, and the app suggests matches (`condition_links.link_candidates`,
 *   LP-958);
 * - a linked document's checks run (`condition_evidence`, LP-953's `check_link`);
 * - a condition is Ready when every live task is done (`condition_plan.ready_because`), and a Ready,
 *   open condition goes in the lender package (`condition_package._goes_in`);
 * - push back and ask the underwriter are drafts to the underwriter, read from the CONDITION's step
 *   only (`condition_drafts._QUESTIONS`; LP-966 review);
 * - she records the lender's answer (LP-958's Record).
 * If one of these changes, the step that leans on it is false: change both together.
 */
import { emailWord, recipient } from "@/lib/conditions/next-step";
import { PERFORMER_LABEL } from "@/lib/conditions/plan-words";
import type { Condition, ConditionItem, PlanOption } from "@/lib/types/conditions";

/** Who does a step: the app, the processor, someone the app waits on, or the lender. */
export type PathWho = "we" | "you" | "them" | "lender";

export interface PathStep {
  who: PathWho;
  /** The label over the step: "We", "You", "Title / escrow", "The lender". */
  whoLabel: string;
  text: string;
  detail?: string;
  /** LP-968 — the prepared draft this step is about, so the step can open it. */
  draftId?: string;
}

/**
 * A MIRROR OF `condition_plan.ready_because`, branch for branch (LP-966 review).
 *
 * This read "every live item's OPTION is already_in_file", and the server reads every live item's
 * STATUS, which is a different thing in both directions. A document she links by hand is RECEIVED and
 * only becomes DONE when `check_link` passes it (LP-953), so a condition whose items are all
 * "Already in the file" with one document still being read was promised "ready to send" and did not
 * become ready. And a condition whose tasks she had already marked done was left out of the promise
 * even though the server would move it, because no item's option was `already_in_file`.
 *
 * Keyed on status, so the sentence says what confirm will do. The server returns WHICH step made it
 * ready; the screen only needs whether, so this returns a boolean.
 *
 * IT LIVES HERE, EXPORTED, BECAUSE ONE COPY WAS NOT ENOUGH (LP-967 review). The LP-966 review fixed
 * the confirm summary and left this rule module-private in the panel, so LP-967 wrote a second copy
 * keyed on the OPTION again for the "Already in the file" box — and the two boxes on one screen
 * could then disagree about the same condition. Anything asking "will confirm make this ready?"
 * asks here.
 */
export function willBeReady(condition: Condition, live: ConditionItem[]): boolean {
  if (condition.next_step === "already_in_file") return true;
  // A condition-level ask, question or push-back is owed until its send moves it; display-only never
  // moves. Only "no step of its own" or "I'll do it" can be settled by the items.
  if (condition.next_step !== null && condition.next_step !== "i_will_do_it") return false;
  if (live.length === 0) return false;
  return live.every((item) => item.status === "done");
}

/** The items still on the plan. */
export function liveItems(condition: Condition): ConditionItem[] {
  return condition.items.filter((item) => item.status !== "not_needed");
}

/** Who an ask goes to, by name. */
export function askedWho(item: ConditionItem): string {
  const who = recipient(item);
  if (who === "borrower") return "the borrower";
  if (who === "lo") return "the LO";
  if (who === "appraiser") return "the lender";
  return PERFORMER_LABEL[who];
}

function capital(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

const WE = (text: string, detail?: string): PathStep => ({
  who: "we",
  whoLabel: "We",
  text,
  detail,
});
const YOU = (text: string, detail?: string): PathStep => ({
  who: "you",
  whoLabel: "You",
  text,
  detail,
});
const LENDER = (text: string, detail?: string): PathStep => ({
  who: "lender",
  whoLabel: "The lender",
  text,
  detail,
});

/** What a document for this task should be, when the library says (not the generic placeholder). */
function shouldBe(item: ConditionItem): string | undefined {
  return item.generic || !item.acceptable ? undefined : `It should be: ${item.acceptable}.`;
}

/** A task with nothing left on it: the path from HERE is empty, and an empty card says nothing. */
const FINISHED: PathStep = {
  who: "we",
  whoLabel: "Done",
  text: "This task is done — nothing left on it",
};

/**
 * How many of a task's own steps have ALREADY HAPPENED, from its status (LP-967 review).
 *
 * The path is "every step from now until the lender clears it", and it began at "We draft the email"
 * however far along the task was — so a task whose ask had gone out, or whose document was already
 * linked, described work that was behind her as though it were ahead. The statuses map onto the steps:
 * `requested` means the ask went (`mark_sent`), `received` means a document is linked but has not
 * passed its checks (a hand link is RECEIVED until `check_link`, LP-953), `done` means finished.
 *
 * "Already in the file" is NOT trimmed: `build_plan` sets that option and `DONE` together, so trimming
 * on `done` would empty the one card she most wants to read ("We found X on the file").
 */
function alreadyBehind(item: ConditionItem): number {
  if (item.option === "ask_borrower" || item.option === "ask_third_party") {
    if (item.status === "requested") return 2; // the draft and the send
    if (item.status === "received") return 4; // …and it came back, and it is linked
  }
  if (item.option === "i_will_do_it" && item.status === "received") return 2;
  return 0;
}

const TRACKS_PROGRESS: readonly PlanOption[] = ["ask_borrower", "ask_third_party", "i_will_do_it"];

/**
 * LP-968 — what the path needs to know about the task's CONDITION: whether its reading still needs her,
 * which keeps its draft from being made (`condition_drafts._needs_her`).
 */
export interface PathContext {
  needsConfirmation?: boolean;
}

/** One task's steps, from its own next step and how far it has got. */
export function taskPath(item: ConditionItem, context: PathContext = {}): PathStep[] {
  // LP-968 — SHE TOOK IT OFF THE PLAN: nothing left on it; the card says so, with her reason.
  if (item.status === "not_needed") return [];
  if (item.status === "done" && TRACKS_PROGRESS.includes(item.option)) return [FINISHED];
  const steps: PathStep[] = [];
  if (item.waits_on_code) {
    steps.push({
      who: "them",
      whoLabel: `Waiting on ${item.waits_on_code}`,
      text: `Starts once ${item.waits_on_code} is done`,
    });
  }
  switch (item.option) {
    case "ask_borrower":
    case "ask_third_party": {
      const who = askedWho(item);
      const email = emailWord(recipient(item));
      // LP-968 — THE DRAFT EXISTS ONCE THE PLAN IS READY (`tasks.conditions._run_read` runs
      // `sync_round_drafts` after `build_plan`), except for a condition whose reading still needs her,
      // and except on a plan built before LP-968, which still drafts at confirm. Each case says its own.
      const drafted = item.draft?.status === "draft" ? item.draft.id : undefined;
      const together = `It goes in the ${email} email, with anything else asked of ${who} this round.`;
      steps.push(
        drafted
          ? { ...WE(`We drafted the email to ${who}`, together), draftId: drafted }
          : WE(
              context.needsConfirmation
                ? `We draft the email to ${who} once you confirm how we read this condition`
                : `We draft the email to ${who} when you confirm the plan`,
              together,
            ),
        YOU(
          "Review the email, and send it once the plan is confirmed",
          // NOT ALWAYS THIS RECIPIENT (LP-967 review). `_wait_on_first_asked` is explicit that it is
          // "NOT whoever was emailed first": the owner is the recipient of the condition's FIRST live
          // ask whose email has gone, "whichever email she happened to mark sent first" — its own
          // example is 0132, the LO's disclosure before title's wire instructions. So on a condition
          // that asks two people this step cannot promise its own recipient.
          `Once you mark it sent, the condition shows as waiting on ${who}. If it asks more than one person, it waits on whichever of them it asks first.`,
        ),
        {
          who: "them",
          whoLabel: capital(who),
          text: `${capital(who)} sends it back`,
          detail:
            "If it comes by email to the file’s inbox, you accept the attachment onto the file.",
        },
        YOU("Link it to this task", "We suggest the document that matches."),
        WE("We check it against what was asked", shouldBe(item)),
      );
      break;
    }
    case "i_will_do_it":
      steps.push(
        YOU(item.task ? capital(item.task) : `Do it: ${item.name}`),
        YOU("Upload what you get to this task, or mark the task done"),
        WE("We check what you upload", shouldBe(item)),
      );
      break;
    case "already_in_file": {
      const found = item.document_name
        ? `We found ${item.document_name}${item.document_page ? `, page ${item.document_page}` : ""} on the file`
        : "We found it on the file";
      steps.push(
        WE(found),
        YOU("Check it’s the right document", "If it isn’t, change this task’s next step."),
      );
      break;
    }
    case "lender_doing_it":
      steps.push(LENDER("The lender does this itself"), YOU("Watch for it to clear"));
      break;
    case "information_only":
      steps.push(WE("Nothing to do: the lender is only telling you something"));
      break;
    case "ask_underwriter":
    case "push_back":
      // A task cannot carry these (LP-966 review): the server reads them from the condition only.
      steps.push(
        YOU(
          "This step does nothing on a single task",
          "Change it, or set it for the whole condition.",
        ),
      );
      break;
  }
  const behind = alreadyBehind(item);
  return behind === 0
    ? steps
    : [
        ...steps.slice(0, item.waits_on_code ? 1 : 0),
        ...steps.slice((item.waits_on_code ? 1 : 0) + behind),
      ];
}

/** The condition's own step, when it has one. */
export function ownStepPath(option: PlanOption): PathStep[] {
  switch (option) {
    case "push_back":
      return [
        WE(
          "We draft a note to the underwriter explaining why it should not apply, when you confirm",
        ),
        YOU("Review the note and send it"),
        LENDER("The underwriter answers"),
      ];
    case "ask_underwriter":
      return [
        WE("We draft a question to the underwriter when you confirm"),
        YOU("Review the question and send it"),
        LENDER("The underwriter answers"),
      ];
    case "lender_doing_it":
      return [LENDER("The lender does this itself"), YOU("Watch for it to clear")];
    case "information_only":
      return [WE("Nothing to do: the lender is only telling you something")];
    case "already_in_file":
      return [WE("We found it on the file"), YOU("Check it’s the right document")];
    case "i_will_do_it":
      return [YOU("Do it, then mark each task below done")];
    case "ask_borrower":
    case "ask_third_party":
      // LP-966 review: drafts are built from items, so the condition's own ask emails nothing.
      return [YOU("Ask by email", "The tasks below set to ask are what go in the email.")];
  }
}

/** How every condition ends: ready, the package, the lender clears it. Nothing for information only. */
export function endingPath(condition: Condition): PathStep[] {
  const own = condition.next_step;
  if (own === "information_only") return [];
  // A STEP THE TASKS CANNOT SETTLE (LP-967 review). `ready_because` returns None for ANY
  // condition-level step that is not "Already in the file" or "I'll do it" — so for "Lender is doing
  // it", a condition-level ask, a push-back or a question to the underwriter, finishing the tasks does
  // not make the condition Ready and it does not reach `_goes_in`'s package that way. Only
  // `information_only` was excluded, so the other three promised a route the server denies. What stays
  // true for them is the end: the lender answers, and she records it.
  if (own !== null && own !== "already_in_file" && own !== "i_will_do_it") {
    return [LENDER("The lender clears it", "You record the lender’s answer when it comes back.")];
  }
  return [
    WE("When every task is done, the condition is ready and goes in the package for the lender"),
    LENDER("The lender clears it", "You record the lender’s answer when it comes back."),
  ];
}

/** "Your first moves" across the round: derived from the plan's drafts and the rows' tasks. */
export interface FirstMoves {
  emails: number;
  /** Tasks she can do now (not waiting on another condition). */
  tasksNow: number;
  /** Tasks that wait on another condition first. */
  tasksLater: number;
  /** Who the round then waits on, once each: "the LO", "Title / escrow". */
  waitingOn: string[];
  /** Codes whose tasks are all already in the file. */
  handled: string[];
}

export function firstMoves(rows: Condition[], drafts: { codes: string[] }[]): FirstMoves {
  const out: FirstMoves = {
    emails: drafts.length,
    tasksNow: 0,
    tasksLater: 0,
    waitingOn: [],
    handled: [],
  };
  for (const condition of rows) {
    const items = liveItems(condition);
    // THE SAME RULE THE CONFIRM SUMMARY USES (LP-967 review). This read every item's OPTION, so a
    // condition whose hand-linked document was still RECEIVED appeared here as handled while
    // "Mark … ready" left it out — two boxes on one screen disagreeing about one condition.
    if (willBeReady(condition, items)) out.handled.push(condition.lender_code ?? "—");
    for (const item of items) {
      if (item.option === "i_will_do_it") {
        if (item.waits_on_code) out.tasksLater += 1;
        else out.tasksNow += 1;
      }
      if (item.option === "ask_borrower" || item.option === "ask_third_party") {
        const who = askedWho(item);
        if (!out.waitingOn.includes(who)) out.waitingOn.push(who);
      }
    }
  }
  return out;
}
