// @vitest-environment jsdom
import type { LtvCalculation } from "@/lib/types/ltv";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const setMutate = vi.fn();
const clearMutate = vi.fn();
const useLtvMock = vi.fn();

vi.mock("@/lib/api/ltv", () => ({
  useLtv: () => useLtvMock(),
  useSetLtvOverride: () => ({ mutate: setMutate, isPending: false }),
  useClearLtvOverride: () => ({ mutate: clearMutate, isPending: false }),
}));

import { LtvCalculator } from "./ltv-calculator";

const CALC: LtvCalculation = {
  ltv: "94.74",
  cltv: "94.74",
  hcltv: "100.00",
  value_basis: "190000.00",
  value_basis_label: "lesser of (purchase price, appraised value)",
  loan_items: [
    {
      key: "ltv.first_loan",
      label: "First mortgage",
      auto_amount: "180000.00",
      override_amount: null,
      amount: "180000.00",
      source: "stated",
      overridden: false,
    },
    {
      key: "ltv.heloc_credit_limit",
      label: "HELOC credit limit",
      auto_amount: null,
      override_amount: "20000.00",
      amount: "20000.00",
      source: "override",
      overridden: true,
    },
  ],
  value_items: [
    {
      key: "ltv.purchase_price",
      label: "Purchase price",
      auto_amount: "190000.00",
      override_amount: null,
      amount: "190000.00",
      source: "stated",
      overridden: false,
    },
    {
      key: "ltv.appraised_value",
      label: "Appraised value",
      auto_amount: "200000.00",
      override_amount: null,
      amount: "200000.00",
      source: "stated",
      overridden: false,
    },
  ],
  ltv_formula: "LTV = first loan ÷ lesser of (purchase price, appraised value)",
  cltv_formula: "CLTV = (first loan + second loan + HELOC drawn balance) ÷ property value",
  hcltv_formula: "HCLTV = (first loan + second loan + HELOC credit limit) ÷ property value",
  purpose: "purchase",
  program: "conventional",
  limit: {
    ltv_max: "97",
    source: "program_default",
    lender_slug: null,
    rule_id: "conv.ltv.purchase_max",
    purpose_basis: "purchase",
    status: "pass",
  },
  findings: { unresolved: false, open_in_scope_count: 0 },
};

function mockLtv(overrides: Partial<ReturnType<typeof useLtvMock>> = {}) {
  useLtvMock.mockReturnValue({
    data: CALC,
    isPending: false,
    isError: false,
    refetch: vi.fn(),
    ...overrides,
  });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("LtvCalculator", () => {
  it("renders the three ratios, the lesser-of basis, the limit and the formulas", () => {
    mockLtv();
    render(<LtvCalculator fileId="LF-1" />);

    // Three ratios (LTV appears in the hero and the formula receipt).
    expect(screen.getAllByText("94.74%").length).toBeGreaterThan(0);
    expect(screen.getByText("100.00%")).toBeDefined(); // HCLTV
    // The "lesser of" value basis is made visible.
    expect(screen.getByText(/Value basis · lesser of/)).toBeDefined();
    // The limit side-by-side.
    expect(screen.getByText("Within limit")).toBeDefined();
    expect(screen.getByText(/97.00% limit/)).toBeDefined();
    // The HCLTV formula (credit limit, not balance) is shown.
    expect(
      screen.getByText("HCLTV = (first loan + second loan + HELOC credit limit) ÷ property value"),
    ).toBeDefined();
  });

  it("shows the refinance purpose and the unresolved alert", () => {
    mockLtv({
      data: {
        ...CALC,
        purpose: "cash_out_refinance",
        findings: { unresolved: true, open_in_scope_count: 1 },
      },
    });
    render(<LtvCalculator fileId="LF-1" />);
    expect(screen.getByText("Cash out refinance")).toBeDefined();
    expect(screen.getByRole("alert")).toBeDefined();
  });

  it("flags over-limit in red", () => {
    mockLtv({
      data: { ...CALC, ltv: "85.00", limit: { ...CALC.limit, ltv_max: "80", status: "over" } },
    });
    render(<LtvCalculator fileId="LF-1" />);
    expect(screen.getByText("Over limit")).toBeDefined();
  });

  it("opens an inline editor and saves an override (real-time recalc trigger)", () => {
    mockLtv();
    render(<LtvCalculator fileId="LF-1" />);

    fireEvent.click(screen.getByRole("button", { name: /\$180,000\.00/ }));
    const input = screen.getByLabelText("Override First mortgage");
    fireEvent.change(input, { target: { value: "170000" } });
    fireEvent.click(screen.getByLabelText("Save override"));

    expect(setMutate).toHaveBeenCalledWith({
      fieldKey: "ltv.first_loan",
      input: { amount: "170000" },
    });
  });

  it("renders the loading skeleton while pending", () => {
    mockLtv({ data: undefined, isPending: true });
    render(<LtvCalculator fileId="LF-1" />);
    expect(screen.getByText("Calculating loan-to-value")).toBeDefined();
  });

  it("renders an error with retry", () => {
    const refetch = vi.fn();
    mockLtv({ data: undefined, isError: true, refetch });
    render(<LtvCalculator fileId="LF-1" />);
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalled();
  });
});
