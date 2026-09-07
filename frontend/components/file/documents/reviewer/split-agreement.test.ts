/**
 * The browser's clamp and the server's validator must accept the same splits.
 *
 * `reviewer_pane_split` is stored, so the server validates it — a client could
 * otherwise persist a pane it cannot grab back, and a refresh would not fix it.
 * That makes two definitions of "a usable split", in two languages, and they
 * agree today by coincidence rather than by construction: raise the server's
 * floor and the browser goes on producing splits it now rejects, so a drag
 * saves nothing and says nothing.
 *
 * Read out of the Python source, the same instrument `ledger-assets.test.ts`
 * uses for the design assets. Restating the numbers here would be the second
 * definition this is written to prevent.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { clampSplit } from "./reviewer-shell";

const VALIDATOR = readFileSync(
  new URL("../../../../../backend/app/schemas/preferences.py", import.meta.url),
  "utf8",
);

/** The numbers the server enforces, taken from the validator itself. */
function serverRules(): { minPane: number; maxTwo: number } {
  const min = /pct < (\d+) for pct in value/.exec(VALIDATOR);
  const max = /sum\(value\) > (\d+)/.exec(VALIDATOR);
  if (!min?.[1] || !max?.[1]) {
    throw new Error("the pane-split validator no longer has the shape this test reads");
  }
  return { minPane: Number(min[1]), maxTwo: Number(max[1]) };
}

describe("the pane split means the same thing on both sides", () => {
  const { minPane, maxTwo } = serverRules();

  it.each([
    [0, 0],
    [95, 95],
    [60, 60],
    [22, 53],
    [100, 0],
    [10, 80],
    [80, 10],
    [-5, 200],
  ])("clampSplit([%i, %i]) is a split the server accepts", (list, canvas) => {
    const [l, c] = clampSplit([list, canvas]);
    expect(l, "the server rejects a pane below its floor").toBeGreaterThanOrEqual(minPane);
    expect(c, "the server rejects a pane below its floor").toBeGreaterThanOrEqual(minPane);
    expect(l + c, "the server keeps a third pane").toBeLessThanOrEqual(maxTwo);
    expect(Number.isInteger(l) && Number.isInteger(c), "the column is list[int]").toBe(true);
  });

  it("the default split is one the server would accept", () => {
    // It is sent on the first save after a drag from the default, so a default
    // outside the server's rules is a first save that always fails.
    const [l, c] = clampSplit([22, 50]);
    expect(l).toBeGreaterThanOrEqual(minPane);
    expect(c).toBeGreaterThanOrEqual(minPane);
    expect(l + c).toBeLessThanOrEqual(maxTwo);
  });
});
