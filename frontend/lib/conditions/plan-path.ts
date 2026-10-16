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
import type { Condition, ConditionItem, Performer, PlanOption } from "@/lib/types/conditions";

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
  /** LP-980 — already done (shown ticked), when the path keeps its done steps (`keepDone`). */
  done?: boolean;
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

/** `2026-10-15` → `10/15`. */
function usShort(iso: string): string {
  const [, month, day] = iso.slice(0, 10).split("-");
  return month && day ? `${month}/${day}` : iso;
}

function capital(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * LP-979 — THE APP'S STEPS SAY WHAT KIND OF STEP THEY ARE, as the agreed mockup and the legend ("We
 * prepare or check it") do: "We prepare it" for what it drafts or puts together, "We check it" for a
 * check, "We found it" for what it found on the file. A bare "We" said who, not what.
 */
const WE = (text: string, detail?: string): PathStep => ({
  who: "we",
  whoLabel: "We prepare it",
  text,
  detail,
});
const CHECK = (text: string, detail?: string): PathStep => ({
  who: "we",
  whoLabel: "We check it",
  text,
  detail,
});
const FOUND = (text: string, detail?: string): PathStep => ({
  who: "we",
  whoLabel: "We found it",
  text,
  detail,
});
const NOTHING = (text: string): PathStep => ({ who: "we", whoLabel: "Nothing to do", text });
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

/**
 * LP-971 follow-up — "WE CHECK IT" SAYS WHAT IS CHECKED, AND IS NOT THERE WHEN NOTHING IS. The owner on
 * 0006: "We check what you upload" sat on IV-01's invoice, which has no checks (only its type is
 * compared, when she links one), and on a step she added, which had neither, so anything she linked
 * passed. So: checks beyond the type keep the general sentence; a type alone names it ("We check it’s
 * a service invoice"); nothing, no step.
 */
function checkSteps(item: ConditionItem, general: string): PathStep[] {
  if (item.has_checks) return [CHECK(general, shouldBe(item))];
  const kinds = item.document_kinds ?? [];
  if (kinds.length === 0) return [];
  return [CHECK(`We check it’s ${withArticle(kinds.join(" or "))}`, shouldBe(item))];
}

function withArticle(words: string): string {
  return /^[aeiou]/i.test(words) ? `an ${words}` : `a ${words}`;
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
  // (A wait's path is the same length — its wait and her upload — so `received` trims the same two.)
  return 0;
}

const TRACKS_PROGRESS: readonly PlanOption[] = ["ask_borrower", "ask_third_party", "i_will_do_it"];

/**
 * LP-968 — what the path needs to know about the task's CONDITION: whether its reading still needs her,
 * which keeps its draft from being made (`condition_drafts._needs_her`).
 */
export interface PathContext {
  needsConfirmation?: boolean;
  /**
   * LP-979 — the file's lender by name ("UWM"), so the ending says who clears it, as the mockup does
   * ("UWM clears 1228"). Absent while the file names no lender: the ending says "the lender".
   */
  lenderName?: string | null;
  /**
   * LP-980 — KEEP THE STEPS ALREADY DONE, marked `done`, instead of starting the path where the task
   * is. The confirmed plan is the working view, so what already happened ("Sent Tue 13 Oct") stays on
   * it, ticked. The plan before Confirm leaves this off and is unchanged.
   */
  keepDone?: boolean;
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
      const checks = checkSteps(item, "We check it against what was asked");
      steps.push(
        drafted
          ? { ...WE(`We drafted the email to ${who}`, together), draftId: drafted }
          : // LP-980 — once it is sent, its draft is in the past: the confirmed plan shows it ticked.
            item.draft?.status === "sent"
            ? WE(`We drafted the email to ${who}`, together)
            : WE(
                context.needsConfirmation
                  ? `We draft the email to ${who} once you confirm how we read this condition`
                  : `We draft the email to ${who} when you confirm the plan`,
                together,
              ),
        YOU(
          item.draft?.status === "sent" && item.draft.sent_on
            ? `Sent ${usShort(item.draft.sent_on)}`
            : "Review the email, and send it once the plan is confirmed",
          // AND "FIRST" MEANS THE FIRST ONE SENT (LP-973 review, from a6's mutation pass).
          // `first_asked_owner` walks the items in order but SKIPS any ask whose email has not gone
          // (`gone(item) is None`), so a condition asking Title first and the borrower second, with
          // only the borrower's email sent, waits on the BORROWER. This said "whichever of them it
          // asks first", which names the item order alone and would have her expect Title.
          // NOT ALWAYS THIS RECIPIENT (LP-967 review). `_wait_on_first_asked` is explicit that it is
          // "NOT whoever was emailed first": the owner is the recipient of the condition's FIRST live
          // ask whose email has gone, "whichever email she happened to mark sent first" — its own
          // example is 0132, the LO's disclosure before title's wire instructions. So on a condition
          // that asks two people this step cannot promise its own recipient.
          `Once you mark it sent, the condition shows as waiting on ${who}. If it asks more than one person, it waits on the first of them whose email you have sent.`,
        ),
        {
          who: "them",
          whoLabel: capital(who),
          text: `${capital(who)} sends it back`,
          detail:
            "If it comes by email to the file’s inbox, you accept the attachment onto the file.",
        },
        // LP-980 REVIEW — THE LAST STEP HAS TO NAME WHAT IS STILL OPEN. With a check row after it,
        // linking is the whole of this step and the check is what remains. With nothing to check
        // (`document_kinds` empty and no `checks`), linking is the LAST thing the path knows about —
        // and a RECEIVED task is linked, so the working view ticked everything before this step,
        // left this one unticked, and `nextOf` named "Link it to this task" as what to do next on a
        // document she had already linked. Her remaining action is to accept it, which is the clause
        // the other two paths already end with, so this one ends with it too rather than inventing a
        // sentence: "or mark the task done" is what is owed, and the step reads true in both states.
        checks.length > 0
          ? YOU("Link it to this task", "We suggest the document that matches.")
          : YOU(
              "Link it to this task, or mark the task done",
              "We suggest the document that matches. Nothing checks this one, so it is yours to accept.",
            ),
        ...checks,
      );
      break;
    }
    case "i_will_do_it":
      // LP-972 — "WAIT FOR SOMETHING": she asked some other way, so no email goes; the steps are the
      // wait, then the same upload-or-link and check as her own task. The reminder is the server's
      // (`reminders._waits_due`): on the date, Eastern, on the Reminders page while it is still open.
      if (item.waiting) {
        const who = PERFORMER_LABEL[item.performer];
        steps.push(
          {
            who: "them",
            whoLabel: who,
            text: `${who} sends ${item.name}`,
            detail: item.due_date
              ? `If it hasn’t come by ${usShort(item.due_date)}, it shows on your Reminders page.`
              : undefined,
          },
          YOU("When it comes, upload or link it here, or mark the task done"),
          ...checkSteps(item, "We check what you upload"),
        );
        break;
      }
      steps.push(
        YOU(item.task ? capital(item.task) : `Do it: ${item.name}`),
        YOU("Upload what you get to this task, or mark the task done"),
        ...checkSteps(item, "We check what you upload"),
      );
      break;
    case "already_in_file": {
      const found = item.document_name
        ? `We found ${item.document_name}${item.document_page ? `, page ${item.document_page}` : ""} on the file`
        : "We found it on the file";
      steps.push(
        FOUND(found),
        YOU("Check it’s the right document", "If it isn’t, change this task’s next step."),
      );
      break;
    }
    case "lender_doing_it":
      steps.push(LENDER("The lender does this itself"), YOU("Watch for it to clear"));
      break;
    case "information_only":
      steps.push(NOTHING("Nothing to do: the lender is only telling you something"));
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
  // LP-971 FOLLOW-UP REVIEW — THE TRIM MAY NOT EMPTY A TASK THAT IS NOT DONE. `alreadyBehind` returns
  // fixed counts (2 for a sent ask, 4 for one that came back) that assumed every path ended in a
  // "We check it" row. Dropping that row where nothing is checked made the counts one too many: a
  // RECEIVED task with no checks trimmed to NOTHING — no steps on its card, and no entry for `nextOf`
  // to read, so the condition's own "Next:" skipped it and named the lender's ending while she still
  // had to accept the document. Measured: `received` + no `document_kinds` gave `[]`, where the same
  // item with a kind gave `["We check it"]`. Capping the trim leaves the most advanced step she still
  // owes — for her own task that is "upload what you get, or mark the task done", which is exactly it.
  const behind = Math.min(alreadyBehind(item), Math.max(steps.length - 1, 0));
  if (context.keepDone && behind > 0) {
    const from = item.waits_on_code ? 1 : 0;
    return steps.map((step, index) =>
      index >= from && index < from + behind ? { ...step, done: true } : step,
    );
  }
  return behind === 0
    ? steps
    : [
        ...steps.slice(0, item.waits_on_code ? 1 : 0),
        ...steps.slice((item.waits_on_code ? 1 : 0) + behind),
      ];
}

