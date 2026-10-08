import type { Condition, ConditionItem, PlanOption } from "@/lib/types/conditions";
import { describe, expect, it } from "vitest";
import { askedWho, endingPath, firstMoves, ownStepPath, taskPath } from "./plan-path";

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
      ["you", "Review the email and send it"],
      ["them", "Title / escrow sends it back"],
      ["you", "Link it to this task"],
      ["we", "We check it against what was asked"],
    ]);
    expect(steps[0]?.detail).toBe(
      "It goes in the title email, with anything else asked of Title / escrow this round.",
    );
    expect(steps[4]?.detail).toBe("It should be: The thing itself.");
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
    expect(detail).toContain("whichever of them it asks first");
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
});
