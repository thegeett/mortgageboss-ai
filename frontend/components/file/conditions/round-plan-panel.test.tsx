import type { Condition, ConditionRound, RoundPlan } from "@/lib/types/conditions";
// @vitest-environment jsdom
/**
 * S3-02 (LP-920): the plan's pills, and Confirm held back while a reading still needs her.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const plan = vi.hoisted(() => ({ data: undefined as RoundPlan | undefined }));
vi.mock("@/lib/api/conditions", () => ({
  useRoundPlan: () => ({ data: plan.data }),
  useConfirmPlan: () => ({ mutate: vi.fn(), isPending: false }),
  useSetNextStep: () => ({ mutate: vi.fn() }),
  useUpdateItem: () => ({ mutate: vi.fn() }),
}));

import { RoundPlanPanel } from "./round-plan-panel";

afterEach(cleanup);

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

describe("RoundPlanPanel", () => {
  it("heads the plan and holds Confirm while 0132's reading needs her", () => {
    plan.data = basePlan;
    render(
      <RoundPlanPanel
        fileId="f1"
        round={round}
        conditions={[] as Condition[]}
        onOpenCondition={vi.fn()}
        onConfirmReading={vi.fn()}
      />,
    );
    expect(screen.getByText("11 conditions · 08/28/2026 · nothing has been sent")).toBeDefined();
    expect(screen.getByText("Borrower · Title/attorney · LO")).toBeDefined();
    const confirm = screen.getByRole("button", { name: "Confirm plan and draft 3 emails" });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    expect(
      screen.getByText("Confirm 0132’s reading first — one condition still needs you."),
    ).toBeDefined();
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
});
