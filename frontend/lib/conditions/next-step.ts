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
  DraftTail,
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
export function recipient(item: ConditionItem): Performer {
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
  // LP-942: never the appraiser's own email; appraisal requests go through the lender.
  appraiser: "lender",
  other_party: "other party",
};

/** LP-958 — "borrower", "LO", "title": how an email is named by who it goes to. */
export function emailWord(performer: Performer): string {
  return EMAIL_WORD[performer];
}

/** Title and attorney share one email (S3-05), so they count as one recipient. */
function emailKey(performer: Performer): string {
  if (performer === "attorney") return "title";
  // LP-942: the appraiser's asks go in the lender's email, so the two count as one recipient.
  if (performer === "appraiser") return "lender";
  return performer;
}

/**
 * Where an item is: "In borrower email" for an ask. LP-922 adds "· draft" / "· sent 08/28".
 * `null` for anything that is not asked of someone.
 */
export function itemWhere(item: ConditionItem): string | null {
  if (!ASKS.includes(item.option)) return null;
  return `In ${EMAIL_WORD[recipient(item)]} email${tail(item.draft ? [item.draft] : [])}`;
}

/** The drafts carrying the condition's asks, once each. */
function askDrafts(condition: Condition): DraftTail[] {
  const out: DraftTail[] = [];
  for (const item of condition.items) {
    if (!live(item) || !ASKS.includes(item.option) || !item.draft) continue;
    if (!out.some((each) => each.id === item.draft?.id)) out.push(item.draft);
  }
  return out;
}

/**
 * S3-12's tail: " · sent 08/28" once every draft carrying it was marked sent (the latest date),
 * " · draft" while any is unsent, nothing before the plan made one.
 */
export function tail(drafts: readonly DraftTail[]): string {
  if (drafts.length === 0) return "";
  if (drafts.some((draft) => draft.status === "draft")) return " · draft";
  const dates = drafts.map((draft) => draft.sent_on ?? "").sort();
  const last = dates[dates.length - 1];
  return last ? ` · sent ${last.slice(5).replace("-", "/")}` : " · sent";
}

/** LP-958 — the unsent drafts carrying the condition's OPEN asks (not done, not dropped), once each. */
export function unsentAskDrafts(condition: Condition): DraftTail[] {
  const out: DraftTail[] = [];
  for (const item of condition.items) {
    if (!live(item) || item.status === "done" || !ASKS.includes(item.option)) continue;
    if (item.draft?.status === "draft" && !out.some((each) => each.id === item.draft?.id)) {
      out.push(item.draft);
    }
  }
  return out;
}

/** LP-958 — whether the server's package takes it now: `condition_package._goes_in`, mirrored. */
export function goesInPackage(condition: Condition): boolean {
  return condition.prep_status === "ready" && openWithLender(condition) && !condition.info_only;
}

/**
 * Still awaiting the lender's word: `open`, or came back `not_cleared` and not answered since. The
 * backend's `_OPEN` (`condition_package.py:58`), as ONE predicate (LP-958 review).
 *
 * It was written out twice with different members: the package rule counted `not_cleared` and the
 * "Sent to lender" token did not, so a condition she had fixed and re-sent read as sent in the
 * package rule and as un-sent in the Next step column, and the drawer's Next box said a third thing.
 * Anything asking "is the lender still to answer?" asks here.
 */
