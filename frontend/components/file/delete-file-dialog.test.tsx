// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const deleteMutate = vi.fn();
const mockDelete = vi.hoisted(() => ({ isPending: false }));
const toastSuccess = vi.fn();
const toastError = vi.fn();
const documentsData = vi.hoisted(() => ({ value: undefined as unknown }));

vi.mock("@/lib/api/loan-files", () => ({
  useDeleteLoanFile: () => ({ mutate: deleteMutate, isPending: mockDelete.isPending }),
}));

// The dialog counts the file's documents while it is open (LP-UI-035).
vi.mock("@/lib/api/documents", () => ({
  useLoanFileDocuments: () => ({ data: documentsData.value }),
}));

vi.mock("sonner", () => ({
  toast: {
    success: (...a: unknown[]) => toastSuccess(...a),
    error: (...a: unknown[]) => toastError(...a),
  },
}));

import { DeleteFileDialog } from "./delete-file-dialog";

const FILE = {
  id: "uuid-1",
  display_id: "LF-1234",
  primary_borrower_name: "Mahesh Chhotala",
  property_address: "60 North Street",
};

/** Type the id, which is what arms the delete button (LP-UI-035). */
function confirmId(id = FILE.display_id) {
  fireEvent.change(screen.getByLabelText(/to confirm/i), { target: { value: id } });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockDelete.isPending = false;
  documentsData.value = undefined;
});

describe("DeleteFileDialog", () => {
  it("names the file and what's affected (not a silent destroy)", () => {
    render(<DeleteFileDialog file={FILE} open onOpenChange={vi.fn()} />);
    // The id is in the title: a processor with two tabs open must see WHICH
    // file without reading the body.
    expect(screen.getByText("Delete LF-1234?")).toBeDefined();
    expect(screen.getByText("Mahesh Chhotala")).toBeDefined();
    // The id now appears twice — in the title and in the "type this" label —
    // which is the point of both, so assert on each rather than on the pattern.
    expect(screen.getAllByText(/LF-1234/).length).toBeGreaterThanOrEqual(2);
    // Impact + recoverability are spelled out.
    expect(screen.getByText(/extracted data and findings/)).toBeDefined();
    expect(screen.getByText(/an administrator can restore it/i)).toBeDefined();
  });

  it("names HOW MANY documents go with it once the count arrives", () => {
    // "Twelve documents" is what makes a processor stop. "Its data" is what they
    // already agreed to by clicking Delete.
    documentsData.value = [
      { id: "a", is_current: true, status: "completed" },
      { id: "b", is_current: true, status: "completed" },
    ];
    render(<DeleteFileDialog file={FILE} open onOpenChange={vi.fn()} />);
    expect(screen.getByText(/2 documents/)).toBeDefined();
  });

  it("omits the count rather than guessing while it loads", () => {
    // A wrong number on a destructive confirmation is worse than no number.
    render(<DeleteFileDialog file={FILE} open onOpenChange={vi.fn()} />);
    expect(screen.getByText(/Its documents, extracted data and findings/)).toBeDefined();
  });

  describe("the typed-id gate", () => {
    it("keeps the delete button disabled until the id is typed", () => {
      render(<DeleteFileDialog file={FILE} open onOpenChange={vi.fn()} />);
      const button = screen.getByRole("button", { name: /delete file/i });
      expect(button.hasAttribute("disabled")).toBe(true);
      confirmId();
      expect(button.hasAttribute("disabled")).toBe(false);
    });

    it("does not accept a near miss", () => {
      render(<DeleteFileDialog file={FILE} open onOpenChange={vi.fn()} />);
      confirmId("LF-1233");
      expect(screen.getByRole("button", { name: /delete file/i }).hasAttribute("disabled")).toBe(
        true,
      );
    });

    it("accepts the id in lower case", () => {
      // The gate exists to defeat a muscle-memory click, not to test typing. A
      // processor who typed the id has demonstrated everything it asks for.
      render(<DeleteFileDialog file={FILE} open onOpenChange={vi.fn()} />);
      confirmId("lf-1234");
      expect(screen.getByRole("button", { name: /delete file/i }).hasAttribute("disabled")).toBe(
        false,
      );
    });
  });

  it("confirm triggers the delete with the file id", () => {
    render(<DeleteFileDialog file={FILE} open onOpenChange={vi.fn()} />);
    confirmId();
    fireEvent.click(screen.getByRole("button", { name: /delete file/i }));
    expect(deleteMutate).toHaveBeenCalledTimes(1);
    expect(deleteMutate.mock.calls[0]?.[0]).toBe("uuid-1");
  });

  it("on success: toasts, closes, and calls onDeleted", () => {
    deleteMutate.mockImplementation((_id, opts) => opts?.onSuccess?.());
    const onOpenChange = vi.fn();
    const onDeleted = vi.fn();
    render(<DeleteFileDialog file={FILE} open onOpenChange={onOpenChange} onDeleted={onDeleted} />);
    confirmId();
    fireEvent.click(screen.getByRole("button", { name: /delete file/i }));
    expect(toastSuccess).toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onDeleted).toHaveBeenCalled();
  });

  it("on error: toasts the error and does not close", () => {
    deleteMutate.mockImplementation((_id, opts) => opts?.onError?.(new Error("boom")));
    const onOpenChange = vi.fn();
    render(<DeleteFileDialog file={FILE} open onOpenChange={onOpenChange} />);
    confirmId();
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
