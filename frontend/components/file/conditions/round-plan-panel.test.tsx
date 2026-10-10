import type {
  Condition,
  ConditionItem,
  ConditionRound,
  DescribeResult,
  PlanOption,
  RoundPlan,
} from "@/lib/types/conditions";
// @vitest-environment jsdom
/**
 * S3-02 (LP-920), explained (LP-966): the plan says what to do on the screen, each condition opens to
 * "What you need to do", every step select carries its meaning and an ⓘ to all eight, and "When you
 * confirm, we will:" says what Confirm does. Confirm is still held while a reading needs her.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const plan = vi.hoisted(() => ({ data: undefined as RoundPlan | undefined }));
const calls = vi.hoisted(() => ({
  items: [] as unknown[],
  steps: [] as unknown[],
  reverts: [] as unknown[],
  added: [] as unknown[],
  described: [] as unknown[],
  logged: [] as unknown[],
  confirms: [] as unknown[],
  ownWay: [] as unknown[],
  removed: [] as unknown[],
  /** LP-969 — what the add call answers with, so "Check a document" can find the new task. */
  addResponse: null as Condition | null,
  /**
   * LP-971 REVIEW — one answer PER CALL, in order, each the condition as it stands after that add.
   * A single fixed `addResponse` cannot show what "Add these N steps" does, because the thing being
   * tested is which item each response identifies as the new one.
   */
  addResponses: [] as Condition[],
  /** LP-971 — what "Turn it into steps" comes back with. */
  describeResult: null as DescribeResult | null,
}));
vi.mock("@/lib/api/conditions", () => ({
  useRoundPlan: () => ({ data: plan.data }),
  useConfirmPlan: () => ({
    mutate: (body: unknown) => calls.confirms.push(body),
    isPending: false,
  }),
  useSetNextStep: () => ({ mutate: (body: unknown) => calls.steps.push(body) }),
  useUpdateItem: () => ({ mutate: (body: unknown) => calls.items.push(body) }),
  useRevertPlan: () => ({ mutate: (id: unknown) => calls.reverts.push(id), isPending: false }),
  useLogCall: () => ({
    mutate: (body: unknown, options?: { onSuccess?: () => void }) => {
      calls.logged.push(body);
      options?.onSuccess?.();
    },
    isPending: false,
  }),
  useDescribeSteps: () => ({
    mutate: (body: unknown, options?: { onSuccess?: (r: DescribeResult) => void }) => {
      calls.described.push(body);
      if (calls.describeResult) options?.onSuccess?.(calls.describeResult);
    },
    isPending: false,
  }),
  useAddItem: () => ({
    // `onSettled` IS PART OF THE CONTRACT, and this mock did not call it. The panel serialises a batch
    // of adds on it (LP-971 review), so a mock that only calls `onSuccess` would leave the queue
    // stuck after the first step and the test would be measuring the mock.
    mutate: (
      body: unknown,
      options?: { onSuccess?: (data: Condition) => void; onSettled?: () => void },
    ) => {
      calls.added.push(body);
      const next = calls.addResponses.shift() ?? calls.addResponse;
      if (next) options?.onSuccess?.(next);
      options?.onSettled?.();
    },
    isPending: false,
  }),
  useOwnWay: () => ({ mutate: (id: unknown) => calls.ownWay.push(id), isPending: false }),
  useRemoveItem: () => ({ mutate: (body: unknown) => calls.removed.push(body), isPending: false }),
  useUploadToItem: () => ({ mutate: vi.fn(), isPending: false }),
  useLinkCandidates: () => ({ data: undefined, isLoading: false }),
  useLinkItemDocument: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { RoundPlanPanel } from "./round-plan-panel";

afterEach(() => {
  cleanup();
  calls.items = [];
  calls.steps = [];
  calls.reverts = [];
  calls.added = [];
  calls.confirms = [];
  calls.ownWay = [];
  calls.removed = [];
  calls.addResponse = null;
  calls.addResponses = [];
  calls.describeResult = null;
  calls.described = [];
  calls.logged = [];
});

const basePlan: RoundPlan = {
  round_id: "r1",
  round_number: 1,
  round_date: "2026-08-28",
  planned: 11,
  ready_at: "2026-08-28T20:21:00Z",
  confirmed_at: null,
  nothing_sent: true,
  drafts: [
    { recipient: "borrower", label: "Borrower", codes: ["7086"] },
    { recipient: "title_attorney", label: "Title/attorney", codes: ["1947"] },
    { recipient: "lo", label: "LO", codes: ["0132"] },
  ],
  your_tasks: 2,
  already_in_file: 1,
  push_back: 1,
  lender_doing_it: 1,
  needs_confirmation: 1,
  blocking_codes: ["0132"],
};

const round = { id: "r1", status: "imported" } as ConditionRound;

function item(overrides: Partial<ConditionItem>): ConditionItem {
  return {
    id: "i1",
    key: "invoice",
    name: "Credit report invoice",
    acceptable: "The credit vendor's invoice for this file",
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
    specifics: {} as ConditionItem["specifics"],
    task: "upload the invoice",
    draft: null,
    ...overrides,
  };
}

function condition(overrides: Partial<Condition>): Condition {
  return {
    id: "c1",
    lender_code: "0006",
    bucket_kind: "prior_to_funding",
    verbatim_text: "Provide copy of invoice for credit report.",
    sequence: 1,
    first_round_id: "r1",
    last_seen_round_id: "r1",
    reading_status: "ready",
    reading: {
      summary: "Credit report invoice",
      explanation: "The lender needs a copy of the credit report invoice.",
    },
    next_step: null,
    plan_reason: null,
    library_type: {
      id: "IV-01",
      name: "Credit report invoice",
      label: "IV-01 Credit report invoice",
      rule_label: "Lender requirement",
      rule_note: null,
      playbook: "Usually already in the file from when credit was pulled; point to it.",
    },
    items: [item({})],
    ...overrides,
  } as Condition;
}

const TITLE_ITEM = item({
  id: "i2",
  key: "seller_cd",
  name: "Final seller Closing Disclosure",
  acceptable: "The final seller CD, with the closing package",
  performer: "title",
  performers: ["title"],
  option: "ask_third_party",
  task: null,
});

function show(
  conditions: Condition[],
  data: RoundPlan = basePlan,
  confirmedRoundIds?: ReadonlySet<string>,
) {
  plan.data = data;
  render(
    <RoundPlanPanel
      fileId="f1"
      round={round}
      conditions={conditions}
      onOpenCondition={vi.fn()}
      onConfirmReading={vi.fn()}
      confirmedRoundIds={confirmedRoundIds ?? new Set()}
    />,
  );
}

function unblocked(): RoundPlan {
  return { ...basePlan, blocking_codes: [], needs_confirmation: 0, drafts: [] };
}

describe("RoundPlanPanel", () => {
  it("says what to do on the screen and holds Confirm while 0132's reading needs her", () => {
    show([condition({}), condition({ id: "c2", lender_code: "0132", sequence: 2 })]);
    // LP-974 — the mockup's heading and sentence; the three numbered how-to steps are gone.
    expect(screen.getByText("Here’s how we’ll get these 2 conditions cleared")).toBeTruthy();
    expect(screen.getByText("Plan for round 1")).toBeTruthy();
    expect(screen.getByText(/then confirm\. Nothing is sent until you do\./)).toBeTruthy();
    expect(screen.queryByText(/Open each condition/)).toBeNull();
    // LP-967 — "Your first moves" replaces the pills: the plan's three drafts are the first thing to do.
    expect(screen.getByText("Your first moves")).toBeTruthy();
    expect(screen.getByText(/^Review the 3 drafted emails/)).toBeTruthy();
    const confirm = screen.getByRole("button", { name: "Confirm the plan" });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    expect(
      screen.getByText("Confirm 0132’s reading first — one condition still needs you."),
    ).toBeTruthy();
  });

  // LP-976 REVIEW — a blocker with no lender code arrives as an em dash, and the hand-added condition
  // this ticket is about has no code. "Confirm —'s reading first" is not a sentence she can act on.
  it("describes a code-less blocker instead of naming a dash", () => {
    show([condition({})], { ...basePlan, blocking_codes: ["\u2014"] });
    expect(
      screen.getByText("Check how we read it first — one condition still needs you."),
    ).toBeTruthy();
    expect(screen.queryByText(/Confirm —/)).toBeNull();
  });

  it("names the coded blocker when a file has both kinds, wherever it sits", () => {
    // The list is unordered: the server's query has no `order_by`, so the dash can come first.
    show([condition({})], { ...basePlan, blocking_codes: ["\u2014", "1947"] });
    expect(
      screen.getByText("Confirm 1947’s reading first — 2 conditions still need you."),
    ).toBeTruthy();
  });

  it("is gone once the plan is confirmed", () => {
    plan.data = { ...basePlan, confirmed_at: "2026-08-28T20:40:00Z", blocking_codes: [] };
    const { container } = render(
      <RoundPlanPanel
        confirmedRoundIds={new Set()}
        fileId="f1"
        round={round}
        conditions={[]}
        onOpenCondition={vi.fn()}
        onConfirmReading={vi.fn()}
      />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("collapsed, says the route and the next step (LP-974)", () => {
    show([
      condition({}),
      condition({ id: "c2", lender_code: "1947", sequence: 2, items: [TITLE_ITEM] }),
      condition({
        id: "c3",
        lender_code: "0007",
        sequence: 3,
        items: [item({ id: "i3", name: "Inspection invoice", waits_on_code: "1228" })],
      }),
      condition({
        id: "c4",
        lender_code: "1582",
        sequence: 4,
        items: [
          item({
            id: "i4",
            name: "Processing invoice",
            option: "already_in_file",
            document_name: "HR Loan Processing invoice",
            document_page: 1,
          }),
        ],
      }),
    ]);
    // "Route:" is what the tasks' steps say (until LP-970's routes); "Next:" is the first step ahead.
    expect(screen.getAllByText("Route:")).toHaveLength(4);
    expect(screen.getAllByText("You upload the invoice")).toHaveLength(2);
    expect(screen.getByText("Ask Title / escrow — in the title email")).toBeTruthy();
    expect(screen.getByText("Upload the invoice")).toBeTruthy();
    expect(screen.getByText("Starts once 1228 is done")).toBeTruthy();
    expect(
      screen.getByText("We found HR Loan Processing invoice, page 1 on the file"),
    ).toBeTruthy();
    // 1947's ask: the draft does not exist yet, so its next step says when it will.
    expect(
      screen.getByText("We draft the email to Title / escrow when you confirm the plan"),
    ).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "See the plan" })).toHaveLength(4);
    // Nothing of the detail until she opens it.
    expect(screen.queryByText("What the lender wants")).toBeNull();
  });

  it("opens a condition to what the lender wants, when, the words, done-when and good to know", () => {
    show([condition({})], unblocked());
    fireEvent.click(screen.getByRole("button", { name: "See the plan" }));

    expect(screen.getByText("The lender needs a copy of the credit report invoice.")).toBeTruthy();
    expect(
      screen.getByText(/needed before the loan funds, after closing documents are drawn\./),
    ).toBeTruthy();
    expect(screen.getByText("Provide copy of invoice for credit report.")).toBeTruthy();
    expect(screen.getByText(/The credit vendor's invoice for this file/)).toBeTruthy();
    expect(
      screen.getByText(/Usually already in the file from when credit was pulled/),
    ).toBeTruthy();
    // The meaning of the chosen step, under its select.
    expect(screen.getByText(/You do this yourself\. It goes on your task list/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Hide the plan" }));
    expect(screen.queryByText("What the lender wants")).toBeNull();
  });

  it("an ask's meaning names who it goes to", () => {
    show([condition({ lender_code: "1947", items: [TITLE_ITEM] })], unblocked());
    fireEvent.click(screen.getByRole("button", { name: "See the plan" }));
    expect(screen.getByText(/We put this request in the email to Title \/ escrow\./)).toBeTruthy();
  });

  it("each Next step select is named by its own task (LP-974 review)", () => {
    // The visible label is "Next step" on every row, with the task name in a span beside it that
    // nothing tied to the control — so a screen reader announced three identical combo boxes and she
    // could not tell which task she was changing. `aria-labelledby` over the name and the label makes
    // each one's accessible name its own.
    const second = item({ id: "i9", name: "Second task", option: "i_will_do_it" });
    show([condition({ next_step: "push_back", items: [item({}), second] })], unblocked());
    fireEvent.click(screen.getByRole("button", { name: "See the plan" }));

    const named = screen.getAllByRole("combobox").map((el) => el.getAttribute("aria-labelledby"));
    expect(named.every(Boolean)).toBe(true);
    // Each name leads with its own row's heading, so the three are distinguishable.
    expect(screen.getByRole("combobox", { name: /^Second task Next step$/ })).toBeTruthy();
    expect(screen.getByRole("combobox", { name: /^The whole condition Next step$/ })).toBeTruthy();
    // THE CONTROL: the visible label is still "Next step" and still tied by `htmlFor`, so the three
    // remain findable that way too — this adds a name rather than replacing one.
    expect(screen.getAllByLabelText("Next step")).toHaveLength(3);
  });

  it("changes ONE task's step, and the condition's own step through its own call", () => {
    const second = item({ id: "i9", name: "Second task", option: "i_will_do_it" });
    show([condition({ next_step: "push_back", items: [item({}), second] })], unblocked());
    fireEvent.click(screen.getByRole("button", { name: "See the plan" }));
    const selects = screen.getAllByLabelText("Next step");
    expect(selects).toHaveLength(3); // the whole condition, then each task

    fireEvent.change(selects[2] as HTMLSelectElement, { target: { value: "ask_borrower" } });
    expect(calls.items).toEqual([{ conditionId: "c1", itemId: "i9", option: "ask_borrower" }]);

    fireEvent.change(selects[0] as HTMLSelectElement, { target: { value: "ask_underwriter" } });
    expect(calls.steps).toEqual([{ conditionId: "c1", next_step: "ask_underwriter" }]);
  });

  it("a task is not offered the whole condition's questions, but keeps one it already has", () => {
    // LP-966 REVIEW, at the layer it shows: every `_QUESTIONS` use on the server reads the CONDITION's
    // next_step (condition_drafts.py:739, :747, :818, :1116), so a TASK set to `ask_underwriter` or
    // `push_back` is in no email, raises no question draft and is not her task — it belongs nowhere,
    // while the meaning line under its select promised a question to the underwriter.
    const stale = item({ id: "i8", name: "Already a question", option: "push_back" });
    const ordinary = item({ id: "i9", name: "Second task", option: "i_will_do_it" });
    show([condition({ next_step: "push_back", items: [stale, ordinary] })], unblocked());
    fireEvent.click(screen.getByRole("button", { name: "See the plan" }));
    const selects = screen.getAllByLabelText("Next step") as HTMLSelectElement[];
    const values = (select: HTMLSelectElement) => [...select.options].map((o) => o.value);

    // The whole condition keeps all eight: a question is about the condition, and that is where it lives.
    expect(values(selects[0] as HTMLSelectElement)).toHaveLength(8);
    expect(values(selects[0] as HTMLSelectElement)).toContain("ask_underwriter");

    // An ordinary task is offered neither question, and still every step it can actually be.
    const task = values(selects[2] as HTMLSelectElement);
    expect(task).not.toContain("ask_underwriter");
    expect(task).not.toContain("push_back");
    expect(task).toContain("ask_borrower");
    expect(task).toContain("i_will_do_it");
    expect(task).toContain("already_in_file");

    // A task ALREADY holding one still lists it, or the select would render blank against a value
    // outside its options and hide what the item is. She can move it off; nothing new lands on it.
    const held = values(selects[1] as HTMLSelectElement);
    expect(held).toContain("push_back");
    expect(held).not.toContain("ask_underwriter");
    expect(selects[1]?.value).toBe("push_back");
  });

  it("the ⓘ opens all eight steps with the current one marked, and Got it closes it", () => {
    show([condition({ lender_code: "1947", items: [TITLE_ITEM] })], unblocked());
    fireEvent.click(screen.getByRole("button", { name: "See the plan" }));
    fireEvent.click(screen.getByRole("button", { name: "What the next steps mean" }));

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/For Final seller Closing Disclosure \(1947\)\./)).toBeTruthy();
    const items = within(dialog).getAllByRole("listitem");
    expect(items).toHaveLength(8);
    const marked = items.filter((li) => within(li).queryByText("Selected"));
    expect(marked).toHaveLength(1);
    expect(within(marked[0] as HTMLElement).getByText("Ask a third party")).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("button", { name: "Got it" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("offers no way to check a reading that never happened (LP-966 review)", () => {
    // `ConfirmReadingDialog` opens on `condition.reading` and returns null without one, so on a
    // condition that was never read — the likeliest reason a row has no items and no step — "Check how
    // we read it" opened a dialog that renders nothing. A dead control on the one row whose purpose is
    // to say what to do next is worse than no control.
    const onConfirmReading = vi.fn();
    plan.data = basePlan;
    render(
      <RoundPlanPanel
        confirmedRoundIds={new Set()}
        fileId="f1"
        round={round}
        conditions={[
          condition({}),
          condition({
            id: "c3",
            lender_code: "9001",
            sequence: 3,
            items: [],
            next_step: null,
            reading: null,
          }),
        ]}
        onOpenCondition={vi.fn()}
        onConfirmReading={onConfirmReading}
      />,
    );

    expect(screen.getByRole("button", { name: "9001" })).toBeTruthy();
    expect(
      screen.getByText("We haven’t read this one yet, so there is nothing to plan for it."),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Check how we read it" })).toBeNull();
    // THE CONTROL: the row that DOES have a reading still offers it — see the test below, which
    // renders the same shape with a reading and asserts exactly one such button.
  });

  it("shows a condition with nothing worked out, with one way to fix it", () => {
    // The failed reading on LF-Y36E: 1947 blocked Confirm and was not on the screen.
    const onConfirmReading = vi.fn();
    plan.data = basePlan;
    render(
      <RoundPlanPanel
        confirmedRoundIds={new Set()}
        fileId="f1"
        round={round}
        conditions={[
          condition({}),
          condition({
            id: "c2",
            lender_code: "1947",
            sequence: 2,
            items: [],
            next_step: null,
            reading_status: "needs_confirmation",
          }),
        ]}
        onOpenCondition={vi.fn()}
        onConfirmReading={onConfirmReading}
      />,
    );
    expect(screen.getByRole("button", { name: "1947" })).toBeTruthy();
    expect(screen.getByText("We couldn’t work out what this one needs.")).toBeTruthy();
    const fix = screen.getAllByRole("button", { name: "Check how we read it" });
    expect(fix).toHaveLength(1);
    fireEvent.click(fix[0] as HTMLElement);
    expect(onConfirmReading).toHaveBeenCalledWith("c2");
  });

  it("opens a task to its path: who does each step, from now until it is checked (LP-967)", () => {
    show([condition({ lender_code: "1947", items: [TITLE_ITEM] })], unblocked());
    fireEvent.click(screen.getByRole("button", { name: "See the plan" }));
    const path = within(screen.getByRole("list", { name: "The plan, step by step" }));
    expect(
      path.getByText("We draft the email to Title / escrow when you confirm the plan"),
    ).toBeTruthy();
    expect(
      screen.getByText("Review the email, and send it once the plan is confirmed"),
    ).toBeTruthy();
    expect(screen.getByText("Title / escrow sends it back")).toBeTruthy();
    expect(screen.getByText("Link it to this task")).toBeTruthy();
    expect(
      screen.getByText("It should be: The final seller CD, with the closing package."),
    ).toBeTruthy();
    // The shared ending.
    expect(
      screen.getByText(
        "When every task is done, the condition is ready and goes in the package for the lender",
      ),
    ).toBeTruthy();
    expect(screen.getByText("The lender clears it")).toBeTruthy();
  });

  it("the path follows the task's step: the same task as her own job reads as her steps", () => {
    const mine = { ...TITLE_ITEM, option: "i_will_do_it" as PlanOption, task: "upload the CD" };
    show([condition({ lender_code: "1947", items: [mine] })], unblocked());
    fireEvent.click(screen.getByRole("button", { name: "See the plan" }));
    // Once in the timeline, once as the collapsed row's "Next:".
    expect(screen.getAllByText("Upload the CD")).toHaveLength(2);
    expect(
      screen.queryByText("Review the email, and send it once the plan is confirmed"),
    ).toBeNull();
  });

  it("first moves: emails, tasks now, tasks waiting, who we wait on, what is in the file", () => {
    show(
      [
        condition({}),
        condition({ id: "c2", lender_code: "1947", sequence: 2, items: [TITLE_ITEM] }),
        condition({
          id: "c3",
          lender_code: "0007",
          sequence: 3,
          items: [item({ id: "i3", name: "Inspection invoice", waits_on_code: "1228" })],
        }),
        condition({
          id: "c4",
          lender_code: "1582",
          sequence: 4,
          // LP-967 review: `status: "done"` beside the option, which is the pair `build_plan` writes
          // and what `willBeReady` — shared now with the confirm summary — reads.
          items: [item({ id: "i4", option: "already_in_file", status: "done" })],
        }),
      ],
      { ...basePlan, blocking_codes: [], drafts: [basePlan.drafts[1] as RoundPlan["drafts"][0]] },
    );
    expect(
      screen.getByText(
        "Review the 1 drafted email, then do 1 task yourself. 1 more task waits on another condition.",
      ),
    ).toBeTruthy();
    expect(screen.getByText("Title / escrow.")).toBeTruthy();
    expect(screen.getByText("1582.")).toBeTruthy();
  });

  // --- LP-968: drafts with the plan, and her edits ------------------------------------------- //

  function open(conditions: Condition[], onOpenDraft = vi.fn()) {
    plan.data = unblocked();
    render(
      <RoundPlanPanel
        confirmedRoundIds={new Set()}
        fileId="f1"
        round={round}
        conditions={conditions}
        onOpenCondition={vi.fn()}
        onConfirmReading={vi.fn()}
        onOpenDraft={onOpenDraft}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "See the plan" }));
    return onOpenDraft;
  }

  it("a drafted ask opens its draft from the path (LP-968)", () => {
    const drafted = {
      ...TITLE_ITEM,
      draft: { id: "d1", status: "draft", sent_on: null } as ConditionItem["draft"],
    };
    const onOpenDraft = open([condition({ lender_code: "1947", items: [drafted] })]);
    expect(screen.getAllByText("We drafted the email to Title / escrow")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Review draft" }));
    expect(onOpenDraft).toHaveBeenCalledWith("d1");
  });

  it("Not needed waits for a reason, then sends it", () => {
    open([condition({ lender_code: "1947", items: [TITLE_ITEM] })]);
    fireEvent.click(screen.getByRole("button", { name: "Not needed" }));
    const mark = screen.getByRole("button", { name: "Mark not needed" }) as HTMLButtonElement;
    expect(mark.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Why isn’t it needed?"), {
      target: { value: "seller CD already in the package" },
    });
    expect(mark.disabled).toBe(false);
    fireEvent.click(mark);
    expect(calls.items).toEqual([
      {
        conditionId: "c1",
        itemId: "i2",
        status: "not_needed",
        note: "seller CD already in the package",
      },
    ]);
  });

  it("Already done needs a note on someone else's task, not on her own", () => {
    open([condition({ lender_code: "1947", items: [TITLE_ITEM] })]);
    fireEvent.click(screen.getByRole("button", { name: "Already done" }));
    expect((screen.getByRole("button", { name: "Mark done" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
    cleanup();
    open([condition({})]); // her own task: "I'll do it"
    fireEvent.click(screen.getByRole("button", { name: "Already done" }));
    const mark = screen.getByRole("button", { name: "Mark done" }) as HTMLButtonElement;
    expect(mark.disabled).toBe(false);
    fireEvent.click(mark);
    expect(calls.items).toEqual([{ conditionId: "c1", itemId: "i1", status: "done" }]);
  });

  it("I'll do this myself is offered on an ask and turns it into her task, with how", () => {
    open([condition({ lender_code: "1947", items: [TITLE_ITEM] })]);
    fireEvent.click(screen.getByRole("button", { name: "I’ll do this step myself" }));
    fireEvent.change(screen.getByLabelText("How are you doing it? (optional)"), {
      target: { value: "calling title" },
    });
    fireEvent.click(screen.getByRole("button", { name: "I’ll do it" }));
    expect(calls.items).toEqual([
      { conditionId: "c1", itemId: "i2", option: "i_will_do_it", note: "calling title" },
    ]);
    cleanup();
    open([condition({})]); // already her task: nothing to take over
    expect(screen.queryByRole("button", { name: "I’ll do this step myself" })).toBeNull();
  });

  it("a task she dropped stays on the card, crossed out with her reason, and can be undone", () => {
    const dropped = { ...TITLE_ITEM, status: "not_needed" as const, plan_note: "no fee charged" };
    open([condition({ lender_code: "1947", items: [dropped] })]);
    expect(screen.getByText("Why: no fee charged")).toBeTruthy();
    expect(screen.getByText("Not needed")).toBeTruthy();
    expect(
      screen.queryByText("Review the email, and send it once the plan is confirmed"),
    ).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(calls.items).toEqual([{ conditionId: "c1", itemId: "i2", status: "open" }]);
  });

  it("goes back to the suggested plan for that condition", () => {
    open([condition({})]);
    fireEvent.click(screen.getByRole("button", { name: "Go back to the suggested plan" }));
    expect(calls.reverts).toEqual(["c1"]);
  });

  it("says what Confirm will do: the emails, the ready ones and her tasks", () => {
    show(
      [
        condition({}),
        condition({
          id: "c3",
          lender_code: "0007",
          sequence: 3,
          items: [item({ id: "i3", name: "Inspection invoice", waits_on_code: "1228" })],
        }),
        condition({
          id: "c4",
          lender_code: "1582",
          sequence: 4,
          // LP-966 REVIEW: `status: "done"` is what the server actually emits beside this option —
          // `build_plan` sets both together. The fixture said option-only, with the default status,
          // which is a state no writer produces, and the summary's rule keyed on the option.
          items: [item({ id: "i4", option: "already_in_file", status: "done" })],
        }),
      ],
      { ...basePlan, blocking_codes: [], drafts: [basePlan.drafts[1] as RoundPlan["drafts"][0]] },
    );
    expect(screen.getByText("When you confirm, we will:")).toBeTruthy();
    expect(
      screen.getByText(/to Title\/attorney \(1947\)\. Until then nothing can be sent/),
    ).toBeTruthy();
    expect(screen.getByText("Mark 1582 ready")).toBeTruthy();
    expect(
      screen.getByText(/upload the invoice \(0006\); upload the invoice \(0007, after 1228\)/),
    ).toBeTruthy();
  });

  it("promises ready for what confirm will really make ready (LP-966 review)", () => {
    // The summary is a MIRROR of `condition_plan.ready_because`, which keys on each live item's
    // STATUS. Keying on the option was wrong both ways: a document she linked by hand is RECEIVED
    // until `check_link` passes it (LP-953), so the first row here was promised ready and would not
    // have become ready; and the second was left out although the server moves it.
    show(
      [
        condition({
          id: "c5",
          lender_code: "1582",
          sequence: 5,
          items: [
            item({ id: "i5", option: "already_in_file", status: "done" }),
            item({ id: "i6", option: "already_in_file", status: "received" }),
          ],
        }),
        condition({
          id: "c6",
          lender_code: "7086",
          sequence: 6,
          items: [item({ id: "i7", option: "i_will_do_it", status: "done" })],
        }),
      ],
      { ...basePlan, blocking_codes: [], drafts: [] },
    );

    const ready = screen.getByText(/Mark .* ready/).textContent ?? "";
    expect(ready).toContain("7086");
    expect(ready).not.toContain("1582");
  });

  it("LP-974: the opened condition is ONE numbered timeline, edits on each task's first step", () => {
    const second = { ...TITLE_ITEM, id: "i9" };
    show([condition({ items: [item({}), second] })], unblocked());
    fireEvent.click(screen.getByRole("button", { name: "See the plan" }));
    const path = screen.getByRole("list", { name: "The plan, step by step" });
    const steps = within(path).getAllByRole("listitem");
    // 3 steps for her task, 5 for the ask, 2 for the ending, numbered 1…10 down one list.
    expect(steps).toHaveLength(10);
    expect(steps.map((li) => li.querySelector("[aria-hidden]")?.textContent)).toEqual([
      "1",
      "2",
      "3",
      "4",
      "5",
      "6",
      "7",
      "8",
      "9",
      "10",
    ]);
    // Two tasks: each one's name sits on its first step, so the steps can be told apart.
    expect(within(steps[0] as HTMLElement).getByText("Credit report invoice")).toBeTruthy();
    expect(
      within(steps[3] as HTMLElement).getByText("Final seller Closing Disclosure"),
    ).toBeTruthy();
    // Her edits once per task, on its first step — not on every step, not on the ending.
    expect(within(path).getAllByRole("button", { name: "Not needed" })).toHaveLength(2);
    expect(
      within(steps[0] as HTMLElement).getByRole("button", { name: "Not needed" }),
    ).toBeTruthy();
    expect(
      within(steps[3] as HTMLElement).getByRole("button", { name: "Not needed" }),
    ).toBeTruthy();
    // The selects moved out of the timeline, to "How it gets done".
    expect(within(path).queryByLabelText("Next step")).toBeNull();
    expect(screen.getByText("How it gets done")).toBeTruthy();
    expect(screen.getAllByLabelText("Next step")).toHaveLength(2);
  });

  it("LP-974: a condition whose only task she dropped is not called unread", () => {
    const dropped = { ...TITLE_ITEM, status: "not_needed" as const, plan_note: "no fee charged" };
    show([condition({ lender_code: "1947", items: [dropped] })], unblocked());
    expect(screen.queryByText(/We haven’t read this one yet|We couldn’t work out/)).toBeNull();
    expect(screen.getByText("Nothing left: you marked every task not needed")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "See the plan" }));
    const path = within(screen.getByRole("list", { name: "The plan, step by step" }));
    expect(path.getAllByRole("listitem")).toHaveLength(1);
    expect(path.queryByText("The lender clears it")).toBeNull();
  });

  describe("LP-969 — add a step, and my own way", () => {
    function opened(conditions: Condition[]) {
      show(conditions, unblocked());
      fireEvent.click(screen.getByRole("button", { name: "See the plan" }));
    }

    it("offers every building block", () => {
      opened([condition({})]);
      fireEvent.click(screen.getByRole("button", { name: "Add a step" }));
      for (const label of [
        "Email someone",
        "Ask the borrower to upload",
        "Upload it myself",
        "Check a document on the file",
        "Ask the underwriter",
        "Push back to the underwriter",
        "Something else",
      ]) {
        expect(screen.getByRole("button", { name: new RegExp(`^${label}`) })).toBeTruthy();
      }
    });

    it("LP-972: a call goes to the history, not the plan; a wait is a task with its date", () => {
      opened([condition({})]);
      fireEvent.click(screen.getByRole("button", { name: "Add a step" }));
      fireEvent.click(screen.getByRole("button", { name: /^Call or talk to someone/ }));
      fireEvent.change(screen.getByLabelText("Who did you talk to?"), { target: { value: "lo" } });
      fireEvent.change(screen.getByLabelText("When"), { target: { value: "2026-10-09" } });
      fireEvent.change(screen.getByLabelText("What was agreed?"), {
        target: { value: "He will re-disclose today" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Add the step" }));
      expect(calls.logged).toEqual([
        {
          conditionId: "c1",
          with_whom: "lo",
          on: "2026-10-09",
          agreed: "He will re-disclose today",
        },
      ]);
      expect(calls.added).toEqual([]); // NOT A TASK

      fireEvent.click(screen.getByRole("button", { name: "Add a step" }));
      fireEvent.click(screen.getByRole("button", { name: /^Wait for something/ }));
      fireEvent.change(screen.getByLabelText("From whom?"), { target: { value: "title" } });
      fireEvent.change(screen.getByLabelText("What are you waiting for?"), {
        target: { value: "the payoff letter" },
      });
      fireEvent.change(screen.getByLabelText("By when?"), { target: { value: "2026-10-15" } });
      fireEvent.click(screen.getByRole("button", { name: "Add the step" }));
      expect(calls.added).toEqual([
        {
          conditionId: "c1",
          name: "the payoff letter",
          performers: ["title"],
          option: "i_will_do_it",
          waiting: true,
          due_date: "2026-10-15",
        },
      ]);
    });

    it("LP-971: the open menu offers Describe it beside the blocks", () => {
      opened([condition({})]);
      expect(screen.queryByLabelText("Or describe what you want to do")).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: "Add a step" }));
      expect(screen.getByLabelText("Or describe what you want to do")).toBeTruthy();
      expect(screen.getByRole("button", { name: "Turn it into steps" })).toBeTruthy();
    });

    it("an email step is an ask to the person she picks, in her words", () => {
      opened([condition({})]);
      fireEvent.click(screen.getByRole("button", { name: "Add a step" }));
      fireEvent.click(screen.getByRole("button", { name: /^Email someone/ }));
      const add = screen.getByRole("button", { name: "Add the step" }) as HTMLButtonElement;
      expect(add.disabled).toBe(true); // her words first
      fireEvent.change(screen.getByLabelText("To"), { target: { value: "title" } });
      fireEvent.change(screen.getByLabelText("What should they send or do?"), {
        target: { value: "The final seller CD" },
      });
      fireEvent.click(add);
      expect(calls.added).toEqual([
        {
          conditionId: "c1",
          name: "The final seller CD",
          performers: ["title"],
          option: "ask_third_party",
        },
      ]);
    });

    it("the To list is every performer but her and the appraiser, whose asks go to the lender", () => {
      opened([condition({})]);
      fireEvent.click(screen.getByRole("button", { name: "Add a step" }));
      fireEvent.click(screen.getByRole("button", { name: /^Email someone/ }));
      const to = Array.from(
        (screen.getByLabelText("To") as HTMLSelectElement).options,
        (option) => option.text,
      );
      expect(to).toContain("Lender");
      expect(to).toContain("Title / escrow");
      expect(to).not.toContain("You");
      expect(to).not.toContain("Appraiser");
    });

    it("email to the borrower, and ask the borrower to upload, are asks to the borrower", () => {
      opened([condition({})]);
      fireEvent.click(screen.getByRole("button", { name: "Add a step" }));
      fireEvent.click(screen.getByRole("button", { name: /^Email someone/ }));
      fireEvent.change(screen.getByLabelText("To"), { target: { value: "borrower" } });
      fireEvent.change(screen.getByLabelText("What should they send or do?"), {
        target: { value: "Two months of statements" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Add the step" }));
      expect(calls.added).toEqual([
        {
          conditionId: "c1",
          name: "Two months of statements",
          performers: ["borrower"],
          option: "ask_borrower",
        },
      ]);
      calls.added = [];

      fireEvent.click(screen.getByRole("button", { name: "Add a step" }));
      fireEvent.click(screen.getByRole("button", { name: /^Ask the borrower to upload/ }));
      fireEvent.change(screen.getByLabelText("What should the borrower upload?"), {
        target: { value: "The signed LOE" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Add the step" }));
      expect(calls.added).toEqual([
        {
          conditionId: "c1",
          name: "The signed LOE",
          performers: ["borrower"],
          option: "ask_borrower",
        },
      ]);
    });

    it("something else is her own task", () => {
      opened([condition({})]);
      fireEvent.click(screen.getByRole("button", { name: "Add a step" }));
      fireEvent.click(screen.getByRole("button", { name: /^Something else/ }));
      fireEvent.change(screen.getByLabelText("What will you do?"), {
        target: { value: "Call the LO about the fee" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Add the step" }));
      expect(calls.added).toEqual([
        {
          conditionId: "c1",
          name: "Call the LO about the fee",
          performers: ["processor"],
          option: "i_will_do_it",
        },
      ]);
    });

    it("check a document adds her task and opens the link dialog on it", () => {
      const added = item({ id: "new", name: "Check the HOA certificate", origin: "manual" });
      calls.addResponse = condition({ items: [item({}), added] });
      opened([condition({})]);
      expect(screen.queryByRole("dialog")).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: "Add a step" }));
      fireEvent.click(screen.getByRole("button", { name: /^Check a document on the file/ }));
      fireEvent.change(screen.getByLabelText("What is the document?"), {
        target: { value: "the HOA certificate" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Add the step" }));
      expect(calls.added).toEqual([
        {
          conditionId: "c1",
          name: "Check the HOA certificate",
          performers: ["processor"],
          option: "i_will_do_it",
        },
      ]);
      expect(screen.getByRole("dialog")).toBeTruthy();
    });

    it("the underwriter questions set the condition's own step, which a task cannot carry", () => {
      opened([condition({})]);
      fireEvent.click(screen.getByRole("button", { name: "Add a step" }));
      fireEvent.click(screen.getByRole("button", { name: /^Push back to the underwriter/ }));
      expect(calls.steps).toEqual([{ conditionId: "c1", next_step: "push_back" }]);
      expect(calls.added).toEqual([]);
    });

    it("my own way is offered while there is a suggestion, and sends the condition", () => {
      opened([condition({})]);
      fireEvent.click(screen.getByRole("button", { name: "I’ll handle it my own way" }));
      expect(calls.ownWay).toEqual(["c1"]);
    });

    it("with nothing left, my own way is gone and the path invites her own steps", () => {
      const dropped = item({
        status: "not_needed",
        plan_note: "You chose to handle this condition your own way.",
      });
      opened([condition({ items: [dropped] })]);
      expect(screen.queryByRole("button", { name: "I’ll handle it my own way" })).toBeNull();
      expect(screen.getByText("Build your own path")).toBeTruthy();
      expect(screen.getByRole("button", { name: "Add a step" })).toBeTruthy();
    });

    it("a condition never read can still be given steps", () => {
      opened([condition({ reading: null, items: [] })]);
      // Said on the row and again in the opened plan, where "Add a step" is the way forward.
      expect(
        screen.getAllByText("We haven’t read this one yet, so there is nothing to plan for it."),
      ).toHaveLength(2);
      expect(screen.getByRole("button", { name: "Add a step" })).toBeTruthy();
    });

    it("a step she added can be removed; one the reading suggested cannot", () => {
      const mine = item({ id: "m1", name: "Call the LO", origin: "manual" });
      opened([condition({ items: [item({}), mine] })]);
      const removes = screen.getAllByRole("button", { name: "Remove step" });
      expect(removes).toHaveLength(1);
      fireEvent.click(removes[0] as HTMLElement);
      expect(calls.removed).toEqual([{ conditionId: "c1", itemId: "m1" }]);
    });

    it("her own open task offers Add document on its step; an ask does not", () => {
      opened([condition({ items: [item({}), { ...TITLE_ITEM }] })]);
      const path = within(screen.getByRole("list", { name: "The plan, step by step" }));
      expect(path.getAllByRole("button", { name: /Add document/ })).toHaveLength(1);
    });
  });

  describe("LP-973 — round 2's plan is what is new on its sheet", () => {
    // Seen again, with the plan she confirmed on round 0 (LP-975's stamp).
    const seenAgain = (id: string, code: string) =>
      condition({
        id,
        lender_code: code,
        sequence: 9,
        first_round_id: "r0",
        plan_confirmed_at: "2026-08-20T15:00:00Z",
      });

    it("lists only new conditions, and counts the ones that keep their plan", () => {
      show([condition({}), seenAgain("c8", "1947"), seenAgain("c9", "6378")], unblocked());
      expect(screen.getByRole("button", { name: "0006" })).toBeTruthy();
      expect(screen.queryByRole("button", { name: "1947" })).toBeNull();
      expect(screen.queryByRole("button", { name: "6378" })).toBeNull();
      expect(screen.getByText("2 conditions from earlier rounds keep their plan.")).toBeTruthy();
      expect(screen.getByText("Here’s how we’ll get this condition cleared")).toBeTruthy();
      expect(screen.getByText(/^1 new condition/)).toBeTruthy();
    });

    it("says which drafted codes are from an earlier round (LP-973 review)", () => {
      // "Unlock the 2 drafted emails: to Title/attorney (1947)" is true of the server — the email is
      // real and unsent — but 1947 is carried and has no row above, so she cannot click it or see what
      // it asks. The LP-966 review already settled that a code in a sentence should name a row she can
      // reach, which is why a BLOCKING carried condition stays in the plan; the drafts case was left.
      show([condition({}), seenAgain("c8", "1947")], {
        ...unblocked(),
        drafts: [{ label: "Title/attorney", codes: ["1947"] }],
      } as RoundPlan);
      expect(screen.queryByRole("button", { name: "1947" })).toBeNull();
      expect(
        screen.getByText(/1947 is from an earlier round, so it is not listed above\./),
      ).toBeTruthy();
    });

    it("says nothing extra when every drafted code has a row (the control)", () => {
      show([condition({})], {
        ...unblocked(),
        drafts: [{ label: "Borrower", codes: ["0006"] }],
      } as RoundPlan);
      expect(screen.getByRole("button", { name: "0006" })).toBeTruthy();
      expect(screen.queryByText(/from an earlier round, so/)).toBeNull();
    });

    it("keeps a carried condition that blocks Confirm, so the refusal names a row on screen", () => {
      show([condition({}), seenAgain("c8", "0132")]); // basePlan blocks on 0132
      expect(screen.getByRole("button", { name: "0132" })).toBeTruthy();
      expect(
        screen.getByText("Confirm 0132’s reading first — one condition still needs you."),
      ).toBeTruthy();
      expect(screen.queryByText(/from earlier rounds/)).toBeNull();
    });

    it("says so when nothing on the sheet is new", () => {
      show([seenAgain("c8", "1947")], unblocked());
      expect(screen.getByText("Nothing new to plan on this sheet")).toBeTruthy();
      expect(screen.getByText("1 condition from earlier rounds keeps its plan.")).toBeTruthy();
      expect(screen.getByRole("button", { name: "Confirm the plan" })).toBeTruthy();
    });

    it("LP-975: one seen again whose plan she never confirmed is in the plan, and not counted", () => {
      // Round 2 imported while round 1's plan waited: confirming round 2 puts this plan in force, so it
      // is on the screen she confirms, and "keep their plan" would say she approved what she never saw.
      const neverConfirmed = condition({
        id: "c7",
        lender_code: "1947",
        sequence: 8,
        first_round_id: "r0",
        plan_confirmed_at: null,
      });
      show([condition({}), neverConfirmed, seenAgain("c9", "6378")], unblocked());
      expect(screen.getByRole("button", { name: "1947" })).toBeTruthy();
      expect(screen.queryByRole("button", { name: "6378" })).toBeNull();
      expect(screen.getByText("1 condition from earlier rounds keeps its plan.")).toBeTruthy();
    });

    it("round 1 has nothing carried, and says nothing about it (the control)", () => {
      show([condition({}), condition({ id: "c2", lender_code: "1947", sequence: 2 })], unblocked());
      expect(screen.queryByText(/from earlier rounds/)).toBeNull();
      expect(screen.getByText("Here’s how we’ll get these 2 conditions cleared")).toBeTruthy();
    });
  });

  describe("LP-976 — conditions added after the plan was confirmed", () => {
    const confirmedPlan = (): RoundPlan => ({
      ...unblocked(),
      confirmed_at: "2026-08-28T20:40:00Z",
    });
    const stamped = (id: string, code: string) =>
      condition({ id, lender_code: code, plan_confirmed_at: "2026-08-28T20:40:00Z" });

    it("stays for an added condition, shows only it, and confirms its plan on its round", () => {
      show(
        [stamped("c1", "0006"), condition({ id: "c9", lender_code: "4410", sequence: 9 })],
        confirmedPlan(),
        new Set(["r1"]),
      );
      expect(screen.getByText("1 condition was added after you confirmed the plan")).toBeTruthy();
      expect(screen.getByText(/an email that includes\s+it\s+is not sent/)).toBeTruthy();
      expect(screen.getByRole("button", { name: "4410" })).toBeTruthy();
      expect(screen.queryByRole("button", { name: "0006" })).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: "Confirm its plan" }));
      expect(calls.confirms).toEqual([{ roundId: "r1" }]);
    });

    it("confirms each round an added condition is on", () => {
      show(
        [
          condition({ id: "c8", lender_code: "4410", sequence: 8 }),
          condition({
            id: "c9",
            lender_code: "4411",
            sequence: 9,
            first_round_id: "r0",
            last_seen_round_id: "r0",
          }),
        ],
        confirmedPlan(),
        new Set(["r0", "r1"]),
      );
      expect(screen.getByText("2 conditions were added after you confirmed the plan")).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: "Confirm their plan" }));
      expect(calls.confirms).toEqual([{ roundId: "r1" }, { roundId: "r0" }]);
    });

    it("an unstamped condition on a round still waiting is not 'added after' (the control)", () => {
      // r0 is not confirmed: its plan is a proposal, not a late arrival on a confirmed plan.
      show(
        [
          stamped("c1", "0006"),
          condition({
            id: "c9",
            lender_code: "4411",
            first_round_id: "r0",
            last_seen_round_id: "r0",
          }),
        ],
        confirmedPlan(),
        new Set(["r1"]),
      );
      expect(screen.queryByText(/added after you confirmed/)).toBeNull();
      expect(screen.queryByRole("button", { name: /Confirm/ })).toBeNull();
    });

    it("names only the emails the added condition is in", () => {
      // The first confirm already unlocked round 1's other emails; this confirm unlocks only its own.
      show(
        [stamped("c1", "0006"), condition({ id: "c9", lender_code: "4410", sequence: 9 })],
        {
          ...confirmedPlan(),
          drafts: [
            { recipient: "borrower", label: "Borrower", codes: ["0006"] },
            { recipient: "hoa", label: "HOA", codes: ["4410"] },
          ],
        },
        new Set(["r1"]),
      );
      expect(screen.getByText(/to HOA \(4410\)/)).toBeTruthy();
      expect(screen.queryByText(/to Borrower \(0006\)/)).toBeNull();
    });

    it("shows a late condition with no task even when the server counts nothing planned", () => {
      // The LP-976 review's hazard: `planned` counts conditions with a task or a step, and a late one
      // whose reading fell back can have neither. Hidden, nothing would ever stamp it, and with the
      // fallback gone its emails would wait for ever.
      show(
        [
          stamped("c1", "0006"),
          condition({ id: "c9", lender_code: "4410", sequence: 9, items: [] }),
        ],
        { ...confirmedPlan(), planned: 0 },
        new Set(["r1"]),
      );
      expect(screen.getByText("1 condition was added after you confirmed the plan")).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: "Confirm its plan" }));
      expect(calls.confirms).toEqual([{ roundId: "r1" }]);
    });

    it("on a round still waiting with nothing planned, shows nothing (deliberate, LP-976)", () => {
      // A task-less condition on an UNCONFIRMED round is out of force under either rule, has nothing to
      // apply or send, and draws the panel the moment it gets a task. The `planned === 0` guard stays
      // for this case on purpose; widening it would put an empty plan on screen.
      show([condition({ id: "c9", lender_code: "4410", items: [] })], {
        ...unblocked(),
        planned: 0,
      });
      expect(screen.queryByText(/Here’s how|added after you confirmed|Nothing new/)).toBeNull();
      expect(screen.queryByRole("button", { name: /Confirm/ })).toBeNull();
    });

    it("is gone when nothing was added since", () => {
      show([stamped("c1", "0006")], confirmedPlan(), new Set(["r1"]));
      expect(screen.queryByRole("button", { name: /Confirm/ })).toBeNull();
    });
  });
});

describe("LP-971 review — Add these steps fires several adds from one press", () => {
  /**
   * The link dialog is opened from the add response, by finding the item that was not there before:
   * `updated.items.find((each) => !before.has(each.id))`. `before` is captured once, from the prop,
   * and every add in the batch captures the same one — so the FIRST new item wins, whichever step
   * asked for the dialog. A "Check a document" step that is not the first in the batch opens the
   * dialog on another step's task, and she links a document to the wrong one.
   */
  const described: DescribeResult = {
    steps: [
      { block: "todo", text: "Call the LO about the fee", to: null },
      { block: "check", text: "the HOA certificate", to: null },
    ],
    left_out: [],
    refusal: null,
  };

  function addTwo() {
    const base = condition({ items: [] });
    const todo = item({ id: "i-todo", name: "Call the LO about the fee" });
    const check = item({ id: "i-check", name: "Check the HOA certificate" });
    // One answer per add, each the condition as it stands after that add.
    calls.addResponses = [
      { ...base, items: [todo] },
      { ...base, items: [todo, check] },
    ];
    calls.describeResult = described;
    show([base], unblocked());
    fireEvent.click(screen.getByRole("button", { name: "See the plan" }));
    fireEvent.click(screen.getByRole("button", { name: "Add a step" }));
    fireEvent.change(screen.getByLabelText("Or describe what you want to do"), {
      target: { value: "call the LO and check the HOA certificate" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Turn it into steps" }));
    fireEvent.click(screen.getByRole("button", { name: "Add these 2 steps" }));
  }

  it("sends both steps through the add door", () => {
    addTwo();
    expect(calls.added).toHaveLength(2);
  });

  it("opens the link dialog on the step that asked for it", () => {
    addTwo();
    const dialog = screen.getByRole("dialog");
    console.log("DIALOGS:", screen.getAllByRole("dialog").length, "| TEXT:", dialog.textContent);
    console.log("ADDED:", JSON.stringify(calls.added));
    expect(within(dialog).getByText("Check the HOA certificate")).toBeTruthy();
    expect(within(dialog).queryByText("Call the LO about the fee")).toBeNull();
  });
});