export function openWithLender(condition: Condition): boolean {
  return condition.lender_status === "open" || condition.lender_status === "not_cleared";
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

export type NextStepIcon =
  | "lender"
  | "info"
  | "question"
  | "mail"
  | "task"
  | "waits"
  | "file"
  | "failed"
  | "finding";

export interface NextStepToken {
  icon: NextStepIcon;
  text: string;
  /** LP-922 — the draft this token opens, when it is about an email. */
  draftId?: string;
  /**
   * `action` is ours to do or already under way (primary); `quiet` is watching or waiting (muted);
   * `blocking` is a failed check (red, S3-12); `attention` is a finding waiting on an answer.
   */
  tone: "action" | "quiet" | "blocking" | "attention";
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
  // LP-923 — WHAT ARRIVED OUTRANKS WHAT WAS ASKED. A failed check is the next thing she must act on
  // ("Evidence failed a check — page 6", S3-12), then a deposit waiting on an explanation.
  const failed = (condition.evidence ?? []).find((evidence) => evidence.failed);
  if (failed) {
    const what = failed.reask ?? failed.checks.find((c) => c.result === "failed")?.label ?? "";
    return {
      icon: "failed",
      text: `Evidence failed a check${what ? ` — ${what}` : ""}`,
      tone: "blocking",
    };
  }
  // Not a REPLACED upload's findings: they hold nothing on the server (`_settle`), and since LP-937 made
  // its `failed` false this line is reached for it (LP-937 review).
  const finding = (condition.evidence ?? [])
    .filter((evidence) => !evidence.replaced)
    .flatMap((evidence) => evidence.findings)
    .find((f) => f.needed && f.status !== "explained");
  if (finding) {
    return {
      icon: "finding",
      text:
        finding.status === "asked" ? "Deposit explanation asked" : "Large deposit needs sourcing",
      tone: "attention",
    };
  }
  // LP-958 — READY SAYS WHERE IT GOES. The owner set every row Ready and the column still showed
  // the plan's emails, so nothing said what came next. An ask still in an unsent draft is the one
  // thing that makes Ready doubtful, so it says that first.
  if (condition.prep_status === "ready") {
    const unsent = unsentAskDrafts(condition)[0];
    if (unsent) {
      return {
        icon: "mail",
        text: "Ready, but its email is unsent: send it or mark the item not needed",
        tone: "attention",
        draftId: unsent.id,
      };
    }
    if (goesInPackage(condition)) {
      const checked = (condition.evidence ?? []).length > 0;
      return {
        icon: "file",
        text: `Goes in the lender package${checked ? " · evidence checked" : ""}`,
        tone: "action",
      };
    }
  }
  // A RE-SENT CONDITION IS STILL SENT (LP-958 review). This read `lender_status === "open"`, so a
  // condition that came back `not_cleared`, was fixed and submitted again fell past here and showed the
  // plan's steps — as if nothing had been sent — while the drawer told her to send it again.
  if (condition.prep_status === "with_underwriter" && openWithLender(condition)) {
    return { icon: "lender", text: "Sent to lender · waiting for their answer", tone: "quiet" };
  }
  if (step === "lender_doing_it")
    return { icon: "lender", text: "Lender is doing it", tone: "quiet" };
  if (step === "information_only") return { icon: "info", text: "Information only", tone: "quiet" };
  if (step !== null && QUESTIONS.includes(step)) {
    const question = condition.question_draft;
    return {
      icon: "question",
      text: `Question to UW${tail(question ? [question] : [])}`,
      tone: "action",
      draftId: question?.id,
    };
  }

  const recipients = askRecipients(condition);
  const drafts = askDrafts(condition);
  const opens = (drafts.find((draft) => draft.status === "draft") ?? drafts[0])?.id;
  if (recipients.length === 1 && recipients[0]) {
    return {
      icon: "mail",
      text: `In ${EMAIL_WORD[recipients[0]]} email${tail(drafts)}`,
      tone: "action",
      draftId: opens,
    };
  }
  if (recipients.length > 1) {
    const words = recipients.map((each) => EMAIL_WORD[each]);
    words[0] = capitalise(words[0] ?? "");
    return {
      icon: "mail",
      text: `${words.join(" + ")} emails${tail(drafts)}`,
      tone: "action",
      draftId: opens,
    };
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
  // LP-947: WHO we will wait on is the server's (`waiting_on_when_sent`, the rule its send applies);
  // this only words it, and says which email moves it.
  const status = `Waiting on ${waitingLabel(condition.waiting_on_when_sent)}`;
  if (step !== null && QUESTIONS.includes(step)) {
    return { status, when: "the question is marked sent" };
  }
  const first = askRecipients(condition)[0];
  if (first) {
    return { status, when: `the ${EMAIL_WORD[first]} email is marked sent` };
  }
  if (stepOptions(condition).includes("i_will_do_it")) {
    return { status: "Ready to send", when: "your task is done" };
  }
  return null;
}
