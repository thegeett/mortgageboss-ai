// @vitest-environment jsdom
/**
 * LP-971 — "Describe it": her words go to the server, the proposed steps come back for her to see, and
 * "Add these steps" adds each through the same door the block chosen by hand uses (`addedStepFor`).
 */
import type { DescribeResult } from "@/lib/types/conditions";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  sent: [] as unknown[],
  result: null as DescribeResult | null,
  fail: null as Error | null,
}));
vi.mock("@/lib/api/conditions", () => ({
  useDescribeSteps: () => ({
    isPending: false,
    mutate: (
      body: unknown,
      options: { onSuccess: (r: DescribeResult) => void; onError: (e: unknown) => void },
    ) => {
      state.sent.push(body);
      if (state.fail) options.onError(state.fail);
      else if (state.result) options.onSuccess(state.result);
    },
  }),
}));

import { getErrorMessage } from "@/lib/errors/api-error";
import { DescribeSteps } from "./plan-describe";

afterEach(() => {
  cleanup();
  state.sent = [];
  state.result = null;
  state.fail = null;
});

function show(ownStep: "push_back" | null = null) {
  const onAdd = vi.fn();
  const onDone = vi.fn();
  render(
    <DescribeSteps
      conditionId="c1"
      ownStep={ownStep}
      pending={false}
      onAdd={onAdd}
      onDone={onDone}
    />,
  );
  return { onAdd, onDone };
}

function turn(words: string) {
  fireEvent.change(screen.getByLabelText("Or describe what you want to do"), {
    target: { value: words },
  });
  fireEvent.click(screen.getByRole("button", { name: "Turn it into steps" }));
}

describe("DescribeSteps", () => {
  it("sends her words, shows the steps, and adds each through the add-a-step door", () => {
    state.result = {
      steps: [
        { block: "email", to: "title", text: "The final seller CD" },
        { block: "todo", to: null, text: "Call the builder" },
      ],
      left_out: [],
      refusal: null,
    };
    const { onAdd, onDone } = show();
    expect(
      (screen.getByRole("button", { name: "Turn it into steps" }) as HTMLButtonElement).disabled,
    ).toBe(true); // her words first
    turn("Ask title for the final CD and I'll call the builder");
    expect(state.sent).toEqual([
      { conditionId: "c1", text: "Ask title for the final CD and I'll call the builder" },
    ]);

    const proposed = within(screen.getByRole("list", { name: "Proposed steps" }));
    expect(proposed.getByText(/\(Title \/ escrow\): The final seller CD/)).toBeTruthy();
    expect(proposed.getByText(/Call the builder/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Add these 2 steps" }));
    expect(onAdd.mock.calls.map(([step]) => step)).toEqual([
      {
        kind: "task",
        name: "The final seller CD",
        performers: ["title"],
        option: "ask_third_party",
      },
      { kind: "task", name: "Call the builder", performers: ["processor"], option: "i_will_do_it" },
    ]);
    expect(onDone).toHaveBeenCalled();
  });

  it("a question says her words go in the note, and that it replaces the condition's step", () => {
    state.result = {
      steps: [{ block: "underwriter", to: null, text: "Can 1228 move to closing?" }],
      left_out: [],
      refusal: null,
    };
    const { onAdd } = show("push_back");
    turn("Ask the underwriter to move 1228 to closing");
    expect(screen.getByText(/We draft the note from the condition\. Put this in it/)).toBeTruthy();
    expect(screen.getByText(/It replaces this condition’s own step\./)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Add this step" }));
    expect(onAdd).toHaveBeenCalledWith({ kind: "own_step", option: "ask_underwriter" });
  });

  it("the same question as the condition's own step replaces nothing (the control)", () => {
    state.result = {
      steps: [{ block: "push_back", to: null, text: "It is new construction" }],
      left_out: [],
      refusal: null,
    };
    show("push_back");
    turn("Push back, it's new construction");
    expect(screen.getByText(/Put this in it before you send/)).toBeTruthy();
    expect(screen.queryByText(/It replaces this condition’s own step/)).toBeNull();
  });

  it("shows what was left out and why, beside what was kept", () => {
    state.result = {
      steps: [{ block: "todo", to: null, text: "Call the builder" }],
      left_out: [
        "Left out “Pay the $450 fee”: it mentions $450, which is not in what you wrote or the lender's words.",
      ],
      refusal: null,
    };
    show();
    turn("Call the builder and sort the fee");
    expect(
      within(screen.getByRole("list", { name: "Left out" })).getByText(/it mentions \$450/),
    ).toBeTruthy();
  });

  it("a refusal is a sentence and offers nothing to add", () => {
    state.result = {
      steps: [],
      left_out: [],
      refusal: "That didn't turn into any steps. Try saying who should do what.",
    };
    show();
    turn("hmm");
    expect(
      screen.getByText("That didn't turn into any steps. Try saying who should do what."),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Add th/ })).toBeNull();
  });

  it("a failed request says so", () => {
    state.fail = new Error("Network Error");
    show();
    turn("Ask title for the CD");
    expect(screen.getByText(getErrorMessage(state.fail))).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Proposed steps" })).toBeNull();
  });
});
