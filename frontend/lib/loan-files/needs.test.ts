import {
  categoryLabel,
  groupNeeds,
  isProposed,
  outstandingNeedsCount,
  proposedNeedsCount,
  sourceLabel,
} from "@/lib/loan-files/needs";
import { NEEDS_PRIORITY } from "@/lib/status";
import type {
  NeedsItemDisposition,
  NeedsItemOrigin,
  NeedsItemPriority,
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
    explanation: null,
    reasoning: null,
    reason: null,
    borrower_id: null,
    satisfied_by_document_id: null,
    satisfied_by_document_filename: null,
    satisfied_at: null,
    requires_coverage_confirmation: false,
    matching_documents: [],
    source: null,
    possible_duplicate_of: null,
    possibly_covered_by: null,
    coverage_note: null,
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

describe("an unrecognised needs status", () => {
  // NeedsDashboard calls groupNeeds before rendering any card, so the unguarded
  // `buckets[NEEDS_GROUP[need.status]].push(...)` threw a TypeError and blanked
  // the whole page — including the needs it did understand. The casts are the
  // point: this is a value the backend shipped before the frontend knew its name.
  const unknown = need("escalated" as NeedsItemStatus);
  const known = need("pending");

  it("does not take the dashboard down, and does not hide the needs around it", () => {
    const groups = groupNeeds([known, unknown]);
    expect(groups.flatMap((g) => g.items)).toHaveLength(2);
  });

  it("lands in the chase pile, where someone will see it", () => {
    const groups = groupNeeds([unknown]);
    expect(groups.map((g) => g.key)).toEqual(["needs_action"]);
  });

  it("is counted by outstandingNeedsCount, which must agree with the group", () => {
    expect(outstandingNeedsCount([unknown])).toBe(1);
  });
});

describe("NEEDS_PRIORITY", () => {
  const ALL_PRIORITIES: NeedsItemPriority[] = ["blocking", "standard", "low"];

  it("has an entry for every priority", () => {
    for (const priority of ALL_PRIORITIES) {
      // Directly, not via `resolveStatus` — see the note in status.test.ts: the
      // fallback makes the same assertion hold for any string at all.
      const meta = NEEDS_PRIORITY[priority];
      expect(meta, `NEEDS_PRIORITY has no entry for "${priority}"`).toBeDefined();
      expect(meta?.label.trim()).toBeTruthy();
    }
  });

  it("ALL_PRIORITIES is the whole union", () => {
    expect(new Set(Object.keys(NEEDS_PRIORITY))).toEqual(new Set(ALL_PRIORITIES));
  });
});
