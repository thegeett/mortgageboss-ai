// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// A controllable mock of the upload mutation so we can flip `isPending`.
const mockUpload = vi.hoisted(() => ({ isPending: false, mutate: vi.fn() }));
vi.mock("@/lib/api/documents", () => ({
  useUploadDocuments: () => mockUpload,
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
