import type {
  Condition,
  ConditionItem,
  ConditionRound,
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
const calls = vi.hoisted(() => ({ items: [] as unknown[], steps: [] as unknown[] }));
vi.mock("@/lib/api/conditions", () => ({
  useRoundPlan: () => ({ data: plan.data }),
  useConfirmPlan: () => ({ mutate: vi.fn(), isPending: false }),
  useSetNextStep: () => ({ mutate: (body: unknown) => calls.steps.push(body) }),
  useUpdateItem: () => ({ mutate: (body: unknown) => calls.items.push(body) }),
}));

import { RoundPlanPanel } from "./round-plan-panel";

afterEach(() => {
  cleanup();
  calls.items = [];
  calls.steps = [];
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

function show(conditions: Condition[], data: RoundPlan = basePlan) {
  plan.data = data;
  render(
    <RoundPlanPanel
      fileId="f1"
      round={round}
      conditions={conditions}
      onOpenCondition={vi.fn()}
      onConfirmReading={vi.fn()}
    />,
  );
}

function unblocked(): RoundPlan {
  return { ...basePlan, blocking_codes: [], needs_confirmation: 0, drafts: [] };
}

describe("RoundPlanPanel", () => {
  it("says what to do on the screen and holds Confirm while 0132's reading needs her", () => {
    show([]);
    expect(screen.getByText("Check the plan, then confirm it")).toBeTruthy();
    expect(screen.getByText("Plan for round 1")).toBeTruthy();
    expect(
      screen.getByText(/Nothing is emailed or changed on the file until you do\./),
    ).toBeTruthy();
    expect(screen.getByText(/to draft — Borrower, Title\/attorney, LO/)).toBeTruthy();
    const confirm = screen.getByRole("button", { name: "Confirm plan and draft 3 emails" });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    expect(
      screen.getByText("Confirm 0132’s reading first — one condition still needs you."),
    ).toBeTruthy();
  });

  it("is gone once the plan is confirmed", () => {
    plan.data = { ...basePlan, confirmed_at: "2026-08-28T20:40:00Z", blocking_codes: [] };
    const { container } = render(
      <RoundPlanPanel
        fileId="f1"
        round={round}
        conditions={[]}
        onOpenCondition={vi.fn()}
        onConfirmReading={vi.fn()}
      />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("collapsed, says who does each task and in which email", () => {
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
    expect(screen.getAllByText("You upload the invoice")).toHaveLength(2);
    expect(screen.getByText("Ask Title / escrow — in the title email")).toBeTruthy();
    expect(screen.getByText("Waits on 1228")).toBeTruthy();
    expect(screen.getByText("Found: HR Loan Processing invoice, page 1")).toBeTruthy();
    // Nothing of the detail until she opens it.
    expect(screen.queryByText("What the lender wants")).toBeNull();
  });

  it("opens a condition to what the lender wants, when, the words, done-when and good to know", () => {
    show([condition({})], unblocked());
    fireEvent.click(screen.getByRole("button", { name: "What you need to do" }));

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

    fireEvent.click(screen.getByRole("button", { name: "Hide details" }));
    expect(screen.queryByText("What the lender wants")).toBeNull();
  });

  it("an ask's meaning names who it goes to", () => {
    show([condition({ lender_code: "1947", items: [TITLE_ITEM] })], unblocked());
    fireEvent.click(screen.getByRole("button", { name: "What you need to do" }));
    expect(screen.getByText(/We put this request in the email to Title \/ escrow\./)).toBeTruthy();
  });

  it("changes ONE task's step, and the condition's own step through its own call", () => {
    const second = item({ id: "i9", name: "Second task", option: "i_will_do_it" });
    show([condition({ next_step: "push_back", items: [item({}), second] })], unblocked());
    fireEvent.click(screen.getByRole("button", { name: "What you need to do" }));
    const selects = screen.getAllByLabelText("Next step");
    expect(selects).toHaveLength(3); // the whole condition, then each task

    fireEvent.change(selects[2] as HTMLSelectElement, { target: { value: "ask_borrower" } });
    expect(calls.items).toEqual([{ conditionId: "c1", itemId: "i9", option: "ask_borrower" }]);

    fireEvent.change(selects[0] as HTMLSelectElement, { target: { value: "ask_underwriter" } });
    expect(calls.steps).toEqual([{ conditionId: "c1", next_step: "ask_underwriter" }]);
  });

  it("the ⓘ opens all eight steps with the current one marked, and Got it closes it", () => {
    show([condition({ lender_code: "1947", items: [TITLE_ITEM] })], unblocked());
    fireEvent.click(screen.getByRole("button", { name: "What you need to do" }));
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

  it("shows a condition with nothing worked out, with one way to fix it", () => {
    // The failed reading on LF-Y36E: 1947 blocked Confirm and was not on the screen.
    const onConfirmReading = vi.fn();
    plan.data = basePlan;
    render(
      <RoundPlanPanel
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
          items: [item({ id: "i4", option: "already_in_file" })],
        }),
      ],
      { ...basePlan, blocking_codes: [], drafts: [basePlan.drafts[1] as RoundPlan["drafts"][0]] },
    );
    expect(screen.getByText("When you confirm, we will:")).toBeTruthy();
    expect(screen.getByText(/to Title\/attorney \(1947\)\. You review each one/)).toBeTruthy();
    expect(screen.getByText("Mark 1582 ready")).toBeTruthy();
    expect(
      screen.getByText(/upload the invoice \(0006\); upload the invoice \(0007, after 1228\)/),
    ).toBeTruthy();
  });
});
