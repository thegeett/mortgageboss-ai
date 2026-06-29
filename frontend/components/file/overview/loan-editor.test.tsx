// @vitest-environment jsdom
import type { LoanFileDetail } from "@/lib/types/loan-file";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const updateMutate = vi.fn();
vi.mock("@/lib/api/overview-edit", () => ({
  useUpdateLoanFile: () => ({ mutate: updateMutate, isPending: false }),
}));
vi.mock("@/lib/api/lenders", () => ({
  useLenders: () => ({ data: [{ id: "L1", name: "UWM", supported_programs: ["conventional"] }] }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { LoanEditor } from "./loan-editor";

const FILE = {
  id: "LF-1",
  display_id: "LF-1",
  status: "in_processing",
  loan_program: "conventional",
  loan_purpose: "purchase",
  loan_amount: "100000",
  lender_id: null,
  lender_name: null,
  loan_officer_name: null,
  loan_officer_email: null,
} as unknown as LoanFileDetail;

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("LoanEditor", () => {
  it("saves an edited field inline (no confirmation)", () => {
    render(<LoanEditor file={FILE} />);
    fireEvent.change(screen.getByLabelText("Amount"), { target: { value: "120000" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    expect(updateMutate).toHaveBeenCalledTimes(1);
    expect(updateMutate.mock.calls[0]?.[0]).toEqual({ loan_amount: "120000" });
  });

  it("sets the target lender (the LP-80 overlay selector)", () => {
    render(<LoanEditor file={FILE} />);
    fireEvent.change(screen.getByLabelText("Target lender"), { target: { value: "L1" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    expect(updateMutate.mock.calls[0]?.[0]).toEqual({ lender_id: "L1" });
  });

  it("confirms a program change before saving", () => {
    render(<LoanEditor file={FILE} />);
    fireEvent.change(screen.getByLabelText("Program"), { target: { value: "fha" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    // Not saved yet — a confirmation appears (changing the program swaps the rule set).
    expect(updateMutate).not.toHaveBeenCalled();
    expect(screen.getByText(/Change the loan program/)).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: /change program/i }));
    expect(updateMutate).toHaveBeenCalledTimes(1);
    expect(updateMutate.mock.calls[0]?.[0]).toEqual({ loan_program: "fha" });
  });

  it("cancelling the program change does not save", () => {
    render(<LoanEditor file={FILE} />);
    fireEvent.change(screen.getByLabelText("Program"), { target: { value: "fha" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(updateMutate).not.toHaveBeenCalled();
  });
});
