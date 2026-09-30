/**
 * LP-921 — S3-12's Next step tokens and S3-01's "Becomes …" line, from the items the server sends.
 *
 * Items are built with the values the server emits (`PlanOption`, `ConditionItemStatus`), one per
 * S3-12 row, so each token below is the screen's own wording for that condition.
 */
import type { Condition, ConditionItem } from "@/lib/types/conditions";
import { describe, expect, it } from "vitest";
import {
  askRecipients,
  becomes,
  itemWhere,
  nextStepToken,
  stepOptions,
  tail,
  waitingLabel,
} from "./next-step";

function item(overrides: Partial<ConditionItem> = {}): ConditionItem {
  return {
    id: "i1",
    key: "statement",
    name: "Bank statement",
    acceptable: "All pages",
    performer: "borrower",
    performers: ["borrower"],
    option: "ask_borrower",
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
    specifics: { amounts: [], account_bank: null, account_last4: null, month: null, names: [] },
    task: null,
    draft: null,
    ...overrides,
  };
}

function condition(overrides: Partial<Condition> = {}): Condition {
  return {
    prep_status: "to_do",
    next_step: null,
    items: [],
    question_draft: null,
    ...overrides,
  } as Condition;
}

describe("nextStepToken (S3-12)", () => {
  it("1228: the lender is doing it, quietly", () => {
    expect(nextStepToken(condition({ next_step: "lender_doing_it" }))).toEqual({
      icon: "lender",
      text: "Lender is doing it",
      tone: "quiet",
    });
  });

  it("6178: a push-back is a question to the underwriter", () => {
    expect(nextStepToken(condition({ next_step: "push_back" }))?.text).toBe("Question to UW");
  });

  it("6637: borrower and title emails, one word each", () => {
    const items = [
      item({ key: "source" }),
      item({
        key: "receipt",
        performer: "title",
        performers: ["title"],
        option: "ask_third_party",
      }),
      item({ key: "clearance" }),
    ];
    expect(nextStepToken(condition({ items }))?.text).toBe("Borrower + title emails");
  });

  it("0132: the LO email carries the borrower's signature, and the attorney has its own", () => {
    const items = [
      item({ key: "disclosure", performers: ["borrower", "lo"], option: "ask_third_party" }),
      item({
        key: "preference",
        performer: "attorney",
        performers: ["attorney"],
        option: "ask_third_party",
      }),
    ];
    expect(nextStepToken(condition({ items }))?.text).toBe("LO + attorney emails");
  });

  it("1947: one email is 'In title email'", () => {
    const items = [item({ performer: "title", performers: ["title"], option: "ask_third_party" })];
    expect(nextStepToken(condition({ items }))?.text).toBe("In title email");
  });

  it("1582: her task, in the library's words", () => {
    const items = [
      item({ option: "i_will_do_it", performer: "processor", task: "upload the invoice" }),
    ];
    expect(nextStepToken(condition({ items }))).toEqual({
      icon: "task",
      text: "Your task · upload the invoice",
      tone: "quiet",
    });
  });

  it("0007: a task that waits says what on", () => {
    const items = [
      item({ option: "i_will_do_it", task: "upload the invoice", waits_on_code: "1228" }),
    ];
    expect(nextStepToken(condition({ items }))?.text).toBe("Waits on 1228");
  });

  it("0006: already in the file, with the page", () => {
    const items = [item({ option: "already_in_file", status: "done", document_page: 1 })];
    expect(nextStepToken(condition({ items }))?.text).toBe("Already in the file · p.1");
  });

  it("no plan, no token", () => {
    expect(nextStepToken(condition())).toBeNull();
  });

  it("a dropped item is not a step, and a done task is not a task", () => {
    const items = [
      item({ status: "not_needed" }),
      item({ option: "i_will_do_it", status: "done", task: "upload the invoice" }),
    ];
    expect(nextStepToken(condition({ items }))).toBeNull();
    expect(stepOptions(condition({ items }))).toEqual(["i_will_do_it"]);
  });
});

describe("stepOptions", () => {
  it("is the condition's own step and its items', once each", () => {
    const items = [item(), item({ option: "ask_third_party" }), item()];
    expect(stepOptions(condition({ next_step: "ask_underwriter", items }))).toEqual([
      "ask_underwriter",
      "ask_borrower",
      "ask_third_party",
    ]);
  });
});

describe("becomes (S3-01)", () => {
  it("6637: Waiting on Borrower when the borrower email is marked sent", () => {
    const items = [
      item(),
      item({ performer: "title", performers: ["title"], option: "ask_third_party" }),
    ];
    expect(becomes(condition({ items }))).toEqual({
      status: "Waiting on Borrower",
      when: "the borrower email is marked sent",
    });
  });

  it("0132: the LO email leaves us waiting on the LO", () => {
    const items = [item({ performers: ["borrower", "lo"], option: "ask_third_party" })];
    expect(becomes(condition({ items }))?.status).toBe("Waiting on LO");
  });

  it("a question waits on the lender", () => {
    expect(becomes(condition({ next_step: "ask_underwriter" }))).toEqual({
      status: "Waiting on Lender",
      when: "the question is marked sent",
    });
  });

  it("her task becomes Ready to send", () => {
    const items = [item({ option: "i_will_do_it" })];
    expect(becomes(condition({ items }))?.status).toBe("Ready to send");
  });

  it("says nothing for a display-only step or a condition already moved", () => {
    expect(becomes(condition({ next_step: "lender_doing_it" }))).toBeNull();
    expect(becomes(condition({ prep_status: "waiting", items: [item()] }))).toBeNull();
  });
});

