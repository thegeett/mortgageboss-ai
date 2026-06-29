// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const deleteMutate = vi.fn();
const mockDelete = vi.hoisted(() => ({ isPending: false }));
const toastSuccess = vi.fn();
const toastError = vi.fn();

vi.mock("@/lib/api/loan-files", () => ({
  useDeleteLoanFile: () => ({ mutate: deleteMutate, isPending: mockDelete.isPending }),
}));

vi.mock("sonner", () => ({
  toast: {
    success: (...a: unknown[]) => toastSuccess(...a),
    error: (...a: unknown[]) => toastError(...a),
  },
}));

import { DeleteFileDialog } from "./delete-file-dialog";

const FILE = { id: "uuid-1", display_id: "LF-1234", primary_borrower_name: "Mahesh Chhotala" };

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockDelete.isPending = false;
});

describe("DeleteFileDialog", () => {
  it("names the file and what's affected (not a silent destroy)", () => {
    render(<DeleteFileDialog file={FILE} open onOpenChange={vi.fn()} />);
    expect(screen.getByText("Delete this loan file?")).toBeDefined();
    expect(screen.getByText("Mahesh Chhotala")).toBeDefined();
    expect(screen.getByText(/LF-1234/)).toBeDefined();
    // Impact + recoverability are spelled out.
    expect(screen.getByText(/documents, extracted data, and findings/)).toBeDefined();
    expect(screen.getByText(/undone by an admin/)).toBeDefined();
  });

  it("confirm triggers the delete with the file id", () => {
    render(<DeleteFileDialog file={FILE} open onOpenChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /delete file/i }));
    expect(deleteMutate).toHaveBeenCalledTimes(1);
    expect(deleteMutate.mock.calls[0]?.[0]).toBe("uuid-1");
  });

  it("on success: toasts, closes, and calls onDeleted", () => {
    deleteMutate.mockImplementation((_id, opts) => opts?.onSuccess?.());
    const onOpenChange = vi.fn();
    const onDeleted = vi.fn();
    render(<DeleteFileDialog file={FILE} open onOpenChange={onOpenChange} onDeleted={onDeleted} />);
    fireEvent.click(screen.getByRole("button", { name: /delete file/i }));
    expect(toastSuccess).toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onDeleted).toHaveBeenCalled();
  });

  it("on error: toasts the error and does not close", () => {
    deleteMutate.mockImplementation((_id, opts) => opts?.onError?.(new Error("boom")));
    const onOpenChange = vi.fn();
    render(<DeleteFileDialog file={FILE} open onOpenChange={onOpenChange} />);
    fireEvent.click(screen.getByRole("button", { name: /delete file/i }));
    expect(toastError).toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("cancel closes without deleting", () => {
    const onOpenChange = vi.fn();
    render(<DeleteFileDialog file={FILE} open onOpenChange={onOpenChange} />);
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(deleteMutate).not.toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("shows a deleting state and disables the buttons while in flight", () => {
    mockDelete.isPending = true;
    render(<DeleteFileDialog file={FILE} open onOpenChange={vi.fn()} />);
    expect(screen.getByText("Deleting…")).toBeDefined();
    expect(screen.getByRole("button", { name: /deleting/i })).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: /cancel/i })).toHaveProperty("disabled", true);
  });

  it("falls back to a generic name when the borrower is unknown", () => {
    render(
      <DeleteFileDialog
        file={{ ...FILE, primary_borrower_name: null }}
        open
        onOpenChange={vi.fn()}
      />,
    );
    expect(screen.getByText("this file")).toBeDefined();
  });
});
