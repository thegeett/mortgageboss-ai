// @vitest-environment jsdom
/**
 * LP-921 — the summary bar is Stage 2's on a file with no plan and S3-12's on a file with one, and
 * every S3-12 number sets the filter whose rows it counts.
 */
import { EMPTY_LIST_URL_STATE } from "@/lib/conditions/list-url";
import type { ConditionListUrlState } from "@/lib/conditions/list-url";
import type { ConditionSummary } from "@/lib/types/conditions";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ConditionsSummaryBar } from "./conditions-summary-bar";

afterEach(cleanup);

/** S3-12's numbers (LP-934's summary row). "Failed a check" is D1's 2 (LP-934 M1), here 1 as drawn. */
const S3_12: ConditionSummary = {
  total: 11,
  open: 11,
  cleared: 0,
  waived: 0,
  not_cleared: 0,
  superseded: 0,
  info_only: 0,
  by_prep_status: { waiting: 7, to_do: 3, ready: 1 },
  by_owner: {},
  by_bucket_kind: { prior_to_docs: 6, prior_to_funding: 5 },
  open_prior_to_docs: 6,
  open_prior_to_funding: 5,
  pending_suggestions: 0,
  waiting_on_others: 7,
  your_tasks: 2,
  ready_to_send: 1,
  failed_check: 1,
  has_plan: true,
  latest_round: null,
};

function labels(): string[] {
  return screen
    .getAllByText(
      (_, element) => element?.tagName === "SPAN" && element.className.includes("uppercase"),
    )
    .map((element) => element.textContent ?? "");
}

describe("ConditionsSummaryBar", () => {
  it("shows S3-12's numbers on a file with a plan", () => {
    render(
      <ConditionsSummaryBar summary={S3_12} state={EMPTY_LIST_URL_STATE} onFilter={vi.fn()} />,
    );
    expect(labels()).toEqual([
      "Open",
      "Waiting on others",
      "Your tasks",
      "Ready to send",
      "Failed a check",
      "Prior to docs open",
      "Prior to funding open",
    ]);
  });

  it("keeps Stage 2's seven on a file with no plan", () => {
    render(
      <ConditionsSummaryBar
        summary={{ ...S3_12, has_plan: false }}
        state={EMPTY_LIST_URL_STATE}
        onFilter={vi.fn()}
      />,
    );
    expect(labels()).toEqual([
      "Open",
      "Came back",
      "Cleared",
      "Waived",
      "Information",
      "Prior to docs open",
      "Prior to funding open",
    ]);
  });

  it.each([
    ["Waiting on others", { prepStatus: ["waiting"] }],
    ["Your tasks", { step: ["i_will_do_it"] }],
    ["Ready to send", { prepStatus: ["ready"] }],
    ["Failed a check", { check: "failed" }],
  ] as const)("%s sets its own filter on open conditions", (label, want) => {
    const onFilter = vi.fn<(next: ConditionListUrlState) => void>();
    render(
      <ConditionsSummaryBar summary={S3_12} state={EMPTY_LIST_URL_STATE} onFilter={onFilter} />,
    );
    fireEvent.click(screen.getByRole("button", { name: new RegExp(`^${label}`) }));
    expect(onFilter).toHaveBeenCalledWith({
      ...EMPTY_LIST_URL_STATE,
      lenderStatus: ["open", "not_cleared"],
      ...want,
    });
  });

  it("clicking the lit number clears it, the step included", () => {
    const onFilter = vi.fn<(next: ConditionListUrlState) => void>();
    const state: ConditionListUrlState = {
      ...EMPTY_LIST_URL_STATE,
      lenderStatus: ["open", "not_cleared"],
      step: ["i_will_do_it"],
    };
    render(<ConditionsSummaryBar summary={S3_12} state={state} onFilter={onFilter} />);
    const tasks = screen.getByRole("button", { name: /^Your tasks/ });
    expect(tasks.getAttribute("aria-pressed")).toBe("true");
    // Only the one it describes is lit — not "Open", whose lender filter it shares.
    expect(screen.getByRole("button", { name: /^Open/ }).getAttribute("aria-pressed")).toBe(
      "false",
    );
    fireEvent.click(tasks);
    expect(onFilter).toHaveBeenCalledWith(EMPTY_LIST_URL_STATE);
  });
});
