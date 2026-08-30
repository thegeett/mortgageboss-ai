import { describe, expect, it } from "vitest";

import {
  FIT,
  ZOOM_STEPS,
  canZoomIn,
  canZoomOut,
  sharpUpTo,
  zoomIn,
  zoomLabel,
  zoomOut,
  zoomWidth,
} from "./zoom";

describe("zoom steps", () => {
  it("opens at fit, which is one of the steps", () => {
    expect(ZOOM_STEPS).toContain(FIT);
  });

  it("is ordered, so stepping is monotonic", () => {
    const sorted = [...ZOOM_STEPS].sort((a, b) => a - b);
    expect([...ZOOM_STEPS]).toEqual(sorted);
  });

  it("steps up and down through the ladder", () => {
    expect(zoomIn(1)).toBe(1.25);
    expect(zoomOut(1)).toBe(0.75);
    expect(zoomIn(0.5)).toBe(0.75);
    expect(zoomOut(2)).toBe(1.5);
  });

  it("stops at the ends rather than running off them", () => {
    // Returning the same value keeps the caller's state valid; returning
    // undefined would set the zoom to NaN and blank the page.
    expect(zoomIn(2)).toBe(2);
    expect(zoomOut(0.5)).toBe(0.5);
    expect(canZoomIn(2)).toBe(false);
    expect(canZoomOut(0.5)).toBe(false);
    expect(canZoomIn(1)).toBe(true);
    expect(canZoomOut(1)).toBe(true);
  });

  it("recovers from a value that is not on the ladder", () => {
    // A persisted or hand-edited zoom must not strand the controls.
    expect(zoomIn(1.1)).toBe(1.25);
    expect(zoomOut(1.1)).toBe(1);
  });

  it("says how far a given pane can be zoomed before the text softens", () => {
    // REAL ARITHMETIC, not a restated number. The server renders at 2x
    // (`DEFAULT_ZOOM` in page_render.py), so a 612pt US Letter page is 1224px.
    const rendered = 612 * 2;
    expect(sharpUpTo(rendered, 736)).toBeCloseTo(1.66, 2);
    expect(sharpUpTo(rendered, 1024)).toBeCloseTo(1.2, 2);
  });

  it("reports a WIDE pane as already soft at fit, which a constant cannot", () => {
    // The case that shows the old `SHARP_TO = 1.65` was a category error: it is
    // not a property of the render, it is a ratio against a pane the processor
    // drags. At 1440px the fit view is already scaling past the pixels it has.
    expect(sharpUpTo(612 * 2, 1440)).toBeLessThan(FIT);
  });

  it("treats a pane not yet measured as nothing to warn about", () => {
    // Not a guard — division already returns Infinity. Asserted because the
    // BEHAVIOUR matters (no false "soft" warning before layout), and stated as
    // behaviour so nobody adds a branch to produce what already happens.
    expect(sharpUpTo(1224, 0)).toBe(Number.POSITIVE_INFINITY);
  });
});
