// @vitest-environment jsdom
import type { StatedFinancials } from "@/lib/types/stated-financials";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Capture the mutation calls without a real query client / network.
const updateRow = vi.hoisted(() => vi.fn());
const deleteRow = vi.hoisted(() => vi.fn());
const addLiability = vi.hoisted(() => vi.fn());
const updateLoanTerms = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api/mismo", () => ({
  useStatedFinancialsEdit: () => ({
    updateRow: { mutate: updateRow, isPending: false },
    deleteRow: { mutate: deleteRow, isPending: false },
    addLiability: { mutate: addLiability, isPending: false },
    addAsset: { mutate: vi.fn(), isPending: false },
    addIncome: { mutate: vi.fn(), isPending: false },
    addEmployer: { mutate: vi.fn(), isPending: false },
    updateLoanTerms: { mutate: updateLoanTerms, isPending: false },
  }),
}));

import { StatedFinancialsEditor } from "./stated-financials-editor";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function financials(): StatedFinancials {
  return {
    borrowers: [
      {
        id: "b1",
        full_name: "Mahesh Chhotala",
        masked_ssn: "•••-••-2233",
        date_of_birth: null,
        marital_status: null,
        dependent_count: null,
        citizenship: null,
        is_primary: true,
        declarations: null,
        income_items: [
          { id: "inc1", monthly_amount: "7000.00", income_type: "Base", employment_income: true },
        ],
        employers: [{ id: "emp1", employer_name: "Cascade Logistics LLC", is_current: true }],
      },
    ],
    liabilities: [
      {
        id: "liab1",
        liability_type: "MortgageLoan",
        monthly_payment: "4263.00",
        unpaid_balance: "582417.00",
        holder_name: "NR/SMS/CAL",
      },
    ],
    assets: [{ id: "ast1", asset_type: "GiftOfCash", value: "56000.00", holder_name: "Relative" }],
    loan_terms: {
      note_amount: "1104000.00",
      note_rate_percent: "6.8750",
      lien_priority: "FirstLien",
      amortization_type: "Fixed",
      amortization_months: 360,
      application_received_date: null,
    },
    property_extras: null,
    mismo_import: null,
  };
}

describe("StatedFinancialsEditor", () => {
  it("PATCHes only the changed field of a liability row", () => {
    render(<StatedFinancialsEditor fileId="LF-1" data={financials()} />);
    const monthly = screen.getByDisplayValue("4263.00");
    fireEvent.change(monthly, { target: { value: "4000.00" } });
    const saveButtons = screen.getAllByRole("button", { name: /save/i });
    // The liability row's Save (first matching the changed row) fires the update.
    for (const b of saveButtons) fireEvent.click(b);
    expect(updateRow).toHaveBeenCalledWith(
      { kind: "stated-liabilities", id: "liab1", body: { monthly_payment: "4000.00" } },
      expect.anything(),
    );
  });

  it("does not fire a save when nothing changed", () => {
    render(<StatedFinancialsEditor fileId="LF-1" data={financials()} />);
    // Save buttons start disabled (no dirty rows) → clicking does nothing.
    const saveButtons = screen.getAllByRole("button", { name: /save/i });
    for (const b of saveButtons) fireEvent.click(b);
    expect(updateRow).not.toHaveBeenCalled();
  });

  it("removes a row via the delete control", () => {
    render(<StatedFinancialsEditor fileId="LF-1" data={financials()} />);
    const removeButtons = screen.getAllByRole("button", { name: /remove row/i });
    const first = removeButtons.at(0);
    expect(first).toBeDefined();
    if (first) fireEvent.click(first);
    expect(deleteRow).toHaveBeenCalled();
  });

  it("adds a liability row", () => {
    render(<StatedFinancialsEditor fileId="LF-1" data={financials()} />);
    const addButtons = screen.getAllByRole("button", { name: /add/i });
    // Liabilities "Add" — click them all; only the liability adder is asserted.
    for (const b of addButtons) fireEvent.click(b);
    expect(addLiability).toHaveBeenCalled();
  });

  it("sends an empty edited field as null, not an empty string", () => {
    render(<StatedFinancialsEditor fileId="LF-1" data={financials()} />);
    const holder = screen.getByDisplayValue("NR/SMS/CAL");
    fireEvent.change(holder, { target: { value: "" } });
    for (const b of screen.getAllByRole("button", { name: /save/i })) fireEvent.click(b);
    expect(updateRow).toHaveBeenCalledWith(
      { kind: "stated-liabilities", id: "liab1", body: { holder_name: null } },
      expect.anything(),
    );
  });

  it("PATCHes the loan terms on the file", () => {
    render(<StatedFinancialsEditor fileId="LF-1" data={financials()} />);
    const rate = screen.getByDisplayValue("6.8750");
    fireEvent.change(rate, { target: { value: "7.0000" } });
    for (const b of screen.getAllByRole("button", { name: /save/i })) fireEvent.click(b);
    expect(updateLoanTerms).toHaveBeenCalledWith(
      expect.objectContaining({ note_rate_percent: "7.0000" }),
      expect.anything(),
    );
  });
});
