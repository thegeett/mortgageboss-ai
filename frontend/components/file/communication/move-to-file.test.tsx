// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockMove = vi.fn();
const mockFiles = vi.fn();
vi.mock("@/lib/api/inbound", () => ({
  useMoveMessage: () => ({ mutate: mockMove, isPending: false, isError: false, error: null }),
}));
vi.mock("@/lib/api/loan-files", () => ({
  useLoanFiles: (...args: unknown[]) => mockFiles(...args),
}));

import { MoveToFile } from "./move-to-file";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function open(items: unknown[] = []) {
  mockFiles.mockReturnValue({ data: { items }, isPending: false });
  render(<MoveToFile messageId="msg-1" />);
  fireEvent.click(screen.getByRole("button", { name: "Move to file" }));
}

describe("Move to file", () => {
  it("does not search until something is typed", () => {
    open([{ id: "f1", display_id: "LF-AAAA", primary_borrower_name: "Jane" }]);
    expect(mockFiles).toHaveBeenLastCalledWith(expect.anything(), { enabled: false });
    expect(screen.queryByText("LF-AAAA")).toBeNull();
  });

  it("searches what is typed and moves to the file picked", () => {
    open([{ id: "f1", display_id: "LF-AAAA", primary_borrower_name: "Jane Doe" }]);
    fireEvent.change(screen.getByLabelText("Search for a file"), { target: { value: "Jane" } });

    expect(mockFiles).toHaveBeenLastCalledWith({ search: "Jane", pageSize: 8 }, { enabled: true });
    fireEvent.click(screen.getByRole("button", { name: /LF-AAAA/ }));
    expect(mockMove.mock.calls[0]?.[0]).toEqual({ messageId: "msg-1", fileId: "f1" });
  });

  it("says so when nothing matches", () => {
    open([]);
    fireEvent.change(screen.getByLabelText("Search for a file"), { target: { value: "zzz" } });
    expect(screen.getByText("No file matches that.")).toBeTruthy();
  });
});
