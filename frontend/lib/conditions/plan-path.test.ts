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

  it("first moves count what she does now, what waits, who we wait on, and what is handled", () => {
    const rows = [
      { lender_code: "0006", items: [item({ option: "i_will_do_it" })] },
      { lender_code: "0007", items: [item({ option: "i_will_do_it", waits_on_code: "1228" })] },
      { lender_code: "1947", items: [item({}), item({ id: "i2" })] },
      { lender_code: "1582", items: [item({ option: "already_in_file" })] },
      // Half in the file, half still asked: not handled.
      {
        lender_code: "6637",
        items: [
          item({ option: "already_in_file" }),
          item({ id: "i9", performer: "borrower", performers: ["borrower"] }),
        ],
      },
      { lender_code: "9999", items: [item({ option: "i_will_do_it", status: "not_needed" })] },
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
