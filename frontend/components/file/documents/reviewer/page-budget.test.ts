import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { PAGE_COLUMN_REM, ZOOM_STEPS } from "./zoom";

/**
 * The backend's render budget still covers what this client can display (LP-704).
 *
 * `MAX_RENDERED_EDGE` in `services/page_render.py` is not an arbitrary number: it
 * is this column, times the largest zoom step, times a 2x device pixel ratio.
 * Pixels beyond it are shipped, decoded and never seen — so the budget clips them
 * on purpose.
 *
 * NOTHING CONNECTED THE TWO. Widening the reviewer's column, or adding a zoom
 * step above 2, would have left the budget unchanged and quietly turned it from
 * "trims waste" into "costs sharpness" — a backend constant silently derived from
 * a frontend layout constant, with no test in either tree that reads both. The
 * ticket said as much and could not find a guard worth having; this is that
 * guard, and it is the pattern `split-agreement.test.ts` and
 * `extraction-contracts.test.tsx` already use in this repo.
 */
const RENDER_SOURCE = "../../../../../backend/app/services/page_render.py";

function backendConstant(name: string): number {
  const source = readFileSync(new URL(RENDER_SOURCE, import.meta.url), "utf8");
  const match = new RegExp(`^${name}\\s*=\\s*([0-9.]+)`, "m").exec(source);
  if (!match?.[1]) throw new Error(`${name} not found in page_render.py`);
  return Number(match[1]);
}

describe("the render budget and the column it was derived from", () => {
  it("reads the backend constants at all", () => {
    // The positive control. A regex that matched nothing would make the
    // comparison below pass over NaN, or throw somewhere less legible.
    expect(backendConstant("MAX_RENDERED_EDGE")).toBeGreaterThan(0);
    expect(backendConstant("DEFAULT_ZOOM")).toBeGreaterThan(0);
  });

  it("covers this column at the largest zoom this client offers", () => {
    const DEVICE_PIXEL_RATIO = 2; // the ratio the budget was sized for
    const REM_PX = 16;
    const widest = Math.max(...ZOOM_STEPS);
    const devicePixels = PAGE_COLUMN_REM * REM_PX * widest * DEVICE_PIXEL_RATIO;

    const budget = backendConstant("MAX_RENDERED_EDGE");
    const why = `a ${PAGE_COLUMN_REM}rem column at ${widest}x on a ${DEVICE_PIXEL_RATIO}x screen needs ${devicePixels}px, and page_render.py budgets ${budget}px. Raise MAX_RENDERED_EDGE, or accept that the extra zoom costs sharpness rather than showing more page.`;
    expect(devicePixels, why).toBeLessThanOrEqual(budget);
  });

  it("does not budget wastefully more than the client can show", () => {
    // The other direction, loosely: a budget far above what any client pixel can
    // use is shipping bytes nobody decodes. Generous — this is a smell test, not
    // a tight bound.
    const ceiling = PAGE_COLUMN_REM * 16 * Math.max(...ZOOM_STEPS) * 2 * 1.5;
    expect(backendConstant("MAX_RENDERED_EDGE")).toBeLessThanOrEqual(ceiling);
  });
});