describe("words", () => {
  it("the broker is the LO while we wait (M5)", () => {
    expect(waitingLabel("broker")).toBe("LO");
    expect(waitingLabel("borrower")).toBe("Borrower");
    expect(waitingLabel(null)).toBe("someone");
  });

  it("counts an appraiser's ask and a lender's as ONE lender email, waiting on the lender (LP-942)", () => {
    const appraiser = item({
      performer: "appraiser",
      performers: ["appraiser"],
      option: "ask_third_party",
    });
    const lender = item({
      id: "i2",
      performer: "lender",
      performers: ["lender"],
      option: "ask_third_party",
    });
    for (const items of [
      [appraiser, lender],
      [lender, appraiser],
    ]) {
      const both = condition({ items } as unknown as Partial<Condition>);
      expect(askRecipients(both)).toHaveLength(1);
      expect(nextStepToken(both)?.text).toBe("In lender email");
    }
    expect(
      becomes(condition({ items: [appraiser] } as unknown as Partial<Condition>))?.status,
    ).toBe("Waiting on Lender");
  });

  it("an ask says which email it is in; a task says nothing here", () => {
    expect(itemWhere(item())).toBe("In borrower email");
    expect(itemWhere(item({ option: "i_will_do_it" }))).toBeNull();
  });
});

describe("draft tails (LP-922)", () => {
  const drafted = { id: "d1", status: "draft" as const, sent_on: null };
  const sent = (on: string, id = "d1") => ({ id, status: "sent" as const, sent_on: on });

  it("reads · draft while any carrying draft is unsent", () => {
    const items = [
      item({ draft: sent("2026-08-28") }),
      item({
        performer: "title",
        performers: ["title"],
        option: "ask_third_party",
        draft: { ...drafted, id: "d2" },
      }),
    ];
    expect(nextStepToken(condition({ items }))?.text).toBe("Borrower + title emails · draft");
  });

  it("reads · sent 08/28 once every one was marked sent, and opens the draft", () => {
    const items = [
      item({ draft: sent("2026-08-28") }),
      item({
        performer: "title",
        performers: ["title"],
        option: "ask_third_party",
        draft: sent("2026-08-28", "d2"),
      }),
    ];
    const token = nextStepToken(condition({ items }));
    expect(token?.text).toBe("Borrower + title emails · sent 08/28");
    expect(token?.draftId).toBe("d1");
  });

  it("6178: the question's own tail", () => {
    const token = nextStepToken(
      condition({ next_step: "push_back", question_draft: sent("2026-08-28", "q1") }),
    );
    expect(token?.text).toBe("Question to UW · sent 08/28");
    expect(token?.draftId).toBe("q1");
  });

  it("an item says which email it is in, with its state", () => {
    expect(itemWhere(item({ draft: drafted }))).toBe("In borrower email · draft");
    expect(tail([])).toBe("");
  });
});

describe("evidence tokens (LP-923)", () => {
  it("a failed check comes first, red, naming what to ask for", () => {
    const token = nextStepToken(
      condition({
        items: [item({ draft: { id: "d1", status: "sent", sent_on: "2026-08-28" } })],
        evidence: [{ failed: true, reask: "page 6", checks: [], findings: [] }],
      } as unknown as Partial<Condition>),
    );
    expect(token).toMatchObject({ text: "Evidence failed a check — page 6", tone: "blocking" });
  });

  it("a deposit asked about reads as asked", () => {
    const token = nextStepToken(
      condition({
        evidence: [
          { failed: false, reask: null, checks: [], findings: [{ needed: true, status: "asked" }] },
        ],
      } as unknown as Partial<Condition>),
    );
    expect(token?.text).toBe("Deposit explanation asked");
  });

  it("skips a replaced upload's deposit, and keeps one on a statement still evidence (LP-937)", () => {
    const deposit = [{ needed: true, status: "open" }];
    const replaced = nextStepToken(
      condition({
        prep_status: "ready",
        evidence: [
          { failed: false, replaced: false, reask: null, checks: [], findings: [] },
          { failed: false, replaced: true, reask: null, checks: [], findings: deposit },
        ],
      } as unknown as Partial<Condition>),
    );
    expect(replaced?.text).toBe("Evidence checked");
    const stillEvidence = nextStepToken(
      condition({
        evidence: [{ failed: false, replaced: false, reask: null, checks: [], findings: deposit }],
      } as unknown as Partial<Condition>),
    );
    expect(stillEvidence?.text).toBe("Large deposit needs sourcing");
  });
});

it("a condition its evidence made Ready says so", () => {
  const token = nextStepToken(
    condition({
      prep_status: "ready",
      evidence: [{ failed: false, reask: null, checks: [], findings: [] }],
    } as unknown as Partial<Condition>),
  );
  expect(token?.text).toBe("Evidence checked");
});
