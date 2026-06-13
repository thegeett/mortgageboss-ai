import { FILTER_PILLS, STATUS_META, statusLabel, statusesForFilter } from "@/lib/loan-files/status";
import type { LoanFileStatus } from "@/lib/types/loan-file";
import { describe, expect, it } from "vitest";

const ALL_STATUSES: LoanFileStatus[] = [
  "draft",
  "in_processing",
  "ready_to_submit",
  "submitted",
  "in_conditions",
  "clear_to_close",
  "closed",
  "withdrawn",
];

describe("STATUS_META", () => {
  it("maps every status to a label and badge classes", () => {
    for (const status of ALL_STATUSES) {
      expect(STATUS_META[status].label).toBeTruthy();
      expect(STATUS_META[status].className).toContain("border");
    }
  });

  it("statusLabel returns the mapped label", () => {
    expect(statusLabel("in_conditions")).toBe("In conditions");
  });
});

describe("statusesForFilter", () => {
  it("All → no statuses (no filter)", () => {
    expect(statusesForFilter("all")).toEqual([]);
  });

  it("Active → the in-progress statuses (incl. clear_to_close)", () => {
    expect(statusesForFilter("active")).toEqual([
      "draft",
      "in_processing",
      "ready_to_submit",
      "submitted",
      "clear_to_close",
    ]);
  });

  it("Action needed → in_conditions", () => {
    expect(statusesForFilter("action_needed")).toEqual(["in_conditions"]);
  });

  it("Completed → closed + withdrawn", () => {
    expect(statusesForFilter("completed")).toEqual(["closed", "withdrawn"]);
  });
});

describe("filter pill groupings", () => {
  it("the non-All groups are disjoint and cover all eight statuses", () => {
    const grouped = FILTER_PILLS.filter((pill) => pill.key !== "all").flatMap(
      (pill) => pill.statuses,
    );
    expect(grouped).toHaveLength(ALL_STATUSES.length); // disjoint (no dupes) + complete
    expect(new Set(grouped)).toEqual(new Set(ALL_STATUSES));
  });
});
