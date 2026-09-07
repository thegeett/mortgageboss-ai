// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// A controllable mock of the upload mutation so we can flip `isPending`.
const mockUpload = vi.hoisted(() => ({ isPending: false, mutate: vi.fn() }));
vi.mock("@/lib/api/documents", () => ({
  useUploadDocuments: () => mockUpload,
}));

// LP-647 §2 — the dropzone asks whether a verification is running, so this module is reached at
// render. Mocked whole, the repo's pattern (22 files); the real hook needs a QueryClientProvider.
const mockVerification = { data: undefined as unknown };
vi.mock("@/lib/api/verification", () => ({
  useVerification: () => mockVerification,
}));

import { DocumentDropzone } from "./document-dropzone";

afterEach(() => {
  cleanup();
  mockUpload.isPending = false;
});

describe("DocumentDropzone — double-submit prevention", () => {
  it("enables the trigger when idle", () => {
    mockUpload.isPending = false;
    render(<DocumentDropzone fileId="f1" />);
    const button = screen.getByRole("button", { name: /browse files/i });
    expect(button).toBeDefined();
    expect((button as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByText("Drag documents here")).toBeDefined();
  });

  it("disables the trigger and shows 'Uploading…' while a upload is in flight", () => {
    mockUpload.isPending = true;
    render(<DocumentDropzone fileId="f1" />);
    const button = screen.getByRole("button", { name: /browse files/i });
    // Cannot be clicked again → no duplicate upload.
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Uploading…")).toBeDefined();
  });
});

describe("LP-647 §2 — uploads are held while a verification runs", () => {
  afterEach(() => {
    mockVerification.data = undefined;
  });

  /** NOT the same defect as the other direction, and the comment in the component says so: a
   *  document arriving mid-run corrupts nothing — the snapshot froze at enqueue and the upload marks
   *  the file stale, so it is picked up by the next run. What it produces is a confusion: a run
   *  finishes minutes later without the document just added, and nothing said it would not be
   *  included. Held so the processor is told, at the cost of a bounded wait. */
  it("disables the trigger and says when it comes back", () => {
    mockVerification.data = { latest_run: { status: "running" } };
    render(<DocumentDropzone fileId="LF-1" />);

    expect(
      (screen.getByRole("button", { name: /browse files/i }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(screen.getByText("Verification is running")).toBeTruthy();
    expect(screen.getByText(/held until it finishes/)).toBeTruthy();
  });

  /** THE POSITIVE CONTROL. A guard that disables unconditionally would satisfy the test above while
   *  making uploads unreachable — and the run finishing must release it without a reload. */
  it("is usable once the run is no longer running", () => {
    mockVerification.data = { latest_run: { status: "completed" } };
    render(<DocumentDropzone fileId="LF-1" />);

    expect(
      (screen.getByRole("button", { name: /browse files/i }) as HTMLButtonElement).disabled,
    ).toBe(false);
    expect(screen.queryByText("Verification is running")).toBeNull();
    expect(screen.getByText(/PDF, JPG, or PNG/)).toBeTruthy();
  });
});
