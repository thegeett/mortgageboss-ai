import { OPTION_LABEL } from "@/lib/conditions/plan-words";
import { BUCKET_KIND_LABEL } from "@/lib/types/conditions";
import type { ConditionItem, PlanOption } from "@/lib/types/conditions";
import { describe, expect, it } from "vitest";
import {
  BUCKET_KIND_MEANING,
  ITEM_OPTION_ORDER,
  OPTION_EXAMPLE,
  OPTION_MEANING,
  OPTION_ORDER,
  actionFor,
  meaningFor,
} from "./step-meaning";

function item(overrides: Partial<ConditionItem>): ConditionItem {
  return {
    id: "i1",
    key: "k",
    name: "Thing",
    acceptable: "",
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

describe("step meanings", () => {
  it("does not promise readiness from one task alone (LP-966 review)", () => {
    // `condition_plan.ready_because` needs EVERY live item DONE, so neither of these steps makes a
    // multi-task condition ready on its own. Both sentences used to say "once you mark it done" /
    // "when you confirm", which is true only of a condition with nothing else on it.
    for (const option of ["i_will_do_it", "already_in_file"] as const) {
      expect(OPTION_MEANING[option]).toContain("every task");
    }
    // THE CONTROL: the steps that genuinely do not wait on the tasks say nothing of the sort.
    expect(OPTION_MEANING.information_only).not.toContain("every task");
    expect(OPTION_MEANING.lender_doing_it).not.toContain("every task");
  });

  it("offers a task only the steps a task can be (LP-966 review)", () => {
    // Every `_QUESTIONS` use on the server reads the CONDITION's next_step
    // (condition_drafts.py:739, :747, :818, :1116) and nothing reads an item's, so an item set to one
    // is in no email, raises no question and is not her task: it belongs nowhere.
    expect(ITEM_OPTION_ORDER).not.toContain("ask_underwriter");
    expect(ITEM_OPTION_ORDER).not.toContain("push_back");
    // THE CONTROL, both ways: the whole condition still offers all eight, and a task still offers
    // every step it can actually be — so this is a narrowing of one list, not of the feature.
    expect(OPTION_ORDER).toContain("ask_underwriter");
    expect(OPTION_ORDER).toContain("push_back");
    expect(OPTION_ORDER).toHaveLength(8);
    for (const each of [
      "i_will_do_it",
      "ask_borrower",
      "ask_third_party",
      "already_in_file",
    ] as const) {
      expect(ITEM_OPTION_ORDER).toContain(each);
    }
  });

  it("explains every step the app has, and lists each once in the dialog", () => {
    // Derived from the label map, so a ninth step without words fails here, not on her screen.
    const every = Object.keys(OPTION_LABEL) as PlanOption[];
    expect([...OPTION_ORDER].sort()).toEqual([...every].sort());
    for (const option of every) {
      expect(OPTION_MEANING[option]).toBeTruthy();
      expect(OPTION_EXAMPLE[option]).toBeTruthy();
    }
  });

  it("explains every lender heading's timing", () => {
    for (const kind of Object.keys(BUCKET_KIND_LABEL) as (keyof typeof BUCKET_KIND_LABEL)[]) {
      expect(BUCKET_KIND_MEANING[kind]).toBeTruthy();
    }
  });

  it("names the task she does, from the library", () => {
    expect(actionFor("i_will_do_it", item({ task: "order the final inspection" }))).toBe(
      "You order the final inspection",
    );
    expect(actionFor("i_will_do_it", item({ task: null }))).toBe("You do it");
  });

  it("names the email an ask goes in, as the server groups them", () => {
    expect(actionFor("ask_third_party", item({}))).toBe("Ask Title / escrow — in the title email");
    // A borrower + LO item goes to the LO (recipient_for's relay), not the borrower.
    expect(
      actionFor("ask_third_party", item({ performer: "borrower", performers: ["borrower", "lo"] })),
    ).toBe("Ask the LO — in the LO email");
    // LP-942: appraisal requests go through the lender.
    expect(
      actionFor("ask_third_party", item({ performer: "appraiser", performers: ["appraiser"] })),
    ).toBe("Ask the lender — in the lender email");
    // LP-966 REVIEW: the whole condition's ask names NO email. This asserted "by email", which is a
    // claim the server does not keep — drafts are built from ITEMS, so a condition-level ask whose
    // tasks are not asks puts nothing in any email.
    expect(actionFor("ask_third_party", null)).toBe(
      "Ask someone else — the tasks below are what go in the email",
    );
    expect(actionFor("ask_borrower", null)).toBe(
      "Ask the borrower — the tasks below are what go in the email",
    );
    // A TASK still names its own email, which is the half that is true.
    expect(actionFor("ask_borrower", item({}))).toBe("Ask the borrower — in the borrower email");
  });

  it("an ask's meaning names who; every other step reads its general meaning", () => {
    expect(meaningFor("ask_third_party", item({}))).toBe(
      "We put this request in the email to Title / escrow. You review the email first; once sent, the condition waits on them.",
    );
    // LP-966 review: for the WHOLE CONDITION an ask's meaning says what reaches the email — the
    // tasks — rather than `OPTION_MEANING`'s task-shaped promise of one.
    for (const option of ["ask_borrower", "ask_third_party"] as const) {
      const meaning = meaningFor(option, null);
      expect(meaning).not.toBe(OPTION_MEANING[option]);
      expect(meaning).toContain("each task below that is itself set to ask");
    }
    expect(meaningFor("push_back", item({}))).toBe(OPTION_MEANING.push_back);
  });
});
