// @vitest-environment jsdom
import type { PropertyPublic } from "@/lib/types/loan-file";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const updateMutate = vi.fn();
vi.mock("@/lib/api/overview-edit", () => ({
  useUpdateProperty: () => ({ mutate: updateMutate, isPending: false }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { PropertyEditor } from "./property-editor";

const PROPERTY = {
  id: "p1",
  address_line: "123 Main",
  city: "Austin",
  state: "TX",
  postal_code: "78701",
  property_type: "single_family",
  occupancy_type: "primary_residence",
  estimated_value: "400000",
  purchase_price: "410000",
  valuation_amount: "1380000",
} as unknown as PropertyPublic;

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("PropertyEditor", () => {
  it("renders the property fields with current values", () => {
    render(<PropertyEditor fileId="LF-1" property={PROPERTY} />);
    expect((screen.getByLabelText("Address") as HTMLInputElement).value).toBe("123 Main");
    expect((screen.getByLabelText("Est. value") as HTMLInputElement).value).toBe("400000");
  });

  it("saves only the changed field", () => {
    render(<PropertyEditor fileId="LF-1" property={PROPERTY} />);
    fireEvent.change(screen.getByLabelText("Est. value"), { target: { value: "450000" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    expect(updateMutate).toHaveBeenCalledTimes(1);
    expect(updateMutate.mock.calls[0]?.[0]).toEqual({ estimated_value: "450000" });
  });

  it("exposes valuation_amount as an editable field (the field the LTV reads — LP-90)", () => {
    render(<PropertyEditor fileId="LF-1" property={PROPERTY} />);
    // The previously-hidden valuation amount is now displayed + editable.
    const valuation = screen.getByLabelText("Valuation amount") as HTMLInputElement;
    expect(valuation.value).toBe("1380000");
    // Editing it sends only valuation_amount (the property PATCH invalidates dti/ltv/verification
    // → the LTV's appraised basis flows through). No more hidden shadowing field.
    fireEvent.change(valuation, { target: { value: "1480000" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    expect(updateMutate.mock.calls[0]?.[0]).toEqual({ valuation_amount: "1480000" });
  });
});
