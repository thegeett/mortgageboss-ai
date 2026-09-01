// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// `vi.mock` is hoisted above every const, so the doubles have to be hoisted with it.
const { mutate, state, toasts } = vi.hoisted(() => ({
  mutate: vi.fn(),
  state: { isPending: false },
  toasts: { success: vi.fn(), info: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/api/documents", () => ({
  useReprocessDocuments: () => ({ mutate, isPending: state.isPending }),
}));
vi.mock("sonner", () => ({ toast: toasts }));

import { ReprocessAll } from "./reprocess-all";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  state.isPending = false;
});

/** Fire the button and hand the component the result the server would have returned. */
function pressAndResolve(result: {
  queued: number;
  queued_document_ids: string[];
  skipped: Record<string, number>;
}) {
  fireEvent.click(screen.getByRole("button"));
  const call = mutate.mock.calls[0];
  expect(call).toBeDefined();
  call?.[1].onSuccess(result);
}

describe("ReprocessAll", () => {
  it("is not rendered for a file with no documents", () => {
    const { container } = render(<ReprocessAll fileId="f1" documentCount={0} />);
    expect(container.innerHTML).toBe("");
  });

  it("reports the skips, not just the successes", () => {
    // THE POINT OF SURFACING THEM. A bulk action that quietly does less than asked leaves a
    // processor watching for ten documents to change when seven were sent — which is
    // indistinguishable from a slow queue.
    render(<ReprocessAll fileId="f1" documentCount={10} />);

    pressAndResolve({
      queued: 7,
      queued_document_ids: ["a", "b", "c", "d", "e", "f", "g"],
      skipped: { already_processing: 2, type_set_by_a_person: 1 },
    });

    expect(toasts.success).toHaveBeenCalledTimes(1);
    const call = toasts.success.mock.calls[0];
    expect(call).toBeDefined();
    expect(call?.[0]).toContain("7 documents");
    expect(call?.[1].description).toContain("2 already processing");
    expect(call?.[1].description).toContain("1 type set by a person");
  });

  it("says nothing was queued rather than claiming success", () => {
    // A "Re-reading 0 documents" toast is worse than no action at all: it tells a processor work
    // is happening that is not.
    render(<ReprocessAll fileId="f1" documentCount={3} />);

    pressAndResolve({ queued: 0, queued_document_ids: [], skipped: { already_classified: 3 } });

    expect(toasts.success).not.toHaveBeenCalled();
    expect(toasts.info).toHaveBeenCalledTimes(1);
    const info = toasts.info.mock.calls[0];
    expect(info).toBeDefined();
    expect(info?.[1].description).toContain("3 already classified");
  });

  it("uses the singular for one document", () => {
    render(<ReprocessAll fileId="f1" documentCount={1} />);

    pressAndResolve({ queued: 1, queued_document_ids: ["a"], skipped: {} });

    const singular = toasts.success.mock.calls[0];
    expect(singular).toBeDefined();
    expect(singular?.[0]).toContain("1 document");
    expect(singular?.[0]).not.toContain("1 documents");
  });

  it("is disabled while a press is in flight", () => {
    // Load-bearing rather than polish: the server's in-flight check cannot stop a double-click,
    // because a document's status only moves once a worker picks the task up. At batch scale a
    // second press would double-enqueue the whole file.
    state.isPending = true;
    render(<ReprocessAll fileId="f1" documentCount={5} />);

    expect((screen.getByRole("button") as HTMLButtonElement).disabled).toBe(true);
  });

  it("surfaces a failure instead of failing silently", () => {
    render(<ReprocessAll fileId="f1" documentCount={5} />);
    fireEvent.click(screen.getByRole("button"));
    const call = mutate.mock.calls[0];
    expect(call).toBeDefined();

    call?.[1].onError(new Error("boom"));

    expect(toasts.error).toHaveBeenCalledTimes(1);
  });
});
