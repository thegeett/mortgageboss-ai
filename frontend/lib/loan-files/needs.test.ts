import {
  PRIORITY_META,
  categoryLabel,
  groupNeeds,
  isProposed,
  outstandingNeedsCount,
  proposedNeedsCount,
  sourceLabel,
} from "@/lib/loan-files/needs";
import type {
  NeedsItemDisposition,
  NeedsItemOrigin,
  NeedsItemPublic,
  NeedsItemStatus,
} from "@/lib/types/needs-item";
import { describe, expect, it } from "vitest";

function need(status: NeedsItemStatus, overrides: Partial<NeedsItemPublic> = {}): NeedsItemPublic {
  return {
    id: `${status}-${overrides.disposition ?? "x"}`,
    title: "Pay stubs",
    description: null,
    category: "income_employment",
    needs_type: "pay_stub",
    status,
    priority: "standard",
    origin: "floor",
    disposition: "confirmed",
    reasoning: null,
    reason: null,
    borrower_id: null,
    satisfied_by_document_id: null,
    satisfied_by_document_filename: null,
    satisfied_at: null,
    created_at: "2026-06-19T12:00:00Z",
    ...overrides,
  };
}

describe("groupNeeds", () => {
  it("buckets needs into action-oriented groups, action first, dropping empties", () => {
    const groups = groupNeeds([
      need("verified"),
      need("pending"),
      need("received"),
      need("waived"),
      need("rejected"),
    ]);
    expect(groups.map((group) => group.key)).toEqual([
      "needs_action",
      "in_review",
      "complete",
      "set_aside",
    ]);
    // pending + rejected both roll up under "needs action".
    expect(groups[0]?.items).toHaveLength(2);
  });

  it("omits a group with no items", () => {
    const groups = groupNeeds([need("verified")]);
    expect(groups).toHaveLength(1);
    expect(groups[0]?.key).toBe("complete");
  });
});

describe("outstandingNeedsCount", () => {
  it("counts only the needs-action states (pending/requested/rejected)", () => {
    const needs = [
      need("pending"),
      need("requested"),
      need("rejected"),
      need("received"),
      need("verified"),
      need("waived"),
    ];
    expect(outstandingNeedsCount(needs)).toBe(3);
  });

  it("is 0 for an empty list", () => {
    expect(outstandingNeedsCount([])).toBe(0);
  });
});

describe("proposedNeedsCount / isProposed", () => {
  it("counts needs still awaiting confirmation", () => {
    const needs = [
      need("pending", { disposition: "proposed" as NeedsItemDisposition }),
      need("pending", { disposition: "confirmed" as NeedsItemDisposition }),
    ];
    expect(proposedNeedsCount(needs)).toBe(1);
    expect(isProposed(needs[0] as NeedsItemPublic)).toBe(true);
    expect(isProposed(needs[1] as NeedsItemPublic)).toBe(false);
  });
});

describe("sourceLabel", () => {
  it("maps each origin to a short provenance tag", () => {
    const cases: [NeedsItemOrigin, string][] = [
      ["ai_reasoning", "AI"],
      ["suggestion", "Suggested"],
      ["floor", "Baseline"],
      ["manual", "Added"],
    ];
    for (const [origin, label] of cases) {
      expect(sourceLabel(origin)).toBe(label);
    }
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
