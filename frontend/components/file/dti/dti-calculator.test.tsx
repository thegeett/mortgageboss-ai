import type { DtiCalculation } from "@/lib/types/dti";
// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const setMutate = vi.fn();
const clearMutate = vi.fn();
const useDtiMock = vi.fn();

const addMutate = vi.fn();
const removeMutate = vi.fn();
const ungateMutate = vi.fn();
const useUngatePreviewMock = vi.fn(() => ({ data: undefined, isPending: false }));

vi.mock("@/lib/api/dti", () => ({
  useDti: () => useDtiMock(),
  useSetDtiOverride: () => ({ mutate: setMutate, isPending: false }),
  useClearDtiOverride: () => ({ mutate: clearMutate, isPending: false }),
  // LP-643 — the module is mocked WHOLE, so every hook the component reaches for has to be here or
  // it throws at import. Stubbed rather than exercised: these are covered by their own tests below.
  useAddDtiLine: () => ({ mutate: addMutate, isPending: false }),
  useRemoveDtiLine: () => ({ mutate: removeMutate, isPending: false }),
  useDtiUngatePreview: () => useUngatePreviewMock(),
  useApplyDtiUngate: () => ({ mutate: ungateMutate, isPending: false }),
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
          ? { ...i, overridden: true, unknown: false, override_amount: "464.92" }
          : i,
      ),
    };
    mockDti({ data: { ...overridden, unverified_inputs: [suggestion] } });
    render(<DtiCalculator fileId="LF-ABRS" />);

    expect(screen.queryByRole("button", { name: /figure \(\$/ })).toBeNull();
  });
});

describe("LP-643 review — the remove control", () => {
  afterEach(cleanup);

  /** The trash icon used to render on `item.key.startsWith("custom.")`, with the server's prefix
   *  retyped in this component. It now renders on `item.removable`, which the server decides — and
   *  NOTHING covered either version, so this is the first test that touches the control at all. */
  it("offers removal on a processor-added line and not on an engine line", () => {
    useDtiMock.mockReturnValue({
      data: {
        ...CALC,
        debt_items: [
          {
            key: "debt.1",
            label: "Installment",
            auto_amount: "2000.00",
            override_amount: null,
            amount: "2000.00",
            source: "stated",
            overridden: false,
            removable: false,
          },
          {
            key: "custom.6f1c9b3e-0000-4000-8000-000000000001",
            label: "Child support",
            auto_amount: "450.00",
            override_amount: null,
            amount: "450.00",
            source: "manual",
            overridden: false,
            removable: true,
          },
        ],
      },
      isPending: false,
      isError: false,
    });
    render(<DtiCalculator fileId="f1" />);

    expect(screen.getByLabelText("Remove Child support")).toBeTruthy();
    expect(screen.queryByLabelText("Remove Installment")).toBeNull();
  });

  /** And it must send the ID, not the namespaced key — the endpoint takes a UUID. */
  it("removes by id rather than by the namespaced key", () => {
    const id = "6f1c9b3e-0000-4000-8000-000000000001";
    useDtiMock.mockReturnValue({
      data: {
        ...CALC,
        debt_items: [
          {
            key: `custom.${id}`,
            label: "Child support",
            auto_amount: "450.00",
            override_amount: null,
            amount: "450.00",
            source: "manual",
            overridden: false,
            removable: true,
          },
        ],
      },
      isPending: false,
      isError: false,
    });
    render(<DtiCalculator fileId="f1" />);
    fireEvent.click(screen.getByLabelText("Remove Child support"));

    expect(removeMutate).toHaveBeenCalledWith(id);
  });

  /** LP-643 (c) — THE WHOLE-MODULE MOCK IS THIS REPO'S PATTERN (22 files use it), so the fix is not
   *  to fork the style. The hazard is real though: the module is replaced wholly, so a hook added to
   *  it throws at IMPORT here, and nothing fails until someone happens to touch this component.
   *  This turns that into an explicit failure naming the missing hook. */
  it("stubs every hook the api module exports", async () => {
    const real = await vi.importActual<Record<string, unknown>>("@/lib/api/dti");
    const stubbed = await import("@/lib/api/dti");
    // HOOKS ONLY, and the narrowing is the point. A first version asserted over EVERY export and
    // failed on `fetchDti`, `dtiQueryKey` and the raw mutators — none of which a component calls, so
    // none of which can throw here. A guard that refuses more than its reason justifies gets deleted
    // by the next person who hits it. The reason is that a HOOK missing from the mock throws when
    // the component renders; that is the class, and it is exactly the `use` prefix.
    const missing = Object.keys(real).filter(
      (name) => name.startsWith("use") && !(name in stubbed),
    );

    expect(missing).toEqual([]);
  });
});
