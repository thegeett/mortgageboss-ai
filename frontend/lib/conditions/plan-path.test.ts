import type { Condition, ConditionItem, PlanOption } from "@/lib/types/conditions";
import { describe, expect, it } from "vitest";
import {
  askedWho,
  conditionPath,
  endingPath,
  firstMoves,
  nextOf,
  ownStepPath,
  taskPath,
} from "./plan-path";

function item(overrides: Partial<ConditionItem>): ConditionItem {
  return {
    id: "i1",
    key: "k",
    name: "Thing",
    acceptable: "The thing itself",
    performer: "title",
    performers: ["title"],
    option: "ask_third_party",
    status: "open",
    origin: "reading",
    need_id: null,
    need_title: null,
    shared_with_codes: [],
    document_id: null,
    document_name: null,
    document_page: null,
    waits_on_condition_id: null,
    waits_on_code: null,
    due_date: null,
    specifics: {} as ConditionItem["specifics"],
    task: null,
    draft: null,
    ...overrides,
  };
}

const texts = (option: PlanOption, overrides: Partial<ConditionItem> = {}) =>
  taskPath(item({ option, ...overrides })).map((step) => step.text);

describe("plan path", () => {
  it("an ask: we draft on confirm, you send, they send it back, you link, we check", () => {
    const steps = taskPath(item({}));
    expect(steps.map((s) => [s.who, s.text])).toEqual([
      ["we", "We draft the email to Title / escrow when you confirm the plan"],
      ["you", "Review the email, and send it once the plan is confirmed"],
      ["them", "Title / escrow sends it back"],
      ["you", "Link it to this task"],
      ["we", "We check it against what was asked"],
    ]);
    expect(steps[0]?.detail).toBe(
      "It goes in the title email, with anything else asked of Title / escrow this round.",
    );
    expect(steps[4]?.detail).toBe("It should be: The thing itself.");
  });

  it("LP-968: a drafted ask says it is drafted and carries the draft to open", () => {
    const drafted = taskPath(
      item({ draft: { id: "d1", status: "draft", sent_on: null } as ConditionItem["draft"] }),
    );
    expect(drafted[0]).toMatchObject({
      text: "We drafted the email to Title / escrow",
      draftId: "d1",
    });
    // A reading that still needs her is kept out of the drafts, and the path says why.
    expect(taskPath(item({}), { needsConfirmation: true })[0]?.text).toBe(
      "We draft the email to Title / escrow once you confirm how we read this condition",
    );
    // A task she dropped has no path left.
    expect(taskPath(item({ status: "not_needed" }))).toEqual([]);
  });

  it("an ask names the server's recipient: an LO relay goes to the LO", () => {
    const relay = item({ performer: "borrower", performers: ["borrower", "lo"] });
    expect(askedWho(relay)).toBe("the LO");
    expect(taskPath(relay)[2]?.text).toBe("The LO sends it back");
  });

  it("a generic task promises no 'should be' line", () => {
    expect(taskPath(item({ generic: true }))[4]?.detail).toBeUndefined();
  });

  it("her own task names the library's task, then upload or mark done, then our check", () => {
    expect(texts("i_will_do_it", { task: "order the final inspection" })).toEqual([
      "Order the final inspection",
      "Upload what you get to this task, or mark the task done",
      "We check what you upload",
    ]);
    expect(texts("i_will_do_it", { name: "Inspection invoice" })[0]).toBe(
      "Do it: Inspection invoice",
    );
  });

  it("a task that waits on another condition starts there", () => {
    const steps = taskPath(item({ option: "i_will_do_it", waits_on_code: "1228" }));
    expect(steps[0]).toMatchObject({ who: "them", whoLabel: "Waiting on 1228" });
  });

  it("already in the file names the document and asks her to check it", () => {
    expect(
      texts("already_in_file", { document_name: "HR Loan Processing invoice", document_page: 1 }),
    ).toEqual([
      "We found HR Loan Processing invoice, page 1 on the file",
      "Check it’s the right document",
    ]);
  });

  it("a question on a single task says it does nothing there (LP-966 review)", () => {
    expect(texts("push_back")).toEqual(["This step does nothing on a single task"]);
  });

  it("a question is drafted when the plan is ready, and sent after confirm (LP-969)", () => {
    // `sync_round_drafts` makes the underwriter draft in the same pass as the others since LP-968;
    // "when you confirm" was left behind. Only the SEND waits for confirm.
    for (const own of ["ask_underwriter", "push_back"] as const) {
      const [drafted, send] = ownStepPath(own);
      expect(drafted?.text).not.toMatch(/when you confirm/);
      expect(drafted?.detail).toMatch(/^It is drafted once the plan is ready/);
      expect(send?.text).toMatch(/send it once the plan is confirmed$/);
    }
    // The push back cannot promise the argument: `render_question` writes only the HOI-date case.
    expect(ownStepPath("push_back")[1]?.text).toContain("say why it shouldn’t apply");
  });

  it("the condition's own question drafts to the underwriter; its own ask emails nothing itself", () => {
    expect(ownStepPath("push_back").map((s) => s.who)).toEqual(["we", "you", "lender"]);
    expect(ownStepPath("ask_borrower")[0]?.detail).toBe(
      "The tasks below set to ask are what go in the email.",
    );
  });

  it("every condition ends at the package and the lender, except information only", () => {
    const condition = { next_step: null } as Condition;
    expect(endingPath(condition).map((s) => s.who)).toEqual(["we", "lender"]);
    expect(endingPath({ next_step: "information_only" } as Condition)).toEqual([]);
  });

  it("a task's path starts where the task is, not at the beginning (LP-967 review)", () => {
    // The path is "every step from NOW", and it began at "We draft the email" however far along the
    // task was — so a task whose ask had gone, or whose document was already linked, described work
    // behind her as though it were ahead.
    const open = taskPath(item({ status: "open" })).map((s) => s.text);
    expect(open[0]).toBe("We draft the email to Title / escrow when you confirm the plan");

    // `requested`: the draft and the send have happened (`mark_sent`).
    const requested = taskPath(item({ status: "requested" })).map((s) => s.text);
    expect(requested[0]).toBe("Title / escrow sends it back");
    expect(requested).not.toContain("Review the email and send it");

    // `received`: a document is linked but has not passed its checks — a hand link is RECEIVED until
    // `check_link` (LP-953), so the check is the only step left.
    expect(taskPath(item({ status: "received" })).map((s) => s.text)).toEqual([
      "We check it against what was asked",
    ]);

    // `done`: nothing left, and an empty card would say nothing.
    expect(taskPath(item({ status: "done" })).map((s) => s.text)).toEqual([
      "This task is done — nothing left on it",
    ]);
    expect(
      taskPath(item({ option: "i_will_do_it", status: "received" })).map((s) => s.text),
    ).toEqual(["We check what you upload"]);

    // A WAITS-ON PREFIX SURVIVES THE TRIM, because it is not one of the task's own steps.
    const waiting = taskPath(item({ status: "requested", waits_on_code: "1228" }));
    expect(waiting[0]?.text).toBe("Starts once 1228 is done");
    expect(waiting[1]?.text).toBe("Title / escrow sends it back");

    // THE CONTROL: "Already in the file" is DONE by construction (`build_plan` sets both together),
    // so trimming it on `done` would empty the one card she most wants to read.
    expect(
      taskPath(item({ option: "already_in_file", status: "done" })).map((s) => s.text),
    ).toEqual(["We found it on the file", "Check it’s the right document"]);
  });

  it("does not promise this recipient when the condition asks two people (LP-967 review)", () => {
    // `_wait_on_first_asked` says it outright: "NOT whoever was emailed first" — the owner is the
    // recipient of the condition's FIRST live ask whose email has gone, "whichever email she happened
    // to mark sent first", its own example being 0132's LO disclosure before title's wire
    // instructions. So this step cannot promise its own recipient.
    const detail = taskPath(item({}))[1]?.detail ?? "";
    expect(detail).toContain("waiting on Title / escrow");
    // LP-973 review: "first" is the first whose email has GONE — `first_asked_owner` skips an ask
    // whose email has not been sent — not the first on the list.
    expect(detail).toContain("the first of them whose email you have sent");
  });

  it("the ending only promises the package where the tasks can settle it (LP-967 review)", () => {
    // `ready_because` returns None for ANY condition-level step that is not "Already in the file" or
    // "I'll do it", so finishing the tasks does not make such a condition Ready and it never reaches
    // `_goes_in`'s package that way. Only `information_only` was excluded.
    for (const own of [
      "lender_doing_it",
      "ask_underwriter",
      "push_back",
      "ask_borrower",
    ] as const) {
      const steps = endingPath({ next_step: own } as Condition);
      expect(steps.map((s) => s.who)).toEqual(["lender"]);
      expect(steps[0]?.text).toBe("The lender clears it");
    }
    // THE CONTROL: the three the tasks CAN settle still promise the package.
    for (const own of [null, "i_will_do_it", "already_in_file"] as const) {
      expect(endingPath({ next_step: own } as Condition).map((s) => s.who)).toEqual([
        "we",
        "lender",
      ]);
    }
    expect(endingPath({ next_step: "information_only" } as Condition)).toEqual([]);
  });

  it("first moves count what she does now, what waits, who we wait on, and what is handled", () => {
    // LP-967 REVIEW: `next_step: null` and, beside `already_in_file`, `status: "done"` — that is the
    // pair `build_plan` writes. The fixture said option-only with the default `open` status, which no
    // writer on the server produces, and `handled` was keyed on the option to match it.
    const rows = [
      { lender_code: "0006", next_step: null, items: [item({ option: "i_will_do_it" })] },
      {
        lender_code: "0007",
        next_step: null,
        items: [item({ option: "i_will_do_it", waits_on_code: "1228" })],
      },
      { lender_code: "1947", next_step: null, items: [item({}), item({ id: "i2" })] },
      {
        lender_code: "1582",
        next_step: null,
        items: [item({ option: "already_in_file", status: "done" })],
      },
      // Half in the file, half still asked: not handled.
      {
        lender_code: "6637",
        next_step: null,
        items: [
          item({ option: "already_in_file", status: "done" }),
          item({ id: "i9", performer: "borrower", performers: ["borrower"] }),
        ],
      },
      // ALL in the file but one document still being read: a hand link is RECEIVED until `check_link`
      // passes it (LP-953), so confirm will NOT mark this ready — and the box must not say it is
      // handled while the confirm summary leaves it out. Both read `willBeReady` now.
      {
        lender_code: "7086",
        next_step: null,
        items: [
          item({ option: "already_in_file", status: "done" }),
          item({ id: "i7", option: "already_in_file", status: "received" }),
        ],
      },
      {
        lender_code: "9999",
        next_step: null,
        items: [item({ option: "i_will_do_it", status: "not_needed" })],
      },
    ] as Condition[];
    expect(firstMoves(rows, [{ codes: ["1947"] }])).toEqual({
      emails: 1,
      tasksNow: 1,
      tasksLater: 1,
      waitingOn: ["Title / escrow", "the borrower"],
      handled: ["1582"],
    });
  });

  it("LP-974: one timeline per condition — its own step, each task's steps, then the ending", () => {
    const mine = item({ id: "m", option: "i_will_do_it", task: "upload the invoice" });
    const asked = item({ id: "a" });
    const entries = conditionPath({
      next_step: "i_will_do_it",
      items: [mine, asked],
    } as Condition);
    expect(entries.map((e) => [e.item?.id ?? null, e.leads, e.step.text])).toEqual([
      [null, true, "Do it, then mark each task below done"],
      ["m", true, "Upload the invoice"],
      ["m", false, "Upload what you get to this task, or mark the task done"],
      ["m", false, "We check what you upload"],
      ["a", true, "We draft the email to Title / escrow when you confirm the plan"],
      ["a", false, "Review the email, and send it once the plan is confirmed"],
      ["a", false, "Title / escrow sends it back"],
      ["a", false, "Link it to this task"],
      ["a", false, "We check it against what was asked"],
      [
        null,
        false,
        "When every task is done, the condition is ready and goes in the package for the lender",
      ],
      [null, false, "The lender clears it"],
    ]);
  });

  it("LP-974: a dropped task keeps one entry with her reason; with nothing live, no ending", () => {
    const dropped = item({ status: "not_needed", plan_note: "no fee charged" });
    const alone = conditionPath({ next_step: null, items: [dropped] } as Condition);
    expect(alone).toEqual([
      {
        step: { who: "you", whoLabel: "Not needed", text: "Thing", detail: "no fee charged" },
        item: dropped,
        leads: true,
      },
    ]);
    // THE CONTROL: beside a live task, the ending is back.
    const beside = conditionPath({
      next_step: null,
      items: [dropped, item({ id: "i2" })],
    } as Condition);
    expect(beside.at(-1)?.step.text).toBe("The lender clears it");
    // Nothing worked out at all: no entries.
    expect(conditionPath({ next_step: null, items: [] } as unknown as Condition)).toEqual([]);
  });

  it("LP-974: Next is the first step still ahead, past a dropped or finished task", () => {
    const entries = conditionPath({
      next_step: null,
      items: [
        item({ id: "x", status: "not_needed" }),
        item({ id: "y", option: "i_will_do_it", status: "done" }),
        item({ id: "z", status: "requested" }),
      ],
    } as Condition);
    expect(nextOf(entries)?.text).toBe("Title / escrow sends it back");
    // Every task finished: the ending is what comes next.
    const done = conditionPath({
      next_step: null,
      items: [item({ option: "i_will_do_it", status: "done" })],
    } as Condition);
    expect(nextOf(done)?.text).toBe(
      "When every task is done, the condition is ready and goes in the package for the lender",
    );
  });

  it("LP-972: a wait is someone else's next move, with the reminder date, then her upload and our check", () => {
    const wait = item({
      option: "i_will_do_it",
      performer: "title",
      performers: ["title"],
      name: "the payoff letter",
      waiting: true,
      due_date: "2026-10-15",
    });
    const steps = taskPath(wait);
    expect(steps.map((s) => [s.who, s.text])).toEqual([
      ["them", "Title / escrow sends the payoff letter"],
      ["you", "When it comes, upload or link it here, or mark the task done"],
      ["we", "We check what you upload"],
    ]);
    expect(steps[0]?.detail).toBe("If it hasn’t come by 10/15, it shows on your Reminders page.");
    // Received: it came and is being checked; only the check is left.
    expect(taskPath({ ...wait, status: "received" }).map((s) => s.text)).toEqual([
      "We check what you upload",
    ]);
    // In first moves it is someone to wait on, not a task she does now.
    const moves = firstMoves(
      [{ lender_code: "1947", next_step: null, items: [wait] } as Condition],
      [],
    );
    expect(moves).toMatchObject({ tasksNow: 0, waitingOn: ["Title / escrow"] });
  });
});
