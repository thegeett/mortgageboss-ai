/**
 * LP-958 — the drawer's "Next" box: the ONE thing to do on a condition now, in a sentence, and the
 * control that does it (item 9 of the 2026-09-30 staging trial; the mockup the owner approved
 * 2026-10-03). The owner set every condition to Ready to send and asked "what next?": the screen had
 * the statuses and no sentence. This is the sentence.
 *
 * PURE. Everything it reads is on the condition, plus the package's lender and ready count, so the
 * same condition always gets the same answer and the tests need no server.
 *
 * ORDER IS PRECEDENCE, and it follows the work: what the lender said outranks what we sent; a failed
 * check outranks what we asked; Ready outranks the plan (the plan is done); then her task, then the
 * emails, then the question, then the lender's own work.
 *
 * NOTHING HERE MOVES A STATUS. The sentences name the click that does, and the server does it.
 */
import {
  askRecipients,
  emailWord,
  unsentAskDrafts,
  waitingLabel,
} from "@/lib/conditions/next-step";
import type { Condition, ConditionItem } from "@/lib/types/conditions";

const ASKS = ["ask_borrower", "ask_third_party"];
const QUESTIONS = ["push_back", "ask_underwriter"];

export type NextDo =
  /** Add document ▾ and Ask someone ▾ for this item. */
  | { kind: "item"; itemId: string }
  /** Close the drawer and show the Conditions tab's lender package panel. */
  | { kind: "package" }
  | { kind: "draft"; draftId: string }
  | { kind: "record" };

export interface NextAction {
  text: string;
  do?: NextDo;
  /** `done` is the quiet end state: the lender cleared or waived it. */
  tone: "action" | "waiting" | "blocking" | "done";
}

export interface NextContext {
  /** "UWM" — the package's short name; "the lender" when there is none. */
  lender?: string | null;
  /** How many conditions on the file go in the package now (`ready_count`). */
  readyCount?: number | null;
}

function live(item: ConditionItem): boolean {
  return item.status !== "not_needed";
}

/** `2026-08-28` → `08/28`. */
function short(iso: string): string {
  return iso.slice(5).replace("-", "/");
}

export { goesInPackage } from "@/lib/conditions/next-step";

export function nextAction(condition: Condition, context: NextContext = {}): NextAction | null {
  const lender = context.lender || "the lender";
  // A replaced condition takes no writes; the sheet already points at the one that does.
  if (condition.superseded_by_id !== null) return null;
  if (condition.lender_status === "cleared") {
    return { text: `${lender} cleared it. Nothing left to do.`, tone: "done" };
  }
  if (condition.lender_status === "waived") {
    return { text: `${lender} waived it. Nothing left to do.`, tone: "done" };
  }
  if (condition.info_only) {
    return { text: "Information only: nothing to send for it.", tone: "done" };
  }

  // What arrived and failed outranks everything we asked for.
  const failed = (condition.evidence ?? []).find((evidence) => evidence.failed);
  if (failed) {
    const what = failed.reask ?? failed.checks.find((c) => c.result === "failed")?.label ?? "";
    return {
      text: `A document failed a check${what ? `: ${what}` : ""}. Fix it in the document card below, or link a different one.`,
      tone: "blocking",
    };
  }

  if (condition.prep_status === "with_underwriter") {
    return condition.lender_status === "not_cleared"
      ? {
          text: `${lender} did not clear it. Read their note, fix what it asks, then send it again.`,
          tone: "blocking",
        }
      : {
          text: `Sent to ${lender}. When they answer, record it here.`,
          do: { kind: "record" },
          tone: "waiting",
        };
  }

  if (condition.prep_status === "ready") {
    const unsent = unsentAskDrafts(condition)[0];
    if (unsent) {
      return {
        text: "It is Ready to send, but its email was never sent. Send it, or mark the item not needed.",
        do: { kind: "draft", draftId: unsent.id },
        tone: "blocking",
      };
    }
    const others = context.readyCount ? context.readyCount - 1 : 0;
    return {
      text: `Send it to ${lender}: build the lender package.${
        others > 0
          ? ` It goes in with ${others} other condition${others === 1 ? "" : "s"} that ${others === 1 ? "is" : "are"} ready.`
          : ""
      }`,
      do: { kind: "package" },
      tone: "action",
    };
  }

  // Her own task: the first one not done.
  const task = condition.items.find(
    (item) => live(item) && item.option === "i_will_do_it" && item.status !== "done",
  );
  if (task?.waits_on_code) {
    return { text: `Waits on ${task.waits_on_code}: that condition comes first.`, tone: "waiting" };
  }
  if (task) {
    return {
      text: `Get the ${task.name.toLowerCase()}: link it if it is already on the file, or ask someone for it.`,
      do: { kind: "item", itemId: task.id },
      tone: "action",
    };
  }

  const unsent = unsentAskDrafts(condition)[0];
  if (unsent) {
    const who = askRecipients(condition).map(emailWord);
    return {
      text: `Send the ${who.join(" and ")} email${who.length > 1 ? "s" : ""}.`,
      do: { kind: "draft", draftId: unsent.id },
      tone: "action",
    };
  }
  if (askRecipients(condition).length > 0) {
    const who = waitingLabel(condition.waiting_on);
    return { text: `Waiting on ${who}: the email was sent.`, tone: "waiting" };
  }

  const step = condition.next_step;
  if (step !== null && QUESTIONS.includes(step)) {
    const question = condition.question_draft;
    if (question?.status === "draft") {
      return {
        text: "Send the question to the underwriter.",
        do: { kind: "draft", draftId: question.id },
        tone: "action",
      };
    }
    if (question?.status === "sent") {
      return {
        text: `Waiting on the underwriter: the question was sent${
          question.sent_on ? ` ${short(question.sent_on)}` : ""
        }.`,
        tone: "waiting",
      };
    }
  }
  if (step === "lender_doing_it") {
    return {
      text: `${lender} is doing this one. Nothing to do until they answer.`,
      tone: "waiting",
    };
  }
  if (
    step === "already_in_file" ||
    condition.items.some((i) => live(i) && i.option === "already_in_file")
  ) {
    return {
      text: "It is already in the file. Check the document, then set it Ready to send.",
      tone: "action",
    };
  }
  return null;
}

/**
 * LP-958 — the Lender's answer cell. `open` reads "Not cleared yet": the owner read the bare "Open" in
 * the last column as a button or a state of ours ("What is that Open last column for?", 2026-10-03).
 * The shared vocabulary keeps "Open" for the filters and the tiles, where it is a count of what the
 * lender still owes; only the answer cell says it as an answer.
 */
export function lenderAnswerLabel(status: Condition["lender_status"], label: string): string {
  return status === "open" ? "Not cleared yet" : label;
}
