import type { CalculatorView } from "@/lib/types/calculators";
// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const setMutate = vi.fn();
const clearMutate = vi.fn();
const useCalcMock = vi.fn();

vi.mock("@/lib/api/calculators", () => ({
  useCalculator: () => useCalcMock(),
  useSetCalculatorOverride: () => ({ mutate: setMutate, isPending: false }),
  useClearCalculatorOverride: () => ({ mutate: clearMutate, isPending: false }),
}));

import { CalculatorCard } from "./calculator-card";

const VIEW: CalculatorView = {
  calculator: "mortgage_insurance",
  title: "Mortgage insurance",
  headline: "$137.50 / mo",
  headline_label: "Monthly premium",
  status: "required",
  program: "fha",
  inputs: [
    {
      key: "mi.base_loan_amount",
      label: "Base loan amount",
      auto_amount: "300000.00",
      override_amount: null,
      amount: "300000.00",
      source: "stated",
      overridden: false,
    },
  ],
  steps: [
    { label: "Upfront MIP (175 bps, financed)", value: "$5,250.00", emphasis: false },
    { label: "Monthly MIP", value: "$137.50", emphasis: true },
    { label: "MIP duration", value: "life of loan", emphasis: false },
  ],
  formulas: ["Upfront MIP = base loan amount x UFMIP rate (financed into the loan)"],
  methodology: { starter: true, text: "UFMIP is consumed from LP-84's rule." },
  findings: { unresolved: false, open_in_scope_count: 0 },
};

function mockCalc(overrides: Partial<ReturnType<typeof useCalcMock>> = {}) {
  useCalcMock.mockReturnValue({
    data: VIEW,
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

describe("CalculatorCard", () => {
  it("renders the headline, the transparent steps, the formula and the starter note", () => {
    mockCalc();
    render(<CalculatorCard fileId="LF-1" calculator="mortgage_insurance" />);

    expect(screen.getByText("Mortgage insurance")).toBeDefined();
    expect(screen.getByText("$137.50 / mo")).toBeDefined();
    // The transparent derivation steps (the math, shown).
    expect(screen.getByText("Upfront MIP (175 bps, financed)")).toBeDefined();
    expect(screen.getByText("MIP duration")).toBeDefined();
    expect(screen.getByText("life of loan")).toBeDefined();
    // The formula + the grounded-starter methodology marker.
    expect(screen.getByText(/Upfront MIP = base loan amount/)).toBeDefined();
    expect(screen.getByText(/Methodology — starter/)).toBeDefined();
  });

  it("opens an inline editor and saves an override (real-time recalc trigger)", () => {
    mockCalc();
    render(<CalculatorCard fileId="LF-1" calculator="mortgage_insurance" />);

    fireEvent.click(screen.getByRole("button", { name: /\$300,000\.00/ }));
    const input = screen.getByLabelText("Override Base loan amount");
    fireEvent.change(input, { target: { value: "400000" } });
    fireEvent.click(screen.getByLabelText("Save override"));

    expect(setMutate).toHaveBeenCalledWith(
      { fieldKey: "mi.base_loan_amount", input: { amount: "400000" } },
      expect.anything(),
    );
  });

  it("shows the unresolved-findings alert", () => {
    mockCalc({ data: { ...VIEW, findings: { unresolved: true, open_in_scope_count: 1 } } });
    render(<CalculatorCard fileId="LF-1" calculator="mortgage_insurance" />);
    expect(screen.getByRole("alert")).toBeDefined();
    expect(screen.getByText(/1 unresolved finding/)).toBeDefined();
  });

  it("renders an error with retry", () => {
    const refetch = vi.fn();
    mockCalc({ data: undefined, isError: true, refetch });
    render(<CalculatorCard fileId="LF-1" calculator="mortgage_insurance" />);
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalled();
  });
});