/**
 * WHEN A QUESTION IS DRAFTED (LP-969). These steps said "when you confirm", which LP-968 made false:
 * `sync_round_drafts` makes the underwriter draft in the same pass as every other draft, once the plan
 * is ready, unless the condition's reading still needs her (`_needs_her`). Sending still waits for
 * confirm (`unconfirmed_rounds_for`).
 */
const QUESTION_DRAFTED =
  "It is drafted once the plan is ready, or once you confirm how we read this condition if we asked you to.";

/** The condition's own step, when it has one. */
export function ownStepPath(option: PlanOption): PathStep[] {
  switch (option) {
    case "push_back":
      return [
        // LP-969: THE DRAFT ARGUES ONE CASE ITSELF (`render_question`: the HOI policy's start against
        // Must Not Close Before). Every other push back is drafted as the general question, so this
        // step cannot promise the argument is written.
        WE("We draft a note to the underwriter on this condition", QUESTION_DRAFTED),
        YOU(
          "Review the note, say why it shouldn’t apply, and send it once the plan is confirmed",
          "If we found the reason on the sheet, the note already says it.",
        ),
        LENDER("The underwriter answers"),
      ];
    case "ask_underwriter":
      return [
        WE("We draft a question to the underwriter on this condition", QUESTION_DRAFTED),
        YOU("Review the question, and send it once the plan is confirmed"),
        LENDER("The underwriter answers"),
      ];
    case "lender_doing_it":
      return [LENDER("The lender does this itself"), YOU("Watch for it to clear")];
    case "information_only":
      return [NOTHING("Nothing to do: the lender is only telling you something")];
    case "already_in_file":
      return [FOUND("We found it on the file"), YOU("Check it’s the right document")];
    case "i_will_do_it":
      return [YOU("Do it, then mark each task below done")];
    case "ask_borrower":
    case "ask_third_party":
      // LP-966 review: drafts are built from items, so the condition's own ask emails nothing.
      return [YOU("Ask by email", "The tasks below set to ask are what go in the email.")];
  }
}

