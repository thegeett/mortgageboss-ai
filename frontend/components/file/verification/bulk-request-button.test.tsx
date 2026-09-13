// @vitest-environment jsdom
/**
 * LP-851 Screen 6 — "Request all", folded in.
 *
 * THE PROPERTY IS THAT THE CONFIRM GROWS, not that a dialog appears. "Never two dialogs in
 * sequence" is invisible to `getByRole("dialog")`, which passes for one dialog and for the first of
 * two — so every case here counts them, and the title and the document list are asserted to still
 * be on screen underneath the new question.
 */
import type { DraftConflict } from "@/lib/api/draft-conflict";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BulkRequestButton } from "./bulk-request-button";

afterEach(cleanup);

const CONFLICT: DraftConflict = {
  message: "There is already an open draft to the borrower.",
  decisions_required: [
    {
      party: "borrower",
      open_draft: {
        id: "d1",
        created_at: "2026-09-08T14:02:00Z",
        needs: [{ id: "n1", title: "Bank statement — March" }],
        body_edited: false,
        edited_excerpt: null,
      },
      adding: [{ id: "n2", title: "credit report" }],
    },
  ],
  would_create: [],
};

/** An axios-shaped 409 carrying LP-850's refusal. */
function refusal() {
  return {
    isAxiosError: true,
    response: { status: 409, data: { error: { data: CONFLICT } } },
  };
}

const DOCUMENTS = ["credit report", "pay stub"];

/**
 * Hand the component an error the way its caller's mutation does.
 *
 * INSIDE `act`, because this is a raw callback rather than a DOM event: React batches the state
 * updates it makes and does not flush them, so without this the assertions read the tree as it was
 * BEFORE the refusal arrived — which looks exactly like a component that ignored it.
 */
function deliver(onError: (error: unknown) => void, error: unknown) {
  act(() => onError(error));
}

describe("BulkRequestButton", () => {
  it("confirms before it asks for anything", () => {
    const onConfirm = vi.fn();
    render(<BulkRequestButton documents={DOCUMENTS} onConfirm={onConfirm} />);

    fireEvent.click(screen.getByRole("button", { name: /Request all 2/ }));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByText("credit report")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Looks good" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm.mock.calls[0]?.[0]).toBeUndefined();
  });

  it("GROWS when a draft is open — one dialog, not two", () => {
    // The rule. A processor who has just confirmed five documents and is then asked a second
    // question clicks the primary without reading it.
    const onConfirm = vi.fn();
    render(<BulkRequestButton documents={DOCUMENTS} onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole("button", { name: /Request all 2/ }));
    fireEvent.click(screen.getByRole("button", { name: "Looks good" }));

    // The server refuses.
    deliver(onConfirm.mock.calls[0]?.[1] as (error: unknown) => void, refusal());

    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    // AND IT IS STILL THE SAME DIALOG. What the processor confirmed is on screen while they answer
    // the second question — the difference between one dialog that grew and two that replaced each
    // other.
    expect(screen.getByText(/Request 2 documents\?/)).toBeTruthy();
    expect(screen.getByText("credit report")).toBeTruthy();
    // With the open draft's contents and the new actions.
    expect(screen.getByText(/Bank statement — March/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Add to the open draft" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Mark sent, start new" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Looks good" })).toBeNull();
  });

  it("re-sends the SAME request with the processor's answer", () => {
    const onConfirm = vi.fn();
    render(<BulkRequestButton documents={DOCUMENTS} onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole("button", { name: /Request all 2/ }));
    fireEvent.click(screen.getByRole("button", { name: "Looks good" }));
    deliver(onConfirm.mock.calls[0]?.[1] as (error: unknown) => void, refusal());

    fireEvent.click(screen.getByRole("button", { name: "Add to the open draft" }));

    expect(onConfirm).toHaveBeenCalledTimes(2);
    expect(onConfirm.mock.calls[1]?.[0]).toBe("append");
  });

  it("an ordinary failure is not turned into a decision", () => {
    // `capture` is narrow on purpose: a helper that swallowed a real failure into a dialog nobody
    // could answer would be worse than no dialog at all.
    const onConfirm = vi.fn();
    render(<BulkRequestButton documents={DOCUMENTS} onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole("button", { name: /Request all 2/ }));
    fireEvent.click(screen.getByRole("button", { name: "Looks good" }));

    deliver(onConfirm.mock.calls[0]?.[1] as (error: unknown) => void, new Error("boom"));

    expect(screen.queryAllByRole("dialog")).toHaveLength(0);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("cancelling after the refusal asks for nothing more", () => {
    const onConfirm = vi.fn();
    render(<BulkRequestButton documents={DOCUMENTS} onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole("button", { name: /Request all 2/ }));
    fireEvent.click(screen.getByRole("button", { name: "Looks good" }));
    deliver(onConfirm.mock.calls[0]?.[1] as (error: unknown) => void, refusal());

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryAllByRole("dialog")).toHaveLength(0);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});
