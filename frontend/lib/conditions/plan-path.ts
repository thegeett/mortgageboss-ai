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

/** One task's steps, from its own next step. */
export function taskPath(item: ConditionItem): PathStep[] {
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
      steps.push(
        WE(
          `We draft the email to ${who} when you confirm the plan`,
          `It goes in the ${email} email, with anything else asked of ${who} this round.`,
        ),
        YOU(
          "Review the email and send it",
          `Once you mark it sent, the condition shows as waiting on ${who}.`,
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
  return steps;
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
  if (condition.next_step === "information_only") return [];
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
    if (items.length > 0 && items.every((item) => item.option === "already_in_file")) {
      out.handled.push(condition.lender_code ?? "—");
    }
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