/** How every condition ends: ready, the package, the lender clears it. Nothing for information only. */
export function endingPath(condition: Condition, context: PathContext = {}): PathStep[] {
  const own = condition.next_step;
  if (own === "information_only") return [];
  // LP-979 — NAMED WHEN WE KNOW: "UWM clears 1228" and "…the package for UWM". Without a lender on the
  // file, the words stay "the lender" and "it".
  const lender = context.lenderName;
  const clears = lender
    ? { ...LENDER(`${lender} clears ${condition.lender_code ?? "it"}`, RECORD), whoLabel: lender }
    : LENDER("The lender clears it", RECORD);
  // A STEP THE TASKS CANNOT SETTLE (LP-967 review). `ready_because` returns None for ANY
  // condition-level step that is not "Already in the file" or "I'll do it" — so for "Lender is doing
  // it", a condition-level ask, a push-back or a question to the underwriter, finishing the tasks does
  // not make the condition Ready and it does not reach `_goes_in`'s package that way. Only
  // `information_only` was excluded, so the other three promised a route the server denies. What stays
  // true for them is the end: the lender answers, and she records it.
  if (own !== null && own !== "already_in_file" && own !== "i_will_do_it") {
    return [clears];
  }
  return [
    WE(
      `When every task is done, the condition is ready and goes in the package for ${lender ?? "the lender"}`,
    ),
    clears,
  ];
}

const RECORD = "You record the lender’s answer when it comes back.";

/** LP-974 — one step on a condition's timeline, and the task it belongs to (null: the condition's). */
export interface PlanEntry {
  step: PathStep;
  item: ConditionItem | null;
  /** The task's first step here: where its badge and her edits sit. */
  leads: boolean;
}

/**
 * LP-974 — THE CONDITION'S PLAN AS ONE NUMBERED TIMELINE, as the agreed mockup draws it: the
 * condition's own step, then each task's steps, then the shared ending. LP-967 built a card per task
 * with the path inside it, which is not the design the owner approved ("current design and mock
 * design is different").
 *
 * A task she took off the plan keeps one entry, so it stays on the screen crossed out with her reason
 * and Undo (LP-968) rather than vanishing. A condition with no live task and no step of its own has no
 * ending: there is nothing left for it to finish.
 */
