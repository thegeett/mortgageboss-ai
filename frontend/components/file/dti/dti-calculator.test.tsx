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
      override_by: null,
      override_note: null,
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
      override_by: null,
      override_note: null,
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
      override_by: null,
      override_note: null,
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
  findings: {
    unresolved: false,
    open_in_scope_count: 0,
    breakdown: { governed: 0, cross_source: 0, legacy: 0, other: 0 },
  },
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
  // LP-568 — a debt that does not survive closing (the mortgage a refinance pays off, a departing
  // residence, a debt cleared to qualify) is left OUT of the totals. It must still be rendered: a
  // liability that silently disappears from the breakdown is worse than one counted wrongly,
  // because the processor cannot tell it was considered at all.
  it("shows an excluded debt struck through, with its reason, and out of the total", () => {
    mockDti({
      data: {
        ...CALC,
        monthly_debts: "0.00",
        total_monthly_obligations: "277.78",
        debt_items: [
          {
            key: "debt.1",
            label: "MortgageLoan — UNITED WHSLE MORT",
            auto_amount: "3186.00",
            override_amount: null,
            amount: "3186.00",
            source: "stated",
            overridden: false,
            override_by: null,
            override_note: null,
            excluded: true,
            excluded_reason: "paid off at closing",
          },
        ],
      },
    });
    render(<DtiCalculator fileId="LF-1" />);

    // The row is present, and says WHY it does not count.
    expect(screen.getByText(/not counted/)).toBeDefined();
    expect(screen.getByText(/paid off at closing/)).toBeDefined();
    // Its own figure is still shown — struck through, not hidden and not zeroed.
    const amount = screen.getByText("$3,186.00");
    expect(amount.className).toContain("line-through");
  });

  it("puts the result BESIDE the math, not after it (LP-UI-045)", () => {
    // It ran down the page: ratios, three sections, then the formula — so the
    // answer was above the working and the arithmetic that produces it a screen
    // below. Reading it meant scrolling between the number and the numbers it
    // came from.
    mockDti();
    const { container } = render(<DtiCalculator fileId="LF-1" />);
    const split = container.querySelector("div.grid.gap-4");
    expect(split?.className).toContain("lg:grid-cols-[minmax(0,1fr)_19rem]");
    // And it stays put while the math scrolls, which is the point of the split.
    expect(container.querySelector(".lg\\:sticky")).toBeTruthy();
  });

  it("keeps a single column below lg, where two would be too narrow", () => {
    // A line is a label, a figure and its source; at half a laptop's width that
    // wraps three times.
    mockDti();
    const { container } = render(<DtiCalculator fileId="LF-1" />);
    const split = container.querySelector("div.grid.gap-4");
    expect(split?.className).not.toMatch(/(?<!lg:)grid-cols-2/);
  });

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
      data: {
        ...CALC,
        findings: {
          unresolved: true,
          open_in_scope_count: 2,
          breakdown: { governed: 2, cross_source: 0, legacy: 0, other: 0 },
        },
      },
    });
    render(<DtiCalculator fileId="LF-1" />);

    expect(screen.getByRole("alert")).toBeDefined();
    // LP-UI-021: named by system rather than one merged total.
    expect(screen.getByText(/2 rule findings unresolved/)).toBeDefined();
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

