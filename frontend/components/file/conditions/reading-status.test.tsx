// @vitest-environment jsdom
/**
 * LP-952 — the reading's state above the plan: running, failed, never started, or nothing (all read).
 */
import type { ReadingState } from "@/lib/types/conditions";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  data: undefined as ReadingState | undefined,
  read: [] as unknown[],
}));
vi.mock("@/lib/api/conditions", () => ({
  useReadingState: () => ({ data: state.data }),
  useReadAgain: () => ({ isPending: false, mutate: (id: unknown) => state.read.push(id) }),
}));

import { ReadingStatus } from "./reading-status";

afterEach(() => {
  cleanup();
  state.read = [];
});

function show(data: ReadingState) {
  state.data = data;
  return render(<ReadingStatus fileId="f1" roundId="r2" />);
}

describe("ReadingStatus", () => {
  it("says the conditions are being read while it runs, with no button", () => {
    show({ state: "reading", unread: 6, error: null });
    expect(screen.getByText(/Reading 6 conditions…/)).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("offers Read conditions when nothing is queued (LF-DH8V's round 1)", () => {
    show({ state: "not_queued", unread: 6, error: null });
    expect(screen.getByText("6 conditions have not been read.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Read conditions" }));
    expect(state.read).toEqual(["r2"]);
  });

  it("says a stalled reading stopped and offers Read again", () => {
    show({ state: "failed", unread: 1, error: "stalled" });
    expect(screen.getByText(/The reading stopped before it finished/)).toBeTruthy();
    expect(screen.getByText(/1 condition still unread/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Read again" }));
    expect(state.read).toEqual(["r2"]);
  });

  it("renders nothing once every condition is read", () => {
    const { container } = show({ state: "done", unread: 0, error: null });
    expect(container.innerHTML).toBe("");
  });

  it("LP-973: read without the AI, it says so and offers Read again", () => {
    // The state the server reports when the model call failed and the library read them: nothing is
    // unread, so LP-952's own branches offered nothing.
    show({ state: "without_ai", unread: 0, without_ai: 6, error: null });
    expect(screen.getByText("6 conditions were read without the AI.")).toBeTruthy();
    expect(screen.getByText(/their plans are guesses from the sheet/)).toBeTruthy();
    expect(screen.getByText(/anything you have already worked on is kept/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Read again" }));
    expect(state.read).toEqual(["r2"]);
  });

  it("LP-973: one condition reads in the singular", () => {
    show({ state: "without_ai", unread: 0, without_ai: 1, error: null });
    expect(screen.getByText("1 condition was read without the AI.")).toBeTruthy();
    expect(screen.getByText(/its plan is a guess/)).toBeTruthy();
  });
});
