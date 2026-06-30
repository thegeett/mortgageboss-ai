// @vitest-environment jsdom
import type { ValidationInventory } from "@/lib/types/validation-aid";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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
    // HONEST: nothing validated by default.
    expect(screen.getAllByText("grounded starter").length).toBeGreaterThanOrEqual(2);
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
});
