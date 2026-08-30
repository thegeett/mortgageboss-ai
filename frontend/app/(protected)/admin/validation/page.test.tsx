// @vitest-environment jsdom
import type { ValidationInventory } from "@/lib/types/validation-aid";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const recordMutate = vi.fn();
const useInventoryMock = vi.fn();

vi.mock("@/lib/api/validation-aid", () => ({
  useValidationInventory: () => useInventoryMock(),
  useRecordVerdict: () => ({ mutate: recordMutate, isPending: false }),
}));
vi.mock("@/lib/stores/auth-store", () => ({
  useAuthStore: (sel: (s: { user: { role: string } }) => unknown) =>
    sel({ user: { role: "admin" } }),
}));

import ValidationAidPage from "./page";

const INVENTORY: ValidationInventory = {
  total: 2,
  grounded_starter: 2,
  validated: 0,
  corrected: 0,
  flagged_remove: 0,
  additions: [],
  items: [
    {
      item_id: "conv.dti.back_end_max_manual",
      item_kind: "rule",
      program: "conventional",
      category: "income",
      description: "Manual DTI ceiling",
      value: "45",
      op: "<=",
      unit: "percent",
      citation: "Fannie B3-6-02",
      source_type: "fannie_selling_guide",
      to_verify: false,
      starter: true,
      validation_status: "grounded_starter",
      verdict: null,
    },
    {
      item_id: "calc.pmi_rate",
      item_kind: "calculator",
      program: null,
      category: "calculator",
      description: "PMI annual rate",
      value: "55",
      op: null,
      unit: "bps",
      citation: "rate card",
      source_type: "methodology",
      to_verify: true,
      starter: true,
      validation_status: "grounded_starter",
      verdict: null,
    },
  ],
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ValidationAidPage", () => {
  it("lists every grounded-starter item with its citation + value, defaulting grounded", () => {
    useInventoryMock.mockReturnValue({ data: INVENTORY, isPending: false, isError: false });
    render(<ValidationAidPage />);
    expect(screen.getByText("conv.dti.back_end_max_manual")).toBeDefined();
    expect(screen.getByText(/Fannie B3-6-02/)).toBeDefined();
    expect(screen.getByText("calc.pmi_rate")).toBeDefined();
    // HONEST: nothing validated by default. The label is VALIDATION_STATUS's
    // now (LP-UI-028) rather than the raw enum with its underscore replaced —
    // the status joined the one vocabulary, so the words are the vocabulary's.
    // Scoped to the list, because the counts strip carries the same label once.
    const rows = screen.getByRole("list");
    expect(within(rows).getAllByText("Grounded starter").length).toBeGreaterThanOrEqual(2);
  });

  it("records a 'validated' verdict (captures Priya's judgment)", () => {
    useInventoryMock.mockReturnValue({ data: INVENTORY, isPending: false, isError: false });
    render(<ValidationAidPage />);
    fireEvent.click(screen.getAllByRole("button", { name: "Validate" })[0] as HTMLElement);
    expect(recordMutate).toHaveBeenCalledWith(
      expect.objectContaining({ item_id: "conv.dti.back_end_max_manual", kind: "validated" }),
      expect.anything(),
    );
  });

  it("records a 'corrected' verdict with the new value", () => {
    useInventoryMock.mockReturnValue({ data: INVENTORY, isPending: false, isError: false });
    render(<ValidationAidPage />);
    fireEvent.click(screen.getAllByRole("button", { name: /correct…/i })[0] as HTMLElement);
    fireEvent.change(screen.getByLabelText("Corrected value"), { target: { value: "43" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(recordMutate).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "corrected", corrected_value: "43" }),
      expect.anything(),
    );
  });

  it("captures an add-new proposal (a rule Priya says is missing)", () => {
    useInventoryMock.mockReturnValue({ data: INVENTORY, isPending: false, isError: false });
    render(<ValidationAidPage />);
    fireEvent.click(screen.getByRole("button", { name: /add a rule priya says is missing/i }));
    fireEvent.change(screen.getByLabelText("New rule title"), {
      target: { value: "Gift of equity letter" },
    });
    fireEvent.click(screen.getByRole("button", { name: /capture proposal/i }));
    expect(recordMutate).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "add_new", title: "Gift of equity letter" }),
      expect.anything(),
    );
  });

  it("keeps the reviewer's own words on a FLAGGED rule (LP-UI-028)", () => {
    // The note rendered only when there was a corrected_value, so a rule flagged
    // for removal showed the flag and lost the reason. The reason a rule is
    // wrong is worth more than the flag.
    useInventoryMock.mockReturnValue({
      data: {
        ...INVENTORY,
        items: [
          {
            ...INVENTORY.items[0],
            validation_status: "flagged_remove",
            verdict: {
              kind: "flagged_remove",
              corrected_value: null,
              note: "Fannie retired this in the 2026 selling guide.",
              at: "2026-08-30T00:00:00Z",
              actor: "Priya",
            },
          },
        ],
      },
      isPending: false,
      isError: false,
    });
    render(<ValidationAidPage />);
    expect(screen.getByText(/Fannie retired this in the 2026 selling guide/)).toBeDefined();
  });

  it("keeps the words on a correction too, beside the new value", () => {
    useInventoryMock.mockReturnValue({
      data: {
        ...INVENTORY,
        items: [
          {
            ...INVENTORY.items[0],
            validation_status: "corrected",
            verdict: {
              kind: "corrected",
              corrected_value: "45",
              note: "Investor caps at 45, not 50.",
              at: "2026-08-30T00:00:00Z",
              actor: "Priya",
            },
          },
        ],
      },
      isPending: false,
      isError: false,
    });
    render(<ValidationAidPage />);
    expect(screen.getByText(/Corrected to 45/)).toBeDefined();
    expect(screen.getByText(/Investor caps at 45, not 50/)).toBeDefined();
  });

  it("distinguishes grounded-starter from validated by more than colour", () => {
    // SPEC rule: colour AND glyph AND word. Grey-versus-green is one channel,
    // and this screen exists so a researched-but-unconfirmed rule never reads as
    // "fine, nothing to do here".
    useInventoryMock.mockReturnValue({
      data: {
        ...INVENTORY,
        items: [
          { ...INVENTORY.items[0], item_id: "a", validation_status: "grounded_starter" },
          { ...INVENTORY.items[0], item_id: "b", validation_status: "validated" },
        ],
      },
      isPending: false,
      isError: false,
    });
    render(<ValidationAidPage />);
    const rows = screen.getByRole("list");
    const starter = within(rows).getByText("Grounded starter");
    const validated = within(rows).getByText("Validated");
    // Different words AND a different tone — the tone drives both the colour and
    // the glyph, so this pins two of the three channels. A grounded starter
    // rendered in the verified tone would read as "confirmed", which is the one
    // thing this screen exists to prevent.
    expect(starter.className).not.toBe(validated.className);
  });
});

describe("the status filter offers every status", () => {
  // VALIDATION_STATUS is exhaustive over `ValidationStatus`, so a fifth status
  // is a compile error there. A hardcoded list of options beside it would stay
  // green while silently offering no way to filter for the new one — one
  // concept, two enumerations, which is the shape this epic keeps finding.
  it("derives its options from the vocabulary", async () => {
    const { VALIDATION_STATUS } = await import("@/lib/status");
    useInventoryMock.mockReturnValue({ data: INVENTORY, isPending: false, isError: false });
    render(<ValidationAidPage />);

    const select = screen.getByLabelText(/status/i) as HTMLSelectElement;
    const options = [...select.options].map((o) => o.value);
    for (const status of Object.keys(VALIDATION_STATUS)) {
      expect(options, `${status} cannot be filtered for`).toContain(status);
    }
    expect(options).toContain("all");
  });
});
