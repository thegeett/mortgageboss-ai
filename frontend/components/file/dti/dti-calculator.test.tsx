import type { DtiCalculation } from "@/lib/types/dti";
// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const setMutate = vi.fn();
const clearMutate = vi.fn();
const useDtiMock = vi.fn();

vi.mock("@/lib/api/dti", () => ({
  useDti: () => useDtiMock(),
  useSetDtiOverride: () => ({ mutate: setMutate, isPending: false }),
  useClearDtiOverride: () => ({ mutate: clearMutate, isPending: false }),
}));

import { DtiCalculator } from "./dti-calculator";

const CALC: DtiCalculation = {
  front_end_dti: "2.78",
  back_end_dti: "22.78",
  gross_monthly_income: "10000.00",
  housing_payment: "277.78",
  monthly_debts: "2000.00",
  total_monthly_obligations: "2277.78",
  income_items: [
    {
      key: "income.1",
      label: "Base — Pat",
      auto_amount: "10000.00",
      override_amount: null,
      amount: "10000.00",
      source: "stated",
      overridden: false,
    },
  ],
  housing_items: [
    {
      key: "housing.principal_interest",
      label: "Principal & interest",
      auto_amount: "277.78",
      override_amount: null,
      amount: "277.78",
      source: "computed",
      overridden: false,
    },
  ],
  debt_items: [
    {
      key: "debt.1",
      label: "Installment",
      auto_amount: "2000.00",
      override_amount: null,
      amount: "2000.00",
      source: "stated",
      overridden: false,
    },
  ],
  front_end_formula: "Front-end DTI = housing payment ÷ gross monthly income",
  back_end_formula: "Back-end DTI = (housing payment + monthly debts) ÷ gross monthly income",
  program: "conventional",
  limit: {
    back_end_max: "50",
    source: "program_default",
    lender_slug: null,
    rule_id: "conv.dti.back_end_max",
    status: "pass",
  },
  findings: { unresolved: false, open_in_scope_count: 0 },
};

function mockDti(overrides: Partial<ReturnType<typeof useDtiMock>> = {}) {
  useDtiMock.mockReturnValue({
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

describe("DtiCalculator", () => {
  it("renders the two ratios, the breakdown, the formula and the limit", () => {
    mockDti();
    render(<DtiCalculator fileId="LF-1" />);

    // Ratios (the back-end appears in the hero tile and the formula receipt).
    expect(screen.getAllByText("22.78%").length).toBeGreaterThan(0);
    expect(screen.getByText("2.78%")).toBeDefined();
    // Limit side-by-side + pass status.
    expect(screen.getByText("Within limit")).toBeDefined();
    expect(screen.getByText(/50.00% limit/)).toBeDefined();
    // Itemized breakdown.
    expect(screen.getByText("Base — Pat")).toBeDefined();
    expect(screen.getByText("Principal & interest")).toBeDefined();
    expect(screen.getByText("Installment")).toBeDefined();
    // The explicit formula is shown.
    expect(
      screen.getByText("Back-end DTI = (housing payment + monthly debts) ÷ gross monthly income"),
    ).toBeDefined();
  });

  it("shows the unresolved-findings alert when findings are open", () => {
    mockDti({
      data: { ...CALC, findings: { unresolved: true, open_in_scope_count: 2 } },
    });
    render(<DtiCalculator fileId="LF-1" />);

    expect(screen.getByRole("alert")).toBeDefined();
    expect(screen.getByText(/2 unresolved findings/)).toBeDefined();
  });

  it("flags over-limit in red", () => {
    mockDti({
      data: {
        ...CALC,
        back_end_dti: "60.00",
        limit: { ...CALC.limit, status: "over" },
      },
    });
    render(<DtiCalculator fileId="LF-1" />);
    expect(screen.getByText("Over limit")).toBeDefined();
  });

  it("opens an inline editor and saves an override (real-time recalc trigger)", () => {
    mockDti();
    render(<DtiCalculator fileId="LF-1" />);

    // The debt line value is a button that opens the editor.
    fireEvent.click(screen.getByRole("button", { name: /\$2,000\.00/ }));
    const input = screen.getByLabelText("Override Installment");
    fireEvent.change(input, { target: { value: "0" } });
    fireEvent.click(screen.getByLabelText("Save override"));

    expect(setMutate).toHaveBeenCalledWith({ fieldKey: "debt.1", input: { amount: "0" } });
  });

  it("renders the loading skeleton while pending", () => {
    mockDti({ data: undefined, isPending: true });
    render(<DtiCalculator fileId="LF-1" />);
    expect(screen.getByText("Calculating debt-to-income")).toBeDefined();
  });

  it("renders an error with retry", () => {
    const refetch = vi.fn();
    mockDti({ data: undefined, isError: true, refetch });
    render(<DtiCalculator fileId="LF-1" />);
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalled();
  });
});
