/**
 * What happens next on a condition, in the words S3-01, S3-02 and S3-12 print (LP-921).
 *
 * PURE, AND ONE COPY. The list's Next step column, the plan panel's selects and the sheet's chips all
 * read a condition's steps from here, so "which steps does 6637 have" cannot get two answers.
 *
 * NOTHING HERE MOVES A STATUS. The server moves our status when a step comes into force (the plan is
 * confirmed, an item is marked done); these functions only say what the screen shows and what will
 * happen, as the "Becomes Waiting on Borrower when the borrower email is marked sent." line does.
 */
import { OWNER_LABEL } from "@/lib/conditions/owners";
import type {
  Condition,
  ConditionItem,
  OwnerHint,
  Performer,
  PlanOption,
} from "@/lib/types/conditions";

/** Shown, never acted on (plan §4a change 12). */
export const DISPLAY_ONLY: readonly PlanOption[] = ["lender_doing_it", "information_only"];

const ASKS: readonly PlanOption[] = ["ask_borrower", "ask_third_party"];
const QUESTIONS: readonly PlanOption[] = ["push_back", "ask_underwriter"];

/** An item still on the plan: not dropped. */
function live(item: ConditionItem): boolean {
  return item.status !== "not_needed";
}

/**
 * The condition's steps: its own, then each live item's option once, in item order.
 *
 * A UNION, because a condition can carry both — 6637's items ask the borrower and title, and she can
 * still add "Ask the underwriter" to the condition as a whole.
 */
export function stepOptions(condition: Condition): PlanOption[] {
  const seen: PlanOption[] = condition.next_step ? [condition.next_step] : [];
  for (const item of condition.items) {
    if (live(item) && !seen.includes(item.option)) seen.push(item.option);
  }
  return seen;
}

/** Whether the condition's own step is display-only (M4: neutral, no status select). */
export function isDisplayOnly(condition: Condition): boolean {
  return condition.next_step !== null && DISPLAY_ONLY.includes(condition.next_step);
}

/** One email per recipient, as the server groups them (`recipient_for`): an LO item goes in the LO email. */
function recipient(item: ConditionItem): Performer {
  const performers = item.performers.length > 0 ? item.performers : [item.performer];
  if (performers.includes("lo")) return "lo";
  return performers[0] ?? item.performer;
}

/** How S3-12 names an email by who it goes to: "title email", "LO + attorney emails". */
const EMAIL_WORD: Record<Performer, string> = {
  borrower: "borrower",
  lo: "LO",
  processor: "your",
  lender: "lender",
  title: "title",
  attorney: "attorney",
  insurance: "insurance",
  hoa: "HOA",
  employer: "employer",
  appraiser: "appraiser",
  other_party: "other party",
};

/** Title and attorney share one email (S3-05), so they count as one recipient. */
function emailKey(performer: Performer): string {
  return performer === "attorney" ? "title" : performer;
}

/**
 * Where an item is: "In borrower email" for an ask. LP-922 adds "· draft" / "· sent 08/28".
 * `null` for anything that is not asked of someone.
 */
export function itemWhere(item: ConditionItem): string | null {
  if (!ASKS.includes(item.option)) return null;
  return `In ${EMAIL_WORD[recipient(item)]} email`;
}

/** The recipients of the condition's open asks, in item order, one per email. */
export function askRecipients(condition: Condition): Performer[] {
  const out: Performer[] = [];
  for (const item of condition.items) {
    if (!live(item) || item.status === "done" || !ASKS.includes(item.option)) continue;
    const who = recipient(item);
    if (!out.some((each) => emailKey(each) === emailKey(who))) out.push(who);
  }
  return out;
}

function capitalise(word: string): string {
  return word.charAt(0).toUpperCase() + word.slice(1);
}

export type NextStepIcon = "lender" | "info" | "question" | "mail" | "task" | "waits" | "file";

