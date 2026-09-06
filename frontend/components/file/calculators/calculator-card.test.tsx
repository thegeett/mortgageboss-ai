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

describe("LP-647 §3 — an abandoned edit is not discarded silently", () => {
  afterEach(cleanup);

  const TWO_INPUTS: CalculatorView = {
    ...VIEW,
    inputs: [
      ...VIEW.inputs,
      {
        key: "mi.ltv",
        label: "LTV",
        auto_amount: "96.50",
        override_amount: null,
        amount: "96.50",
        source: "computed",
        overridden: false,
      },
    ],
  };

  /** THE SAME DEFECT AS THE DTI PANEL'S, in the same shape, which is why it is fixed in both. A
   *  single `editingKey` at the parent plus a draft local to the row meant opening a second input
   *  discarded the first, silently. Fixing one component and leaving its twin is the failure this
   *  repo keeps repeating. */
  it("keeps a draft when the processor opens another input", () => {
    useCalcMock.mockReturnValue({ data: TWO_INPUTS, isPending: false, isError: false });
    render(<CalculatorCard fileId="LF-1" calculator="mortgage_insurance" />);

    // The read-only trigger is the amount itself, not a labelled control.
    fireEvent.click(screen.getByText("$300,000.00"));
    fireEvent.change(screen.getByLabelText("Override Base loan amount"), {
      target: { value: "312500" },
    });
    fireEvent.click(screen.getByText("$96.50"));

    expect(screen.getByText(/unsaved — press Enter or ✓ to apply \$312500/)).toBeTruthy();
  });

  /** The reset-on-re-entry, pinned. Removing `setDraft(item.amount)` from the trigger was part of
   *  this fix and NOTHING covered it — a mutation re-introducing it passed clean until this existed.
   *  Without it a paused edit survives the switch and is then overwritten the moment the processor
   *  returns to correct it, which is the same loss one step later. */
  it("restores the paused draft when the processor comes back to the input", () => {
    useCalcMock.mockReturnValue({ data: TWO_INPUTS, isPending: false, isError: false });
    render(<CalculatorCard fileId="LF-1" calculator="mortgage_insurance" />);

    fireEvent.click(screen.getByText("$300,000.00"));
    fireEvent.change(screen.getByLabelText("Override Base loan amount"), {
      target: { value: "312500" },
    });
    fireEvent.click(screen.getByText("$96.50"));
    // Back to the first input — its trigger now shows the SAVED amount, not the draft.
    fireEvent.click(screen.getByText("$300,000.00"));

    expect((screen.getByLabelText("Override Base loan amount") as HTMLInputElement).value).toBe(
      "312500",
    );
  });

  /** The same chain-order guard as its two siblings — see the DTI panel's for the reasoning. */
  it("reports an overridden input as unsaved while it holds a pending edit", () => {
    useCalcMock.mockReturnValue({
      data: {
        ...TWO_INPUTS,
        inputs: [
          {
            ...TWO_INPUTS.inputs[0],
            override_amount: "300000.00",
            auto_amount: "290000.00",
            overridden: true,
          },
          TWO_INPUTS.inputs[1],
        ],
      },
      isPending: false,
      isError: false,
    });
    render(<CalculatorCard fileId="LF-1" calculator="mortgage_insurance" />);

    fireEvent.click(screen.getByText("$300,000.00"));
    fireEvent.change(screen.getByLabelText("Override Base loan amount"), {
      target: { value: "312500" },
    });
    fireEvent.click(screen.getByText("$96.50"));

    expect(screen.getByText(/unsaved — press Enter or ✓ to apply \$312500/)).toBeTruthy();
    expect(screen.queryByText(/overridden · auto/)).toBeNull();
  });

  it("does not claim an unsaved edit on an untouched input", () => {
    useCalcMock.mockReturnValue({ data: TWO_INPUTS, isPending: false, isError: false });
    render(<CalculatorCard fileId="LF-1" calculator="mortgage_insurance" />);

    expect(screen.queryByText(/unsaved/)).toBeNull();
  });
});
