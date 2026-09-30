// @vitest-environment jsdom
/**
 * LP-940: "Withdraw" appears only on a condition she added by hand, asks for a reason first, and shows
 * the server's refusal as it is; the "Withdrawn (n)" section lists each with its reason and Undo.
 */
import type { Condition, WithdrawnCondition } from "@/lib/types/conditions";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { AxiosError } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  withdrawn: [] as WithdrawnCondition[],
  withdrawCalls: [] as unknown[],
  restoreCalls: [] as unknown[],
  refuse: null as string | null,
}));
vi.mock("@/lib/api/conditions", () => ({
  useWithdrawnConditions: () => ({ data: state.withdrawn }),
  useWithdrawCondition: () => ({
    isPending: false,
    mutate: (body: unknown, options?: { onError?: (error: unknown) => void }) => {
      state.withdrawCalls.push(body);
      // The shape the API client rejects with: a 409 whose envelope carries the sentence.
      if (state.refuse) {
        options?.onError?.(
          new AxiosError("Request failed", "ERR_BAD_REQUEST", undefined, undefined, {
            status: 409,
            data: { error: { message: state.refuse } },
          } as never),
        );
      }
    },
  }),
  useRestoreCondition: () => ({
    isPending: false,
    mutate: (body: unknown) => state.restoreCalls.push(body),
  }),
}));

import { WithdrawControl, WithdrawnSection } from "./withdraw-condition";

afterEach(() => {
  cleanup();
  state.withdrawCalls = [];
  state.restoreCalls = [];
  state.refuse = null;
});

function condition(origin: "manual" | "sheet"): Condition {
  return { id: "c1", lender_code: "9001", origin } as Condition;
}

describe("WithdrawControl", () => {
  it("is not offered on a condition from the lender's sheet", () => {
    const { container } = render(<WithdrawControl fileId="f1" condition={condition("sheet")} />);
    expect(container.textContent).toBe("");
  });

  it("asks for a reason before it withdraws", () => {
    render(<WithdrawControl fileId="f1" condition={condition("manual")} />);
    fireEvent.click(screen.getByRole("button", { name: /Withdraw/ }));
    const submit = screen.getByRole("button", { name: "Withdraw" });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Why you are withdrawing it"), {
      target: { value: "  Added twice by mistake  " },
    });
    fireEvent.click(submit);
    expect(state.withdrawCalls).toEqual([{ conditionId: "c1", reason: "Added twice by mistake" }]);
  });

  it("shows the server's refusal as it is", () => {
    state.refuse = "The lender's answer is recorded on it, so it stays on the file.";
    render(<WithdrawControl fileId="f1" condition={condition("manual")} />);
    fireEvent.click(screen.getByRole("button", { name: /Withdraw/ }));
    fireEvent.change(screen.getByLabelText("Why you are withdrawing it"), {
      target: { value: "entered in error" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Withdraw" }));
    expect(screen.getByText(state.refuse)).toBeDefined();
  });
});

describe("WithdrawnSection", () => {
  it("is collapsed with its count and codes, and each row has its reason and Undo", () => {
    state.withdrawn = [
      {
        id: "c1",
        lender_code: "9001",
        verbatim_text: "Provide a copy of the processing invoice.",
        reason: "Added twice by mistake",
        withdrawn_at: "2026-09-29T20:00:00Z",
      },
    ];
    render(<WithdrawnSection fileId="f1" />);
    screen.getByText("1 · 9001");
    expect(screen.queryByText(/Added twice by mistake/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Withdrawn/ }));
    screen.getByText("Withdrawn 09/29 — Added twice by mistake");
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(state.restoreCalls).toEqual([{ conditionId: "c1" }]);
  });

  it("is absent when nothing is withdrawn", () => {
    state.withdrawn = [];
    const { container } = render(<WithdrawnSection fileId="f1" />);
    expect(container.textContent).toBe("");
  });
});