export interface NextStepToken {
  icon: NextStepIcon;
  text: string;
  /** `action` is ours to do or already under way (primary); `quiet` is watching or waiting (muted). */
  tone: "action" | "quiet";
}

/**
 * S3-12's Next step cell. `null` when the condition has no plan.
 *
 * ORDER IS PRECEDENCE: a display-only step says so and nothing else; a question to the underwriter
 * outranks the items; then the emails; then her own task; then "already in the file". LP-922 adds
 * "· draft" / "· sent 08/28" to the email and question tokens, and LP-923 puts a failed check first.
 */
export function nextStepToken(condition: Condition): NextStepToken | null {
  const step = condition.next_step;
  if (step === "lender_doing_it")
    return { icon: "lender", text: "Lender is doing it", tone: "quiet" };
  if (step === "information_only") return { icon: "info", text: "Information only", tone: "quiet" };
  if (step !== null && QUESTIONS.includes(step)) {
    return { icon: "question", text: "Question to UW", tone: "action" };
  }

  const recipients = askRecipients(condition);
  if (recipients.length === 1 && recipients[0]) {
    return { icon: "mail", text: `In ${EMAIL_WORD[recipients[0]]} email`, tone: "action" };
  }
  if (recipients.length > 1) {
    const words = recipients.map((each) => EMAIL_WORD[each]);
    words[0] = capitalise(words[0] ?? "");
    return { icon: "mail", text: `${words.join(" + ")} emails`, tone: "action" };
  }

  const task = condition.items.find(
    (item) => live(item) && item.option === "i_will_do_it" && item.status !== "done",
  );
  if (task?.waits_on_code)
    return { icon: "waits", text: `Waits on ${task.waits_on_code}`, tone: "quiet" };
  if (task || step === "i_will_do_it") {
    const what = task ? (task.task ?? task.name.toLowerCase()) : "your task";
    return { icon: "task", text: `Your task · ${what}`, tone: "quiet" };
  }

  const inFile = condition.items.find((item) => live(item) && item.option === "already_in_file");
  if (step === "already_in_file" || inFile) {
    const page = inFile?.document_page;
    return {
      icon: "file",
      text: page ? `Already in the file · p.${page}` : "Already in the file",
      tone: "action",
    };
  }
  return null;
}

/** "LO" for the broker (M5), "someone" when we do not know; the owner chip keeps "Broker". */
export function waitingLabel(owner: OwnerHint | null): string {
  if (owner === null || owner === "unknown") return "someone";
  if (owner === "broker") return "LO";
  return OWNER_LABEL[owner];
}

/** Who a performer's email leaves us waiting on, in Stage 2's owners. */
const WAITING_ON: Record<Performer, OwnerHint> = {
  borrower: "borrower",
  lo: "broker",
  processor: "processor",
  lender: "lender",
  title: "title",
  attorney: "title",
  insurance: "insurance",
  hoa: "unknown",
  employer: "unknown",
  appraiser: "unknown",
  other_party: "unknown",
};

export interface Becomes {
  /** "Waiting on Borrower", "Ready to send". */
  status: string;
  /** "the borrower email is marked sent". */
  when: string;
}

/**
 * S3-01's "Becomes **Waiting on Borrower** when the borrower email is marked sent." — what the next
 * step will do to our status, or `null` when it will do nothing (display-only, already moved).
 */
export function becomes(condition: Condition): Becomes | null {
  if (condition.prep_status !== "to_do" || isDisplayOnly(condition)) return null;
  const step = condition.next_step;
  if (step !== null && QUESTIONS.includes(step)) {
    return { status: "Waiting on Lender", when: "the question is marked sent" };
  }
  const first = askRecipients(condition)[0];
  if (first) {
    return {
      status: `Waiting on ${waitingLabel(WAITING_ON[first])}`,
      when: `the ${EMAIL_WORD[first]} email is marked sent`,
    };
  }
  if (stepOptions(condition).includes("i_will_do_it")) {
    return { status: "Ready to send", when: "your task is done" };
  }
  return null;
}
