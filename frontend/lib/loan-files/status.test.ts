import { FILTER_PILLS, statusLabel, statusesForFilter } from "@/lib/loan-files/status";
import { LOAN_FILE_STATUS, type StatusMeta, type Tone } from "@/lib/status";
import type { LoanFileStatus } from "@/lib/types/loan-file";
import { describe, expect, it } from "vitest";

const TONES: Tone[] = ["blocking", "attention", "verified", "progress", "neutral", "ai"];

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

describe("LOAN_FILE_STATUS", () => {
  it("has an entry for every status", () => {
    for (const status of ALL_STATUSES) {
      // Indexed DIRECTLY. Routing this through `resolveStatus` is what made the
      // assertion vacuous: it synthesizes `{tone: "attention", label: …}` for any
      // key it does not know, so `label`/`tone` are truthy for EVERY string and a
      // deleted entry passed — a withdrawn file then rendered amber "Withdrawn"
      // through the fallback with the suite green.
      const meta: StatusMeta | undefined = LOAN_FILE_STATUS[status];
      expect(meta, `LOAN_FILE_STATUS has no entry for "${status}"`).toBeDefined();
      expect(meta?.label.trim()).toBeTruthy();
      expect(TONES).toContain(meta?.tone);
    }
  });

  it("ALL_STATUSES is the whole union, so the check above cannot go stale", () => {
    // The map is typed `Record<LoanFileStatus, StatusMeta>`, so a new union member
    // is a compile error there. This is the other half: it fails until the new
    // member is added HERE too, rather than being silently skipped.
    expect(new Set(Object.keys(LOAN_FILE_STATUS))).toEqual(new Set(ALL_STATUSES));
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
