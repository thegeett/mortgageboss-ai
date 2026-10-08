import { OPTION_LABEL } from "@/lib/conditions/plan-words";
import { BUCKET_KIND_LABEL } from "@/lib/types/conditions";
import type { ConditionItem, PlanOption } from "@/lib/types/conditions";
import { describe, expect, it } from "vitest";
import {
  BUCKET_KIND_MEANING,
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
    expect(actionFor("ask_third_party", null)).toBe("Ask a third party — by email");
  });

  it("an ask's meaning names who; every other step reads its general meaning", () => {
    expect(meaningFor("ask_third_party", item({}))).toBe(
      "We put this request in the email to Title / escrow. You review the email first; once sent, the condition waits on them.",
    );
    expect(meaningFor("ask_third_party", null)).toBe(OPTION_MEANING.ask_third_party);
    expect(meaningFor("push_back", item({}))).toBe(OPTION_MEANING.push_back);
  });
});
