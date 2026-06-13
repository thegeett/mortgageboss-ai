import { PRIORITY_META, categoryLabel, outstandingNeedsCount } from "@/lib/loan-files/needs";
import type { NeedsItemPublic, NeedsItemStatus } from "@/lib/types/needs-item";
import { describe, expect, it } from "vitest";

function need(status: NeedsItemStatus): NeedsItemPublic {
  return {
    id: status,
    title: "Pay stubs",
    category: "income_employment",
    needs_type: "paystub",
    status,
    priority: "standard",
    origin: "template",
    borrower_id: null,
    satisfied_by_document_id: null,
    created_at: "2026-06-11T12:00:00Z",
  };
}

describe("outstandingNeedsCount", () => {
  it("counts items that are not yet received or waived", () => {
    const needs = [need("outstanding"), need("requested"), need("received"), need("waived")];
    expect(outstandingNeedsCount(needs)).toBe(2);
  });

  it("is 0 for an empty list", () => {
    expect(outstandingNeedsCount([])).toBe(0);
  });
});

describe("categoryLabel", () => {
  it("maps a known category to a human label", () => {
    expect(categoryLabel("income_employment")).toBe("Income & employment");
  });

  it("maps null to 'Uncategorized'", () => {
    expect(categoryLabel(null)).toBe("Uncategorized");
  });
});

describe("PRIORITY_META", () => {
  it("has a label + classes for each priority", () => {
    for (const priority of ["blocking", "standard", "low"] as const) {
      expect(PRIORITY_META[priority].label).toBeTruthy();
      expect(PRIORITY_META[priority].className).toContain("border");
    }
  });
});