export function conditionPath(condition: Condition, context: PathContext = {}): PlanEntry[] {
  const entries: PlanEntry[] = [];
  const own = condition.next_step;
  if (own) {
    ownStepPath(own).forEach((step, index) => {
      entries.push({ step, item: null, leads: index === 0 });
    });
  }
  for (const item of condition.items) {
    if (item.status === "not_needed") {
      entries.push({
        step: {
          who: "you",
          whoLabel: "Not needed",
          text: item.name,
          detail: item.plan_note ?? undefined,
        },
        item,
        leads: true,
      });
      continue;
    }
    taskPath(item, context).forEach((step, index) => {
      entries.push({ step, item, leads: index === 0 });
    });
  }
  // NO ENDING WHEN EVERY TASK IS DROPPED and the condition has no step of its own: nothing is left to
  // finish, so "when every task is done, the condition is ready" would promise what `ready_because`
  // refuses (it needs a live task).
  if (own === null && liveItems(condition).length === 0) return entries;
  for (const step of endingPath(condition, context)) {
    entries.push({ step, item: null, leads: false });
  }
  return entries;
}

/**
 * LP-974 — the collapsed row's "Next:": the first step still ahead. A dropped task and a finished one
 * are not ahead of her, so they are skipped; when nothing is left, the ending is what comes next.
 *
 * LP-979 — A PERSON'S STEP, NOT THE APP'S, as the agreed mockup reads ("Next: Review and send the email
 * to UWM"). "We check what you upload" or "We drafted the email" is the app's own work, and showing it
 * as "Next" told her nothing she does. So the app's steps are passed over for the first step someone
 * takes: hers, or the person or lender she is waiting on ("Title / escrow sends it back" is the honest
 * next thing while an ask is out). Only when every step ahead is the app's does one show.
 */
export function nextOf(entries: PlanEntry[]): PathStep | null {
  const ahead = entries.filter(
    (entry) => entry.item?.status !== "not_needed" && entry.step !== FINISHED && !entry.step.done,
  );
  return (ahead.find((entry) => entry.step.who !== "we") ?? ahead[0])?.step ?? null;
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
      // LP-972 — A WAIT IS NOT A TASK SHE DOES NOW: the next move is someone else's.
      if (item.option === "i_will_do_it" && item.waiting) {
        // Named as an ask's person is ("the borrower", "Title / escrow"), so one list reads one way.
        const who = askedWho(item);
        if (!out.waitingOn.includes(who)) out.waitingOn.push(who);
      } else if (item.option === "i_will_do_it") {
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

/**
 * LP-971 follow-up — THE PATH A STEP WILL ADD, before it is added: "Describe it" shows each proposed step
 * as the rows it becomes. The owner on 0006 added "two steps" and got eight rows, with nothing on screen
 * saying one email is five of them. A stand-in task with the step's own option, performer and checked
 * kinds, through `taskPath` itself, so the preview cannot drift from the path it previews.
 */
export function previewPath(task: {
  name: string;
  option: PlanOption;
  performer: Performer;
  waiting?: boolean;
  documentKinds: string[];
}): PathStep[] {
  return taskPath({
    id: "preview",
    key: "preview",
    name: task.name,
    acceptable: "",
    performer: task.performer,
    performers: [task.performer],
    option: task.option,
    status: "open",
    origin: "manual",
    need_id: null,
    need_title: null,
    shared_with_codes: [],
    document_id: null,
    document_name: null,
    document_page: null,
    waits_on_condition_id: null,
    waits_on_code: null,
    due_date: null,
    specifics: { amounts: [], account_bank: null, account_last4: null, month: null, names: [] },
    task: null,
    draft: null,
    waiting: task.waiting ?? false,
    document_kinds: task.documentKinds,
    has_checks: false,
  });
}

/** LP-971 follow-up — one task just added, and where it sits in the numbered path. */
export interface AddedPlace {
  item: ConditionItem;
  /** The path's numbers, 1-based, of the task's first and last step. */
  first: number;
  last: number;
}

/**
 * WHERE THE STEPS SHE JUST ADDED ARE (the owner on 0006: "it is confusing whether it was added or not").
 * The numbers are the timeline's own, read from the same entries it draws, so "steps 4 to 8" is what she
 * sees. A task with no step on the path (one already done) has no place and is left out.
 */
export function addedPlaces(entries: PlanEntry[], itemIds: readonly string[]): AddedPlace[] {
  const places: AddedPlace[] = [];
  for (const id of itemIds) {
    let first = 0;
    let last = 0;
    let item: ConditionItem | null = null;
    entries.forEach((entry, index) => {
      if (entry.item?.id !== id) return;
      item = entry.item;
      if (first === 0) first = index + 1;
      last = index + 1;
    });
    if (item !== null) places.push({ item, first, last });
  }
  return places;
}
