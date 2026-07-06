// @vitest-environment jsdom
import type { DtiCalculation } from "@/lib/types/dti";
import type { FindingImpactPreview, VerificationFinding } from "@/lib/types/verification";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const useApplyPreviewMock = vi.fn();
vi.mock("@/lib/api/verification", () => ({
  useApplyPreview: () => useApplyPreviewMock(),
}));

import { ViewFixDialog } from "./view-fix-dialog";

const FINDING = {
  id: "f-1",
  rule_id: "xsrc.liability.undisclosed_debt",
  resolution_status: "open",
} as unknown as VerificationFinding;

function dti(over: Partial<DtiCalculation>): DtiCalculation {
  return {
    front_end_dti: "8.33",
    back_end_dti: "28.33",
    gross_monthly_income: "10000",
    housing_payment: "833.33",
    monthly_debts: "2000",
    total_monthly_obligations: "2833.33",
    income_items: [],
    housing_items: [],
    debt_items: [
      {
        key: "debt.a",
        label: "Card",
        auto_amount: "2000",
        override_amount: null,
        amount: "2000",
        source: "stated",
        overridden: false,
      },
    ],
    front_end_formula: "",
    back_end_formula: "",
    program: "conventional",
    limit: {
      back_end_max: "45",
      source: "program_default",
      lender_slug: null,
      rule_id: "x",
      status: "pass",
    },
    findings: { unresolved: false, open_in_scope_count: 0 },
    ...over,
  } as DtiCalculation;
}

function preview(over: Partial<FindingImpactPreview> = {}): FindingImpactPreview {
  return {
    finding_id: "f-1",
    summary: "Add to monthly debts: Auto loan — $6000/mo",
    applied_record: { action: "add_liability" },
    affects: ["dti"],
    dti_before: dti({}),
    dti_after: dti({
      back_end_dti: "88.33",
      monthly_debts: "8000",
      total_monthly_obligations: "8833.33",
      debt_items: [
        {
          key: "debt.a",
          label: "Card",
          auto_amount: "2000",
          override_amount: null,
          amount: "2000",
          source: "stated",
          overridden: false,
        },
        {
          key: "debt.new",
          label: "Auto loan",
          auto_amount: "6000",
          override_amount: null,
          amount: "6000",
          source: "stated",
          overridden: false,
        },
      ],
      limit: {
        back_end_max: "45",
        source: "program_default",
        lender_slug: null,
        rule_id: "x",
        status: "over",
      },
    }),
    ltv_before: null,
    ltv_after: null,
    ...over,
  };
}

function mock(data: FindingImpactPreview | undefined, extra: Record<string, unknown> = {}) {
  useApplyPreviewMock.mockReturnValue({
    data,
    isPending: false,
    isError: false,
    refetch: vi.fn(),
    ...extra,
  });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ViewFixDialog", () => {
  it("renders the DETAILED itemized before/after — the change, the new line, totals, DTI, status", () => {
    mock(preview());
    render(
      <ViewFixDialog
        open
        onOpenChange={vi.fn()}
        fileId="LF-1"
        finding={FINDING}
        onApply={vi.fn()}
      />,
    );
    // The change summary.
    expect(screen.getByText(/Add to monthly debts: Auto loan/)).toBeDefined();
    // The new debt line is highlighted + itemized.
    expect(screen.getByText("Auto loan")).toBeDefined();
    expect(screen.getByText("NEW")).toBeDefined();
    // The recomputed back-end DTI (before → after) and the limit status crossing.
    expect(screen.getByText("28.33%")).toBeDefined();
    expect(screen.getByText("88.33%")).toBeDefined();
    expect(screen.getByText("Within limit")).toBeDefined();
    expect(screen.getByText("Over limit")).toBeDefined();
  });

  it("Apply fix confirms (calls onApply) and closes", () => {
    const onApply = vi.fn();
    const onOpenChange = vi.fn();
    mock(preview());
    render(
      <ViewFixDialog
        open
        onOpenChange={onOpenChange}
        fileId="LF-1"
        finding={FINDING}
        onApply={onApply}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Apply fix/ }));
    expect(onApply).toHaveBeenCalledTimes(1);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("Cancel is a no-op (no apply)", () => {
    const onApply = vi.fn();
    const onOpenChange = vi.fn();
    mock(preview());
    render(
      <ViewFixDialog
        open
        onOpenChange={onOpenChange}
        fileId="LF-1"
        finding={FINDING}
        onApply={onApply}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onApply).not.toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("shows an error state (with retry) when the preview fails to load", () => {
    mock(undefined, { isError: true });
    render(
      <ViewFixDialog
        open
        onOpenChange={vi.fn()}
        fileId="LF-1"
        finding={FINDING}
        onApply={vi.fn()}
      />,
    );
    expect(screen.getByText(/Couldn't compute the impact preview/)).toBeDefined();
  });
});
