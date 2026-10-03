// @vitest-environment jsdom
/**
 * LP-958 — the drawer's Next box: the sentence and its one control, with the lender's name and the
 * ready count from the package (the panel's own numbers), and the three steps once it is Ready.
 */
import type { Condition, ConditionItem } from "@/lib/types/conditions";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/conditions", () => ({
  useConditionPackage: () => ({ data: { lender_short: "UWM", ready_count: 6 } }),
  useUpdateItem: () => ({ isPending: false, mutate: vi.fn() }),
  useUploadToItem: () => ({ isPending: false, mutate: vi.fn() }),
  useLinkItemDocument: () => ({ isPending: false, mutate: vi.fn() }),
  useLinkCandidates: () => ({ isPending: false, isError: false, data: [] }),
}));

import { NextBox } from "./next-box";

afterEach(cleanup);

function condition(overrides: Partial<Condition> = {}): Condition {
  return {
    id: "c1",
    lender_code: "0006",
    prep_status: "to_do",
    lender_status: "open",
    info_only: false,
    superseded_by_id: null,
    next_step: null,
    items: [],
    evidence: [],
    question_draft: null,
    waiting_on: null,
    ...overrides,
  } as Condition;
}

const TASK = {
  id: "t1",
  name: "Credit report invoice",
  option: "i_will_do_it",
  status: "open",
  performers: ["processor"],
  waits_on_code: null,
} as unknown as ConditionItem;

describe("NextBox", () => {
  it("Ready: Open the lender package, and the three steps after", () => {
    const onShowPackage = vi.fn();
    render(
      <NextBox
        fileId="f1"
        condition={condition({ prep_status: "ready" })}
        onShowPackage={onShowPackage}
        onRecordAnswer={vi.fn()}
      />,
    );
    const box = screen.getByRole("region", { name: "Next" });
    within(box).getByText(
      "Send it to UWM: build the lender package. It goes in with 5 other conditions that are ready.",
    );
    fireEvent.click(within(box).getByRole("button", { name: "Open the lender package" }));
    expect(onShowPackage).toHaveBeenCalledOnce();
    expect(
      within(box)
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual([
      "1. Build the package, download it, and upload it in UWM’s portal.",
      "2. Mark it submitted: this condition becomes Sent to lender.",
      "3. When UWM answers, record the lender’s answer here.",
    ]);
  });

  it("her task: the item's own Add document and Ask someone, in the box", () => {
    render(
      <NextBox fileId="f1" condition={condition({ items: [TASK] })} onRecordAnswer={vi.fn()} />,
    );
    const box = screen.getByRole("region", { name: "Next" });
    within(box).getByText(/^Get the credit report invoice/);
    expect(within(box).getByRole("button", { name: "Add document" })).toBeDefined();
    expect(within(box).getByRole("button", { name: "Ask someone" })).toBeDefined();
    expect(within(box).queryByRole("list")).toBeNull();
  });

  it("Sent: Record the lender's answer", () => {
    const onRecordAnswer = vi.fn();
    render(
      <NextBox
        fileId="f1"
        condition={condition({ prep_status: "with_underwriter" })}
        onRecordAnswer={onRecordAnswer}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Record the lender’s answer" }));
    expect(onRecordAnswer).toHaveBeenCalledOnce();
  });

  it("an unsent email: Open the email opens that draft", () => {
    const onOpenDraft = vi.fn();
    const ask = {
      ...TASK,
      option: "ask_borrower",
      performers: ["borrower"],
      draft: { id: "dr9", status: "draft", sent_on: null },
    } as unknown as ConditionItem;
    render(
      <NextBox
        fileId="f1"
        condition={condition({ items: [ask] })}
        onOpenDraft={onOpenDraft}
        onRecordAnswer={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Open the email" }));
    expect(onOpenDraft).toHaveBeenCalledWith("dr9");
  });

  it("renders nothing when there is no next step", () => {
    const { container } = render(
      <NextBox fileId="f1" condition={condition()} onRecordAnswer={vi.fn()} />,
    );
    expect(container.textContent).toBe("");
  });
});
