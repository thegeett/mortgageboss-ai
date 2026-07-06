// @vitest-environment jsdom
import type { LoanFileSummary } from "@/lib/types/loan-file";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// The dialog has its own tests; stub it so the table test stays focused on wiring.
vi.mock("@/components/file/delete-file-dialog", () => ({
  DeleteFileDialog: ({ open, file }: { open: boolean; file: { display_id: string } | null }) =>
    open ? <div data-testid="delete-dialog">deleting {file?.display_id}</div> : null,
}));

import { FileTable } from "./file-table";

const FILE: LoanFileSummary = {
  id: "uuid-1",
  display_id: "LF-1234",
  status: "in_processing",
  loan_program: "conventional",
  loan_purpose: "purchase",
  loan_amount: null,
  lender_id: null,
  lender_name: "Acme Lending",
  property_address: "123 Main St",
  primary_borrower_name: "Mahesh Chhotala",
  created_at: "2026-06-01T00:00:00Z",
  updated_at: "2026-06-20T00:00:00Z",
};

function renderTable(over: Partial<React.ComponentProps<typeof FileTable>> = {}) {
  const onSelect = vi.fn();
  render(
    <FileTable
      files={[FILE]}
      isPending={false}
      isError={false}
      isFiltered={false}
      onSelect={onSelect}
      onNewFile={vi.fn()}
      {...over}
    />,
  );
  return { onSelect };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("FileTable — delete action", () => {
  it("renders a per-row actions trigger", () => {
    renderTable();
    expect(screen.getByRole("button", { name: /actions for LF-1234/i })).toBeDefined();
  });

  it("clicking the actions trigger does NOT navigate (stops propagation)", () => {
    const { onSelect } = renderTable();
    fireEvent.click(screen.getByRole("button", { name: /actions for LF-1234/i }));
    // The row navigates on click; the menu must not trigger it.
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("clicking the row body navigates to the file", () => {
    const { onSelect } = renderTable();
    fireEvent.click(screen.getByText("123 Main St"));
    expect(onSelect).toHaveBeenCalledWith(FILE);
  });

  it("does not show the delete dialog until an action is taken", () => {
    renderTable();
    expect(screen.queryByTestId("delete-dialog")).toBeNull();
  });

  it("selecting Delete from the menu opens the dialog and never navigates", () => {
    const { onSelect } = renderTable();
    // Open the menu (Radix opens on pointerdown), then choose Delete file.
    const trigger = screen.getByRole("button", { name: /actions for LF-1234/i });
    fireEvent.pointerDown(trigger, { button: 0 });
    fireEvent.click(trigger);
    fireEvent.click(screen.getByText("Delete file"));

    expect(screen.getByTestId("delete-dialog")).toBeDefined();
    // The whole point of the fix: choosing a row action must not navigate the row.
    expect(onSelect).not.toHaveBeenCalled();
  });
});
