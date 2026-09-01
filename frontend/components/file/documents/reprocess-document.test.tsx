// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { mutate, state, toasts } = vi.hoisted(() => ({
  mutate: vi.fn(),
  state: { isPending: false },
  toasts: { success: vi.fn(), info: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/api/documents", () => ({
  useReprocessDocument: () => ({ mutate, isPending: state.isPending }),
}));
vi.mock("sonner", () => ({ toast: toasts }));

import type { DocumentResponse, DocumentStatus } from "@/lib/types/document";
import { ReprocessDocumentButton } from "./reprocess-document";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  state.isPending = false;
});

function doc(status: DocumentStatus): DocumentResponse {
  return { id: "d1", status } as DocumentResponse;
}

/** A 409 as axios reports it, since the force affordance keys on the status code. */
function conflict() {
  return {
    isAxiosError: true,
    response: { status: 409, data: { error: { message: "type set by a person" } } },
  };
}

describe("ReprocessDocumentButton", () => {
  it("is disabled while the pipeline is still running", () => {
    // `isPending` covers only the request and drops the moment the POST returns, so the button
    // came back to life while the document sat queued. A processor who sees no visible change
    // presses again, the server ACCEPTS it — PENDING is deliberately not an in-flight status —
    // and the duplicate simply runs after the first: the atomic claim excludes concurrent runs,
    // not sequential ones. That is a second full classify+extract for one press too many.
    render(<ReprocessDocumentButton summary={doc("classifying")} fileId="f1" />);

    const button = screen.getByRole("button") as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.click(button);
    expect(mutate).not.toHaveBeenCalled();
  });

  it("is enabled once the document reaches a terminal status", () => {
    render(<ReprocessDocumentButton summary={doc("needs_review")} fileId="f1" />);

    const button = screen.getByRole("button") as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    fireEvent.click(button);
    expect(mutate).toHaveBeenCalledTimes(1);
    expect(mutate.mock.calls[0]?.[0]).toBe(false);
  });

  it("offers a way past a refusal instead of describing an unreachable one", () => {
    // The drawer's own "Correct type" control sets the very signal the server refuses on, so
    // correcting a type made this button permanently useless for that document — while the error
    // explained a way past it that the UI had no affordance for.
    render(<ReprocessDocumentButton summary={doc("completed")} fileId="f1" />);
    fireEvent.click(screen.getByRole("button"));
    mutate.mock.calls[0]?.[1].onError(conflict());

    const [, options] = toasts.error.mock.calls[0] ?? [];
    expect(options.action).toBeDefined();
    expect(options.action.label).toBe("Re-read anyway");

    options.action.onClick();
    expect(mutate).toHaveBeenCalledTimes(2);
    expect(mutate.mock.calls[1]?.[0]).toBe(true);
  });

  it("does not offer the retry again once it has already forced", () => {
    // Otherwise a refusal that force cannot lift — a superseded version, a live pipeline — would
    // hand the processor the same button forever.
    render(<ReprocessDocumentButton summary={doc("completed")} fileId="f1" />);
    fireEvent.click(screen.getByRole("button"));
    mutate.mock.calls[0]?.[1].onError(conflict());
    toasts.error.mock.calls[0]?.[1].action.onClick();
    mutate.mock.calls[1]?.[1].onError(conflict());

    expect(toasts.error.mock.calls[1]?.[1].action).toBeUndefined();
  });

  it("offers nothing extra on a failure force cannot lift", () => {
    render(<ReprocessDocumentButton summary={doc("completed")} fileId="f1" />);
    fireEvent.click(screen.getByRole("button"));
    mutate.mock.calls[0]?.[1].onError({ isAxiosError: true, response: { status: 503 } });

    expect(toasts.error.mock.calls[0]?.[1].action).toBeUndefined();
  });
});
