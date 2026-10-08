/**
 * LP-966 — what each next step MEANS, in a processor's words: the plan screen's explanations.
 *
 * The owner, 2026-10-08: "we need better explaination, and some where detail explaination so the
 * processor can understand what they has to do", and "some way to tell processor what does I'll do
 * it, Ask third party, Ask Borrower means". `plan-words.ts` names the steps; this says what each one
 * DOES when the plan is confirmed.
 *
 * EVERY SENTENCE HERE IS A CLAIM ABOUT THE SERVER, checked against it when written:
 * - asks (`ask_borrower`, `ask_third_party`) go into a draft email to their recipient
 *   (`condition_drafts._ASKS`, `recipient_for`), which she reviews before sending, and the condition
 *   moves to Waiting on that person when the email is marked sent;
 * - questions (`ask_underwriter`, `push_back`) become a draft to the underwriter
 *   (`condition_drafts._QUESTIONS`);
 * - "Already in the file" makes the condition Ready on confirm (`condition_plan.ready_because`), and so
 *   does "I'll do it" once every task is marked done;
 * - "Lender is doing it" and "Information only" are display-only (`next-step.ts` `DISPLAY_ONLY`).
 * A change on the server that breaks one of these makes the sentence false: change both together.
 */
import { emailWord, recipient } from "@/lib/conditions/next-step";
import { PERFORMER_LABEL } from "@/lib/conditions/plan-words";
import type { BucketKind, ConditionItem, PlanOption } from "@/lib/types/conditions";

/** What a step does, for any task. The ⓘ dialog lists all eight. */
export const OPTION_MEANING: Record<PlanOption, string> = {
  i_will_do_it:
    "You do this yourself. It goes on your task list, and the condition is ready to send to the lender once you mark it done.",
  ask_borrower:
    "We put this request in the email to the borrower. You review the email before it is sent; once sent, the condition shows as waiting on the borrower.",
  ask_third_party:
    "We put this request in an email to the person who has it, such as Title, the LO or the insurance agent. You review the email first; once sent, the condition waits on them.",
  already_in_file:
    "We found the document already on the file. It is linked to the condition, and the condition is marked ready to send to the lender when you confirm.",
  ask_underwriter:
    "Something in the condition is unclear, so we draft a question to the underwriter for you to review and send.",
  push_back:
    "You think the condition should not apply. We draft a note to the underwriter explaining why, for you to review and send.",
  lender_doing_it:
    "The lender handles this itself, for example ordering it through its own vendor. Nothing to request; you watch for it to clear.",
  information_only: "The lender is only telling you something. Nothing to do or send.",
};

/** One example per step, in the dialog. Generic: they read the same on every file. */
export const OPTION_EXAMPLE: Record<PlanOption, string> = {
  i_will_do_it: "uploading the credit report invoice yourself.",
  ask_borrower: "asking the borrower for two months of bank statements.",
  ask_third_party: "asking Title for the final seller Closing Disclosure.",
  already_in_file: "an invoice that was uploaded earlier and found on the file.",
  ask_underwriter: "asking which account a vague asset condition means.",
  push_back: "a condition whose own dates mean it cannot apply to this loan.",
  lender_doing_it: "a desk review the lender orders itself.",
  information_only: "a note that the loan is approved subject to the conditions.",
};

/** The order the dialog lists them in: the common ones first. */
export const OPTION_ORDER: readonly PlanOption[] = [
  "i_will_do_it",
  "ask_borrower",
  "ask_third_party",
  "already_in_file",
  "ask_underwriter",
  "push_back",
  "lender_doing_it",
  "information_only",
];

/** Who an ask goes to, by name: "Title / escrow", "the LO", "the borrower". */
function askedWho(item: ConditionItem | null): string {
  if (item === null) return "a third party";
  const who = recipient(item);
  if (who === "borrower") return "the borrower";
  if (who === "lo") return "the LO";
  if (who === "appraiser") return "the lender";
  return PERFORMER_LABEL[who];
}

/**
 * The short phrase on a task's line: "You order the final inspection", "Ask Title / escrow — in the
 * title email". Names the email the server will put it in, so it cannot disagree with the draft. `item`
 * is null for the condition's own step, which has no recipient of its own.
 */
export function actionFor(option: PlanOption, item: ConditionItem | null): string {
  switch (option) {
    case "i_will_do_it":
      return item?.task ? `You ${item.task}` : "You do it";
    case "ask_borrower":
      return "Ask the borrower — in the borrower email";
    case "ask_third_party":
      return item === null
        ? "Ask a third party — by email"
        : `Ask ${askedWho(item)} — in the ${emailWord(recipient(item))} email`;
    case "already_in_file":
      return "Already in the file";
    case "ask_underwriter":
      return "Ask the underwriter";
    case "push_back":
      return "Push back to the underwriter";
    case "lender_doing_it":
      return "The lender does it";
    case "information_only":
      return "Nothing to do";
  }
}

/** The line under a task's select: the chosen step's meaning, naming the person for an ask. */
export function meaningFor(option: PlanOption, item: ConditionItem | null): string {
  if (option === "ask_third_party" && item) {
    return `We put this request in the email to ${askedWho(item)}. You review the email first; once sent, the condition waits on them.`;
  }
  return OPTION_MEANING[option];
}

/** "When it's needed": what the lender's heading means for timing. */
export const BUCKET_KIND_MEANING: Record<BucketKind, string> = {
  master: "it applies to the whole file.",
  prior_to_approval: "the lender needs this before it gives final approval.",
  prior_to_docs: "the lender needs this before closing documents can be drawn.",
  prior_to_closing: "the lender needs this before the loan closes.",
  prior_to_funding: "needed before the loan funds, after closing documents are drawn.",
  lender_to_clear: "the lender clears this itself.",
  trailing: "due after closing.",
  unknown: "the sheet did not say when it is due.",
};
