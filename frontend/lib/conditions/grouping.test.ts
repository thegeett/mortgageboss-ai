import type { Condition, OwnerHint } from "@/lib/types/conditions";
import { describe, expect, it } from "vitest";
import { groupConditions } from "./grouping";

/** Only the fields grouping reads; the rest of a `Condition` does not affect it. */
function row(code: string, sequence: number, owner: OwnerHint, heading: string): Condition {
  return {
    lender_code: code,
    sequence,
    effective_owner: owner,
    prep_status: "to_do",
    bucket_heading: heading,
  } as Condition;
}

const PTD = "UW - Prior To Final Approval (PTD)";
const PTF = "Closing (PTF)";

// Round 1's Closing (PTF) block in sheet order: Title, Processor x3, Title.
const ROUND_1_PTF = [
  row("1947", 7, "title", PTF),
  row("1582", 8, "processor", PTF),
  row("0006", 9, "processor", PTF),
  row("0007", 10, "processor", PTF),
  row("6378", 11, "title", PTF),
];

describe("grouping the conditions list", () => {
  it("draws each owner ONCE, not once per run (LP-913 review)", () => {
    const groups = groupConditions(ROUND_1_PTF, "owner");

    expect(groups.map((group) => group.key)).toEqual(["Title", "Processor"]);
    expect(groups[0]?.rows.map((r) => r.lender_code)).toEqual(["1947", "6378"]);
  });

  it("keeps a heading as a run, so a heading printed twice is two groups", () => {
    const rows = [
      row("1228", 1, "unknown", PTD),
      row("1947", 2, "title", PTF),
      row("7086", 3, "borrower", PTD),
    ];

    expect(groupConditions(rows, "heading").map((group) => group.key)).toEqual([PTD, PTF, PTD]);
  });

  it("keeps sheet order inside every group, whatever order the rows arrive in", () => {
    const groups = groupConditions([...ROUND_1_PTF].reverse(), "owner");

    expect(groups.map((group) => group.rows.map((r) => r.lender_code))).toEqual([
      ["1947", "6378"],
      ["1582", "0006", "0007"],
    ]);
  });
});
