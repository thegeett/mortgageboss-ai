/**
 * LP-958 — the drawer's Next box: one sentence and one control per state, in the order the work runs.
 * The fixtures carry every field the server sends that the rule reads (lender_status, info_only,
 * superseded_by_id, evidence), never a value the server cannot emit.
 */
import type { Condition, ConditionItem } from "@/lib/types/conditions";
import { describe, expect, it } from "vitest";
import { goesInPackage, lenderAnswerLabel, nextAction } from "./next-action";

function item(overrides: Partial<ConditionItem> = {}): ConditionItem {
  return {
    id: "i1",
    key: "invoice",
    name: "Credit report invoice",
    acceptable: "The credit vendor's invoice",
    performer: "processor",
    performers: ["processor"],
    option: "i_will_do_it",
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
    lender_status: "open",
    info_only: false,
    superseded_by_id: null,
    next_step: null,
    items: [],
    evidence: [],
    question_draft: null,
    waiting_on: null,
    waiting_on_when_sent: null,
    ...overrides,
  } as Condition;
}

const UWM = { lender: "UWM", readyCount: 6 };

describe("nextAction", () => {
  it("Ready: send it to the lender in the package, with how many go with it", () => {
    expect(nextAction(condition({ prep_status: "ready" }), UWM)).toEqual({
      text: "Send it to UWM: build the lender package. It goes in with 5 other conditions that are ready.",
      do: { kind: "package" },
      tone: "action",
    });
    expect(
      nextAction(condition({ prep_status: "ready" }), { lender: "UWM", readyCount: 2 })?.text,
    ).toBe(
      "Send it to UWM: build the lender package. It goes in with 1 other condition that is ready.",
    );
    expect(nextAction(condition({ prep_status: "ready" }), { readyCount: 1 })?.text).toBe(
      "Send it to the lender: build the lender package.",
    );
  });

  it("Ready with an ask still in an unsent draft: send it, or mark the item not needed", () => {
    const asked = item({
      option: "ask_borrower",
      performers: ["borrower"],
      draft: { id: "dr1", status: "draft", sent_on: null },
    });
    expect(nextAction(condition({ prep_status: "ready", items: [asked] }), UWM)).toEqual({
      text: "It is Ready to send, but its email was never sent. Send it, or mark the item not needed.",
      do: { kind: "draft", draftId: "dr1" },
      tone: "blocking",
    });
    // A done ask is not doubtful, and neither is one already sent.
    for (const settled of [
      { ...asked, status: "done" as const },
      { ...asked, draft: { id: "dr1", status: "sent" as const, sent_on: "2026-10-01" } },
    ]) {
      expect(nextAction(condition({ prep_status: "ready", items: [settled] }), UWM)?.do).toEqual({
        kind: "package",
      });
    }
  });

  it("sent: record their answer — including one fixed and sent again (LP-958 review)", () => {
    const sent = {
      text: "Sent to UWM. When they answer, record it here.",
      do: { kind: "record" },
      tone: "waiting",
    };
    expect(nextAction(condition({ prep_status: "with_underwriter" }), UWM)).toEqual(sent);
    // THE RE-SEND. `lender_status` still holds the previous round's `not_cleared` until a new verdict
    // is recorded, and this used to answer "did not clear it … send it again" for a condition she had
    // just sent — and withhold the Record control, which is the part that cost her something.
    expect(
      nextAction(condition({ prep_status: "with_underwriter", lender_status: "not_cleared" }), UWM),
    ).toEqual(sent);
  });

  it("came back: the refusal is on a To do condition, which is where the server puts it", () => {
    // `condition_status.py:488` moves our track to To do on a `not_cleared` verdict from Ready or
    // Sent to lender, so this is the only state a came-back condition is ever in. The sentence used
    // to require `with_underwriter`, so it never appeared here at all.
    expect(
      nextAction(condition({ prep_status: "to_do", lender_status: "not_cleared" }), UWM),
    ).toEqual({
      text: "UWM did not clear it. Read their note, fix what it asks, then send it again.",
      tone: "blocking",
    });
    // THE CONTROL: an ordinary To do condition with work on it is not told the lender refused it.
    const ordinary = nextAction(
      condition({ prep_status: "to_do", items: [item({ id: "t1" })] }),
      UWM,
    );
    expect(ordinary?.text).toBeTruthy();
    expect(ordinary?.text).not.toContain("did not clear");
  });

  it("her open task: get it, by linking or asking, on that item", () => {
    const task = item({ id: "t1" });
    expect(
      nextAction(condition({ items: [item({ id: "x", status: "done" }), task] }), UWM),
    ).toEqual({
      text: "Get the credit report invoice: link it if it is already on the file, or ask someone for it.",
      do: { kind: "item", itemId: "t1" },
      tone: "action",
    });
    expect(nextAction(condition({ items: [item({ waits_on_code: "1228" })] }), UWM)).toEqual({
      text: "Waits on 1228: that condition comes first.",
      tone: "waiting",
    });
  });

  it("asks: send the unsent email, then wait on whoever it went to", () => {
    const ask = (status: "draft" | "sent") =>
      item({
        option: "ask_third_party",
        performers: ["title"],
        draft: { id: "dt", status, sent_on: status === "sent" ? "2026-10-01" : null },
      });
    expect(nextAction(condition({ items: [ask("draft")] }), UWM)).toEqual({
      text: "Send the title email.",
      do: { kind: "draft", draftId: "dt" },
      tone: "action",
    });
    expect(
      nextAction(
        condition({ items: [ask("sent")], prep_status: "waiting", waiting_on: "title" }),
        UWM,
      ),
    ).toEqual({ text: "Waiting on Title: the email was sent.", tone: "waiting" });
  });

  it("a question to the underwriter: send it, then wait with its date", () => {
    const step = { next_step: "ask_underwriter" as const };
    expect(
      nextAction(
        condition({ ...step, question_draft: { id: "q", status: "draft", sent_on: null } }),
      ),
    ).toEqual({
      text: "Send the question to the underwriter.",
      do: { kind: "draft", draftId: "q" },
      tone: "action",
    });
    expect(
      nextAction(
        condition({ ...step, question_draft: { id: "q", status: "sent", sent_on: "2026-10-02" } }),
      )?.text,
    ).toBe("Waiting on the underwriter: the question was sent 10/02.");
    expect(
      nextAction(condition({ ...step, question_draft: { id: "q", status: "sent", sent_on: null } }))
        ?.text,
    ).toBe("Waiting on the underwriter: the question was sent.");
  });

  it("what arrived and failed outranks Ready and the plan", () => {
    const failed = {
      failed: true,
      reask: "page 6 is missing",
      checks: [],
      findings: [],
    } as unknown as Condition["evidence"][number];
    const action = nextAction(
      condition({ prep_status: "ready", items: [item()], evidence: [failed] }),
      UWM,
    );
    expect(action?.tone).toBe("blocking");
    expect(action?.text).toBe(
      "A document failed a check: page 6 is missing. Fix it in the document card below, or link a different one.",
    );
  });

  it("the lender's answer ends it; a replaced one has no box; information only says so", () => {
    expect(nextAction(condition({ lender_status: "cleared", prep_status: "ready" }), UWM)).toEqual({
      text: "UWM cleared it. Nothing left to do.",
      tone: "done",
    });
    expect(nextAction(condition({ lender_status: "waived" }), UWM)?.text).toBe(
      "UWM waived it. Nothing left to do.",
    );
    expect(
      nextAction(condition({ superseded_by_id: "other", prep_status: "ready" }), UWM),
    ).toBeNull();
    expect(nextAction(condition({ info_only: true }), UWM)?.tone).toBe("done");
  });

  it("the lender doing it, already in the file, and no plan", () => {
    expect(nextAction(condition({ next_step: "lender_doing_it" }), UWM)?.text).toBe(
      "UWM is doing this one. Nothing to do until they answer.",
    );
    expect(nextAction(condition({ items: [item({ option: "already_in_file" })] }), UWM)?.text).toBe(
      "It is already in the file. Check the document, then set it Ready to send.",
    );
    expect(nextAction(condition(), UWM)).toBeNull();
  });
});

describe("goesInPackage mirrors condition_package._goes_in", () => {
  it.each([
    [{ prep_status: "ready" }, true],
    [{ prep_status: "ready", lender_status: "not_cleared" }, true],
    [{ prep_status: "ready", lender_status: "cleared" }, false],
    [{ prep_status: "ready", info_only: true }, false],
    [{ prep_status: "waiting" }, false],
  ] as const)("%o → %s", (overrides, want) => {
    expect(goesInPackage(condition(overrides as Partial<Condition>))).toBe(want);
  });
});

it("lenderAnswerLabel: open reads Not cleared yet, every other answer keeps its own word", () => {
  expect(lenderAnswerLabel("open", "Open")).toBe("Not cleared yet");
  expect(lenderAnswerLabel("not_cleared", "Came back")).toBe("Came back");
  expect(lenderAnswerLabel("cleared", "Cleared")).toBe("Cleared");
});
