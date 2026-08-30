// @vitest-environment jsdom
import type { StatedFinancials } from "@/lib/types/stated-financials";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const useStatedFinancials = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/mismo", () => ({ useStatedFinancials }));

import { StatedFinancialsSection } from "./stated-financials-section";

afterEach(() => {
  cleanup();
  useStatedFinancials.mockReset();
});

function financials(overrides: Partial<StatedFinancials> = {}): StatedFinancials {
  return {
    borrowers: [
      {
        id: "b1",
        full_name: "Mahesh Chhotala",
        masked_ssn: "•••-••-2233",
        date_of_birth: "1984-02-17",
        marital_status: "Married",
        dependent_count: 3,
        citizenship: "PermanentResidentAlien",
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
        paid_off_at_closing: null,
        payoff_source: null,
      },
    ],
    assets: [{ id: "ast1", asset_type: "GiftOfCash", value: "56000.00", holder_name: "Relative" }],
    loan_terms: {
      note_amount: "1104000.00",
      note_rate_percent: "6.8750",
      lien_priority: "FirstLien",
      amortization_type: "Fixed",
      amortization_months: 360,
      application_received_date: "2026-06-02",
    },
    property_extras: null,
    mismo_import: {
      source_format: "xml",
      status: "completed",
      warnings: [],
      imported_at: "2026-06-12T00:00:00Z",
    },
    ...overrides,
  };
}

describe("StatedFinancialsSection", () => {
  it("renders the imported stated financials (income, liabilities, assets)", () => {
    useStatedFinancials.mockReturnValue({ data: financials(), isPending: false, isError: false });
    render(<StatedFinancialsSection fileId="LF-1" />);
    expect(screen.getByText("Application data (stated)")).toBeDefined();
    expect(screen.getByText("Mahesh Chhotala")).toBeDefined();
    expect(screen.getByText(/Cascade Logistics LLC/)).toBeDefined();
    expect(screen.getByText("MortgageLoan · NR/SMS/CAL")).toBeDefined();
    expect(screen.getByText("GiftOfCash · Relative")).toBeDefined();
  });

  it("no longer renders the parse warnings itself (LP-UI-024)", () => {
    // They were here — inside the section a reader opens only if they already
    // suspect something — and they could not link anywhere, because a warning
    // was a bare sentence. `MismoWarnings` renders them at the top of the
    // Overview with a link per subject, and mismo-warnings.test.tsx pins them
    // there. Two renderings of one list is how they drift; this asserts where
    // they are NOT, so the move stays visible.
    useStatedFinancials.mockReturnValue({
      data: financials({
        mismo_import: {
          source_format: "xml",
          status: "partial",
          warnings: [
            { message: "Subject property is missing an estimated value.", subject: "property" },
          ],
          imported_at: "2026-06-12T00:00:00Z",
        },
      }),
      isPending: false,
      isError: false,
    });
    render(<StatedFinancialsSection fileId="LF-1" />);
    expect(screen.queryByText("Subject property is missing an estimated value.")).toBeNull();
    // Positive control: the section rendered, so the absence above is real.
    expect(screen.getByText(/Application data/i)).toBeDefined();
  });

  it("renders nothing for a file with no stated data (e.g. manual creation)", () => {
    useStatedFinancials.mockReturnValue({
      data: {
        borrowers: [],
        liabilities: [],
        assets: [],
        loan_terms: {
          note_amount: null,
          note_rate_percent: null,
          lien_priority: null,
          amortization_type: null,
          amortization_months: null,
          application_received_date: null,
        },
        property_extras: null,
        mismo_import: null,
      },
      isPending: false,
      isError: false,
    });
    const { container } = render(<StatedFinancialsSection fileId="LF-1" />);
    expect(container.firstChild).toBeNull();
  });

  it("shows a retry error state when the read fails", () => {
    useStatedFinancials.mockReturnValue({
      data: undefined,
      isPending: false,
      isError: true,
      refetch: vi.fn(),
    });
    render(<StatedFinancialsSection fileId="LF-1" />);
    expect(screen.getByText(/couldn't load the imported application data/i)).toBeDefined();
  });
});
