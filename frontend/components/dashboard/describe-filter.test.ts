import { describe, expect, it } from "vitest";

import { describeFilter } from "./file-table";

/**
 * The filtered-empty sentence (LP-UI-034).
 *
 * "No files match your current filters" is what this replaces, and it fails the
 * ticket's own rule: it does not tell a processor what to undo. Every assertion
 * here is about naming the thing they can click.
 */
describe("describeFilter", () => {
  it("names the status filter, the query, and how many come back", () => {
    expect(
      describeFilter({ search: "ellis", statusLabel: "Blocked to submit", unfilteredTotal: 4 }),
    ).toBe("Nothing in Blocked to submit matches “ellis”. Clear the filters to see all 4.");
  });

  it("drops the query clause when only a status is set", () => {
    expect(describeFilter({ search: "  ", statusLabel: "Draft", unfilteredTotal: 12 })).toBe(
      "Nothing in Draft. Clear the filters to see all 12.",
    );
  });

  it("drops the status clause when only a search is set", () => {
    expect(describeFilter({ search: "ellis", statusLabel: null, unfilteredTotal: 4 })).toBe(
      "Nothing on this list matches “ellis”. Clear the filters to see all 4.",
    );
  });

  it("counts one file in words rather than saying 'all 1'", () => {
    expect(describeFilter({ search: "x", statusLabel: null, unfilteredTotal: 1 })).toContain(
      "see the one file",
    );
  });

  it("promises no count when it does not have one", () => {
    // "See all four" is a claim. Making it while the count is still loading sends
    // a processor looking for files that may not be there.
    const text = describeFilter({ search: "x", statusLabel: null, unfilteredTotal: null });
    expect(text).toBe("Nothing on this list matches “x”. Clear the filters to see every file.");
    expect(text).not.toMatch(/\d/);
  });

  it("degrades to the general sentence with no summary at all", () => {
    expect(describeFilter()).toBe(
      "Nothing matches the filters on this list. Clear them to see every file.",
    );
  });
});
