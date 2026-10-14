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
  const onAddAll = vi.fn();
  const onDone = vi.fn();
  render(
    <DescribeSteps
      conditionId="c1"
      ownStep={ownStep}
      pending={false}
      onAddAll={onAddAll}
      onDone={onDone}
    />,
  );
  return { onAddAll, onDone };
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
    const { onAddAll, onDone } = show();
    expect(
      (screen.getByRole("button", { name: "Turn it into steps" }) as HTMLButtonElement).disabled,
    ).toBe(true); // her words first
    turn("Ask title for the final CD and I'll call the builder");
    expect(state.sent).toEqual([
      { conditionId: "c1", text: "Ask title for the final CD and I'll call the builder" },
    ]);

    const proposed = within(screen.getByRole("list", { name: "Proposed steps" }));
    expect(proposed.getByText(/\(Title \/ escrow\): The final seller CD/)).toBeTruthy();
    // The step's own line, not its preview's "Do it: Call the builder" (LP-971 follow-up).
    expect(proposed.getAllByText(/Call the builder/)[0]?.textContent).toMatch(
      /^Something else: Call the builder/,
    );

    fireEvent.click(screen.getByRole("button", { name: "Add these 2 steps" }));
    // LP-971 review — ONE call with the whole list, so the parent can chain the adds.
    expect(onAddAll).toHaveBeenCalledTimes(1);
    expect(onAddAll.mock.calls[0]?.[0]).toEqual([
      {
        kind: "task",
        name: "The final seller CD",
        performers: ["title"],
        option: "ask_third_party",
        bringsDocument: true,
      },
      {
        kind: "task",
        name: "Call the builder",
        performers: ["processor"],
        option: "i_will_do_it",
        bringsDocument: false,
      },
    ]);
    expect(onDone).toHaveBeenCalled();
  });

  it("a question says her words go in the note, and that it replaces the condition's step", () => {
    state.result = {
      steps: [{ block: "underwriter", to: null, text: "Can 1228 move to closing?" }],
      left_out: [],
      refusal: null,
    };
    const { onAddAll } = show("push_back");
    turn("Ask the underwriter to move 1228 to closing");
    expect(screen.getByText(/We draft the note from the condition\. Put this in it/)).toBeTruthy();
    expect(screen.getByText(/It replaces this condition’s own step\./)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Add this step" }));
    expect(onAddAll).toHaveBeenCalledWith([{ kind: "own_step", option: "ask_underwriter" }], []);
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

describe("LP-971 review — her words and the question block", () => {
  it("keeps her words on screen when a question took them, since the note does not", () => {
    state.result = {
      steps: [{ block: "underwriter", to: null, text: "Can 1228 move to closing?" }],
      left_out: [],
      refusal: null,
    };
    show();
    turn("Ask the underwriter to move 1228 to closing, it's new construction");
    fireEvent.click(screen.getByRole("button", { name: "Add this step" }));

    // The step told her to put these words in the note; they are still here to copy.
    expect(
      (screen.getByLabelText("Or describe what you want to do") as HTMLTextAreaElement).value,
    ).toBe("Ask the underwriter to move 1228 to closing, it's new construction");
  });

  it("clears them for a task, whose name carries them into the plan (the control)", () => {
    state.result = {
      steps: [{ block: "todo", to: null, text: "Call the builder" }],
      left_out: [],
      refusal: null,
    };
    show();
    turn("call the builder about the final inspection");
    fireEvent.click(screen.getByRole("button", { name: "Add this step" }));

    expect(
      (screen.getByLabelText("Or describe what you want to do") as HTMLTextAreaElement).value,
    ).toBe("");
  });

  describe("LP-971 follow-up — what each step adds to the path", () => {
    it("an email the server checks as the condition's document adds five steps, named", () => {
      state.result = {
        steps: [
          {
            block: "email",
            to: "other_party",
            text: "Please provide invoice for credit report",
            document_kinds: ["service invoice"],
          },
        ],
        left_out: [],
        refusal: null,
      };
      show();
      turn("Send email to credit report vendor, receive an email and attach here");
      const proposed = within(screen.getByRole("list", { name: "Proposed steps" }));
      expect(proposed.getByText("Adds 5 steps to the path")).toBeTruthy();
      expect(proposed.getByText(/We check it’s a service invoice/)).toBeTruthy();
      expect(proposed.queryByText(/Nothing checks what comes back/)).toBeNull();
    });

    it("one nothing can check says so, and a to-do (which brings nothing) does not", () => {
      state.result = {
        steps: [
          { block: "email", to: "title", text: "The payoff letter", document_kinds: [] },
          { block: "todo", to: null, text: "Call the builder", document_kinds: [] },
        ],
        left_out: [],
        refusal: null,
      };
      show();
      turn("Ask title for the payoff letter and I'll call the builder");
      const [email, todo] = within(screen.getByRole("list", { name: "Proposed steps" }))
        .getAllByRole("listitem", { name: "" })
        .filter((li) => li.parentElement?.getAttribute("aria-label") === "Proposed steps");
      expect(email?.textContent).toContain("Adds 4 steps to the path");
      expect(email?.textContent).toContain("Nothing checks what comes back");
      expect(todo?.textContent).not.toContain("Nothing checks what comes back");
    });
  });
});