// --------------------------------------------------------------------------- //
// bug-001 — one click to accept a figure the file states for a gated input.
//
// A real file gated on "Property taxes is unknown" while two of its documents stated the annual tax
// outright ($5,579). Gating is right — an estimator's figure must not silently set a DTI — but the
// processor had no way to act on it except retyping a number the system already had.
// --------------------------------------------------------------------------- //
describe("bug-001 — using a stated estimate", () => {
  const suggestion = {
    field_key: "housing.taxes",
    label: "Property taxes",
    monthly_amount: "464.92",
    annual_amount: "5579.00",
    source_label: "the home value estimate",
    sentence:
      "The home value estimate states annual property taxes of $5,579.00. That is an automated valuation's estimate, not verification — upload the property tax bill.",
  };
  // The taxes line must be PRESENT and unknown — the offer renders on the line, keyed to it.
  const gated = {
    ...CALC,
    gated: true,
    gate_reason: "calculation gated (fail-closed): Property taxes is unknown",
    housing_items: [
      ...CALC.housing_items,
      {
        key: "housing.taxes",
        label: "Property taxes",
        auto_amount: "0.00",
        override_amount: null,
        amount: "0.00",
        source: "extracted",
        overridden: false,
        override_by: null,
        override_note: null,
        unknown: true,
      },
    ],
  };

  it("offers the figure ON THE LINE that reads unknown, not only in the banner", () => {
    mockDti({ data: { ...gated, unverified_inputs: [suggestion] } });
    render(<DtiCalculator fileId="LF-ABRS" />);

    expect(
      screen.getByRole("button", {
        name: /Use the home value estimate's figure \(\$464\.92\/mo\)/,
      }),
    ).toBeDefined();
  });

  it("writes it as an override carrying a note that names the source", () => {
    mockDti({ data: { ...gated, unverified_inputs: [suggestion] } });
    render(<DtiCalculator fileId="LF-ABRS" />);

    fireEvent.click(screen.getByRole("button", { name: /Use the home value estimate/ }));

    expect(setMutate).toHaveBeenCalledTimes(1);
    const call = setMutate.mock.calls[0]?.[0];
    expect(call.fieldKey).toBe("housing.taxes");
    // The MONTHLY figure the calculator uses...
    expect(call.input.amount).toBe("464.92");
    // ...and a note recording that an ESTIMATE was accepted, not a verified bill.
    expect(call.input.note).toContain("home value estimate");
    expect(call.input.note).toContain("not a verified tax bill");
  });

  it("offers BOTH sources for one line, not whichever the backend listed first", () => {
    // LP-627 — the two disagreed on LF-ABRS ($6,500 stated against $5,579 estimated) and the backend
    // emits both deliberately. `.find` rendered one: the AVM offer that had been there all along
    // vanished the moment MISMO stated a figure, and the survivor read "Use the estimate" over the
    // borrower's own self-report.
    const stated = {
      field_key: "housing.taxes",
      label: "Property taxes",
      monthly_amount: "541.67",
      annual_amount: "6500.04",
      source_label: "the application",
      sentence: "The application states proposed property taxes of $541.67 a month.",
    };
    mockDti({ data: { ...gated, unverified_inputs: [stated, suggestion] } });
    render(<DtiCalculator fileId="LF-ABRS" />);

    expect(
      screen.getByRole("button", { name: /Use the application's figure \(\$541\.67\/mo\)/ }),
    ).toBeDefined();
    expect(
      screen.getByRole("button", {
        name: /Use the home value estimate's figure \(\$464\.92\/mo\)/,
      }),
    ).toBeDefined();
  });

  it("offers nothing when the file states no such figure", () => {
    mockDti({ data: gated });
    render(<DtiCalculator fileId="LF-ABRS" />);

    expect(screen.getByRole("alert")).toBeDefined(); // the gate banner renders...
    expect(screen.queryByRole("button", { name: /figure \(\$/ })).toBeNull(); // ...with no offer
  });

  it("offers nothing once the line has already been overridden", () => {
    // The figure has been accepted; repeating the offer would invite overriding an override.
    const overridden = {
      ...gated,
      housing_items: gated.housing_items.map((i) =>
        i.key === "housing.taxes"
          ? {
              ...i,
              overridden: true,
              override_by: null,
              override_note: null,
              unknown: false,
              override_amount: "464.92",
            }
          : i,
      ),
    };
    mockDti({ data: { ...overridden, unverified_inputs: [suggestion] } });
    render(<DtiCalculator fileId="LF-ABRS" />);

    expect(screen.queryByRole("button", { name: /figure \(\$/ })).toBeNull();
  });

  it("names who set an override, not just that one exists (LP-UI-021)", () => {
    // The actor was already recorded on DtiOverride and dropped on the way out
    // of the service. On a compliance file "someone changed this number" and
    // "Priya changed this number" are different statements.
    mockDti({
      data: {
        ...CALC,
        income_items: [
          {
            key: "income.bonus",
            label: "Bonus — Pat",
            auto_amount: "583.33",
            override_amount: "0.00",
            amount: "0.00",
            source: "override",
            overridden: true,
            override_by: "Priya Desai",
            override_note: null,
          },
        ],
      },
    });
    render(<DtiCalculator fileId="LF-1" />);
    expect(screen.getByText(/overridden by Priya Desai/)).toBeDefined();
  });

  it("stays silent about an actor it does not have", () => {
    // An override written before the column existed, or by a process rather than
    // a person. A placeholder name in an audit trail reads as one nobody checked,
    // so the line says "overridden" and stops there.
    mockDti({
      data: {
        ...CALC,
        income_items: [
          {
            key: "income.bonus",
            label: "Bonus — Pat",
            auto_amount: "583.33",
            override_amount: "0.00",
            amount: "0.00",
            source: "override",
            overridden: true,
            override_by: null,
            override_note: null,
          },
        ],
      },
    });
    render(<DtiCalculator fileId="LF-1" />);
    expect(screen.getByText(/overridden · auto/)).toBeDefined();
    expect(screen.queryByText(/overridden by/)).toBeNull();
  });
});
